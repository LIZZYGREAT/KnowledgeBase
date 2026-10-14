from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.terms import router as terms_router
from backend.app.db.connection import connect_database
from backend.app.domain.ai import TermDiscoveryOutput
from backend.app.domain.term_discovery import TermDiscoverySettings
from backend.app.domain.term_runtime import TermCandidateEvidenceInput
from backend.app.repositories.pdf_corpus_repository import PdfCorpusRepository
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.repositories.term_discovery_repository import TermDiscoveryRepository
from backend.app.services.knowledge_state_service import KnowledgeStateService
from backend.app.services.learning_context_service import LearningContextService
from backend.app.services.learning_context_sync_entries import render_entry
from backend.app.services.pdf_corpus_service import PdfCorpusService
from backend.app.services.term_candidate_service import (
    TermCandidateConflict,
    TermCandidateService,
)
from backend.app.services.term_discovery_service import (
    DiscoveryCorpus,
    TermDiscoveryService,
    _allocate_lane_budgets,
    _dynamic_allowance,
    _discovery_focus,
    _external_query,
    _covered_by_learning_context,
    _learning_context_headings,
)
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver
from backend.app.services.vocabulary_mining import mine_vocabulary
from backend.app.services.wikipedia_discovery import ExternalDiscoveryResult


def test_inbox_full_skips_snapshot_pdf_extraction_and_ai(tmp_path):
    connection, service, candidate_service, pdf_service, gateway = _service(tmp_path)
    evidence = [
        TermCandidateEvidenceInput(
            origin_type="external",
            origin_id="test-origin-{}".format(index),
            mention="Example term {}".format(index),
        )
        for index in range(12)
    ]
    for index, item in enumerate(evidence):
        candidate_service.create_candidate(
            item.mention, "concept", [item]
        )

    run = service.run()

    assert run.status == "skipped_capacity"
    assert run.snapshot == {"discovery_mode": "general"}
    assert pdf_service.calls == []
    assert gateway.calls == []
    assert run.candidate_count == 0
    connection.close()


def test_run_creates_only_non_stretch_candidate_with_explainable_assessment(tmp_path):
    output = {
        "candidates": [
            _suggestion(
                "elastic weight consolidation",
                "concept",
                "Elastic weight consolidation limits catastrophic forgetting.",
                "core_gap",
                "It connects parameter importance to the current continual learning focus.",
            ),
            _suggestion(
                "advanced consolidation variant",
                "concept",
                "An advanced consolidation variant builds on elastic weight consolidation.",
                "stretch",
                "The source assumes several missing optimization prerequisites.",
            ),
        ]
    }
    connection, service, candidate_service, pdf_service, gateway = _service(
        tmp_path, output
    )
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["concept"], focus_override="continual learning"
        )
    )

    run = service.run()

    assert run.status == "success"
    assert [(item.outcome, item.mention) for item in run.items] == [
        ("created", "elastic weight consolidation"),
        ("stretch", "advanced consolidation variant"),
    ]
    assert run.candidate_count == 1
    assert run.lane_budgets["concept"] == 5
    assert run.raw_counts == {"concept": 2, "entity": 0, "vocabulary": 0}
    assert [item.outcome for item in run.items] == ["created", "stretch"]
    assert candidate_service.list_candidates("pending")[0].discovery_assessment.why_now.startswith(
        "It connects"
    )
    assert [call[0] for call in gateway.calls] == ["discover_terms"]
    assert pdf_service.calls == ["source-alpha"]
    assert service.get_run(run.id).items[1].outcome == "stretch"
    connection.close()


def test_run_focus_ignores_recent_activity_and_records_personalized_focus(tmp_path, monkeypatch):
    connection, service, _candidate_service, _pdf_service, gateway = _service(tmp_path)
    service.update_settings(TermDiscoverySettings(enabled_lanes=["concept"]))
    monkeypatch.setattr(
        "backend.app.services.term_discovery_service._focus_context",
        lambda _root, _settings: ["Continual Learning"],
    )

    class SnapshotWithRecentTerms:
        def build_snapshot(self, explicit_focus):
            return {
                "focus": {
                    "explicit": list(explicit_focus),
                    "recent_terms": [
                        {"id": "icarl", "title": "iCaRL"},
                        {"id": "herding", "title": "Herding"},
                    ],
                    "recent_topics": [],
                    "recent_domains": [],
                },
                "knowledge": {},
                "activity": {"recent_documents": []},
                "term_states": {},
            }

    service.knowledge_state = SnapshotWithRecentTerms()

    run = service.run()

    discovery_calls = [context for task, context in gateway.calls if task == "discover_terms"]
    assert run.status == "success"
    assert discovery_calls
    assert run.snapshot["effective_focus"] == ["Continual Learning"]
    assert all(context["focus"] == run.snapshot["effective_focus"] for context in discovery_calls)
    connection.close()


def test_dynamic_quota_and_lane_backpressure_bound_each_run():
    assert [_dynamic_allowance(count) for count in (0, 3, 4, 7, 8, 11, 12)] == [
        5, 5, 3, 3, 1, 1, 0
    ]
    lane_capacities = {"concept": 5, "entity": 4, "vocabulary": 6}
    assert sum(
        _allocate_lane_budgets(
            ["concept", "entity", "vocabulary"],
            5,
            lane_capacities,
            {"concept": 0, "entity": 0, "vocabulary": 0},
        ).values()
    ) == 5
    assert _allocate_lane_budgets(
        ["concept", "entity", "vocabulary"],
        5,
        lane_capacities,
        {"concept": 5, "entity": 0, "vocabulary": 0},
    ) == {"concept": 0, "entity": 3, "vocabulary": 2}


def test_scheduled_check_runs_once_per_rolling_24_hours(tmp_path):
    _write_document(
        tmp_path,
        "selected-learning-note",
        "Continual Learning Notes",
        "Elastic weight consolidation limits catastrophic forgetting.",
        topics=["continual-learning"],
    )
    learning_context = LearningContextService(tmp_path)
    learning_context.set_sources(["selected-learning-note"])
    learning_context.sync_if_stale = lambda: {
        "state": "synced",
        "stale": False,
        "used_previous_context": False,
        "message": "学习上下文已是最新。",
    }
    connection, service, _candidate_service, pdf_service, gateway = _service(
        tmp_path,
        {
            "candidates": [
                _suggestion(
                    "elastic weight consolidation",
                    "concept",
                    "Elastic weight consolidation limits catastrophic forgetting.",
                    "core_gap",
                    "It connects to the current learning focus.",
                )
            ]
        },
        learning_context_service=learning_context,
    )
    now = datetime(2026, 10, 7, 10, tzinfo=timezone.utc)
    service.clock = lambda: now
    service.update_settings(TermDiscoverySettings(enabled_lanes=["concept"]))

    first = service.scheduled_check()
    second = service.scheduled_check()
    now += timedelta(hours=23, minutes=59)
    before_window = service.scheduled_check()
    _write_document(
        tmp_path,
        "selected-learning-note",
        "Continual Learning Notes",
        "Elastic weight consolidation limits catastrophic forgetting. "
        "The note now compares stability across sequential tasks.",
        topics=["continual-learning"],
    )
    now += timedelta(minutes=1)
    at_window = service.scheduled_check()

    assert first is not None
    assert first.trigger == "scheduled"
    assert first.status == "success"
    assert first.snapshot["discovery_mode"] == "personalized"
    assert first.items[0].source_id == "selected-learning-note"
    assert pdf_service.calls == []
    assert second is None
    assert before_window is None
    assert at_window is not None and at_window.trigger == "scheduled"
    assert [call[0] for call in gateway.calls] == [
        "discover_terms",
        "discover_terms",
    ]
    connection.close()


def test_daily_candidate_quota_does_not_reset_at_utc_midnight(tmp_path):
    output = {
        "candidates": [
            _suggestion(
                "elastic weight consolidation",
                "concept",
                "Elastic weight consolidation limits catastrophic forgetting.",
                "core_gap",
                "It connects to the current learning focus.",
            )
        ]
    }
    connection, service, _candidate_service, _pdf_service, _gateway = _service(
        tmp_path, output
    )
    now = datetime(2026, 10, 6, 23, 55, tzinfo=timezone.utc)
    service.clock = lambda: now
    service.update_settings(
        TermDiscoverySettings(enabled_lanes=["concept"], daily_max_new=1)
    )

    run = service.run()
    assert run.candidate_count == 1
    now += timedelta(minutes=10)
    assert service.get_state().daily_remaining == 0
    now += timedelta(hours=23, minutes=50)
    assert service.get_state().daily_remaining == 1
    connection.close()


def test_scheduled_accepted_note_is_not_recreated_after_focus_and_content_change(tmp_path):
    output = {
        "candidates": [
            {
                **_suggestion(
                    "elastic weight consolidation",
                    "concept",
                    "Elastic weight consolidation limits catastrophic forgetting.",
                    "core_gap",
                    "It connects to the current learning focus.",
                ),
                "existing_term_id": "accepted-term",
            }
        ]
    }
    connection, service, candidate_service, _pdf_service, _gateway = _service(
        tmp_path, output
    )
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()
    _write_term(
        tmp_path / "knowledge" / "terms" / "accepted-term.md",
        "accepted-term",
        "Accepted Term",
        "stub",
    )
    _write_document(
        tmp_path,
        "note-one",
        "Continual Learning Notes",
        "Elastic weight consolidation limits catastrophic forgetting. "
        "It protects previously learned tasks.",
        topics=["continual-learning"],
    )
    learning_context = LearningContextService(tmp_path)
    learning_context.set_sources(["note-one"])
    learning_context.sync_if_stale = lambda: {
        "state": "synced",
        "stale": False,
        "used_previous_context": False,
        "message": "学习上下文已是最新。",
    }
    service.learning_context = learning_context
    now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    service.clock = lambda: now
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["concept"], focus_override="continual learning"
        )
    )

    first = service.scheduled_check()
    assert first is not None and first.candidate_count == 1
    candidate = candidate_service.list_candidates("pending")[0]
    candidate_service.canonical_target_resolver = CanonicalTargetResolver(
        tmp_path, connection
    )
    accepted = candidate_service.accept_existing(candidate.id, "accepted-term")
    assert accepted.status == "accepted"

    now += timedelta(hours=24)
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["concept"], focus_override="continual learning systems"
        )
    )
    _write_document(
        tmp_path,
        "note-one",
        "Continual Learning Notes",
        "Elastic weight consolidation limits catastrophic forgetting. "
        "It protects previously learned tasks and supports stable retention.",
        topics=["continual-learning"],
    )
    second = service.scheduled_check()

    assert second is not None
    assert second.candidate_count == 0
    assert [(item.outcome, item.mention) for item in second.items] == [
        ("duplicate", "elastic weight consolidation")
    ]
    assert candidate_service.list_candidates("accepted")[0].id == candidate.id
    assert candidate_service.list_candidates("pending") == []
    connection.close()


@pytest.mark.parametrize(
    ("origin_type", "origin_id"),
    [
        ("document", "note-one"),
        ("source", "source-alpha"),
        ("research_work", "work-one"),
        ("external", "https://en.wikipedia.org/wiki/Elastic_weight_consolidation"),
    ],
)
def test_discovery_skips_accepted_evidence_for_same_origin_and_normalized_mention(
    tmp_path, origin_type, origin_id
):
    text = "ELASTIC WEIGHT CONSOLIDATION limits catastrophic forgetting."
    output = {
        "candidates": [
            {
                **_suggestion(
                    "ELASTIC WEIGHT CONSOLIDATION",
                    "concept",
                    text,
                    "core_gap",
                    "It connects to the current learning focus.",
                ),
                "existing_term_id": "accepted-term",
            }
        ]
    }
    connection, service, candidate_service, _pdf_service, _gateway = _service(
        tmp_path, output
    )
    _write_term(
        tmp_path / "knowledge" / "terms" / "accepted-term.md",
        "accepted-term",
        "Accepted Term",
        "stub",
    )
    if origin_type == "document":
        _write_document(tmp_path, origin_id, "Accepted Note", text)
    elif origin_type == "research_work":
        connection.execute(
            """INSERT INTO research_works (
                   id, canonical_key, title, normalized_title, authors_json,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, '[]', 'now', 'now')""",
            (origin_id, "doi:10.1/work-one", "Accepted Research Work", "accepted work"),
        )
    candidate_service.canonical_target_resolver = CanonicalTargetResolver(
        tmp_path, connection
    )
    accepted_candidate = candidate_service.create_candidate(
        "elastic weight consolidation",
        "concept",
        [
            TermCandidateEvidenceInput(
                origin_type=origin_type,
                origin_id=origin_id,
                mention="elastic weight consolidation",
                context_excerpt="Elastic weight consolidation limits catastrophic forgetting.",
                rationale="Previously accepted evidence.",
            )
        ],
        preferred_term_id="accepted-term",
    )
    accepted_candidate = candidate_service.accept_existing(
        accepted_candidate.id, "accepted-term"
    )
    assert accepted_candidate.status == "accepted"

    corpus_origin = SimpleNamespace(
        id=origin_id, title="Corpus Title", domains=(), topics=()
    )
    corpus = DiscoveryCorpus(
        origin_type,
        origin_id,
        corpus_origin,
        text,
        "changed-text-hash",
        "{}:analysis".format(origin_id),
        ("concept",),
    )
    registry = TermRegistry.load(tmp_path / "knowledge" / "terms")
    budgets = {"concept": 1, "entity": 0, "vocabulary": 0}
    raw_counts = {"concept": 0, "entity": 0, "vocabulary": 0}
    filtered_counts = {"concept": 0, "entity": 0, "vocabulary": 0}
    items = []
    errors = []

    created = service._process_additional_corpora(
        [corpus],
        "run-accepted",
        {},
        ["continual learning"],
        service._learning_context([], service._learning_preferences()),
        registry,
        TermResolver(registry),
        "new-focus-hash",
        budgets,
        raw_counts,
        filtered_counts,
        items,
        errors,
    )

    assert created == 0
    assert filtered_counts["concept"] == 1
    assert [(item.outcome, item.source_id) for item in items] == [
        ("duplicate", origin_id)
    ]
    assert errors == []
    connection.close()


def test_discovery_skips_note_already_related_to_existing_term_without_candidate_evidence(
    tmp_path,
):
    text = "A later note section explains elastic consolidation in more detail."
    output = {
        "candidates": [
            {
                **_suggestion(
                    "elastic consolidation",
                    "concept",
                    "A later note section explains elastic consolidation in more detail.",
                    "core_gap",
                    "It connects to the current learning focus.",
                ),
                "existing_term_id": "accepted-term",
            }
        ]
    }
    connection, service, _candidate_service, _pdf_service, _gateway = _service(
        tmp_path, output
    )
    _write_term(
        tmp_path / "knowledge" / "terms" / "accepted-term.md",
        "accepted-term",
        "Accepted Term",
        "stub",
    )
    _write_document(tmp_path, "note-one", "Continual Learning Notes", text)
    connection.execute(
        """INSERT INTO term_entity_relations (
               id, entity_type, entity_id, term_id,
               created_from_candidate_id, created_at
           ) VALUES ('accepted-relation', 'document', 'note-one',
                     'accepted-term', NULL, '2026-10-07T00:00:00+00:00')"""
    )
    registry = TermRegistry.load(tmp_path / "knowledge" / "terms")
    corpus = DiscoveryCorpus(
        "document",
        "note-one",
        SimpleNamespace(id="note-one", title="Continual Learning Notes", domains=(), topics=()),
        text,
        "updated-note-content-hash",
        "note-one:analysis",
        ("concept",),
    )
    budgets = {"concept": 1, "entity": 0, "vocabulary": 0}
    raw_counts = {"concept": 0, "entity": 0, "vocabulary": 0}
    filtered_counts = {"concept": 0, "entity": 0, "vocabulary": 0}
    items = []
    errors = []

    created = service._process_additional_corpora(
        [corpus],
        "run-related",
        {},
        ["continual learning"],
        service._learning_context([], service._learning_preferences()),
        registry,
        TermResolver(registry),
        "new-focus-hash",
        budgets,
        raw_counts,
        filtered_counts,
        items,
        errors,
    )

    assert created == 0
    assert filtered_counts["concept"] == 1
    assert [item.outcome for item in items] == ["duplicate"]
    assert connection.execute(
        "SELECT COUNT(*) FROM term_candidates"
    ).fetchone()[0] == 0
    connection.close()


def test_scheduled_check_is_idle_without_a_local_pdf(tmp_path):
    connection, service, _candidate_service, _pdf_service, gateway = _service(tmp_path)
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()

    run = service.scheduled_check()

    assert run is None
    assert service.list_runs() == []
    assert gateway.calls == []
    connection.close()


def test_heading_only_note_is_not_scheduled_as_a_discovery_corpus(tmp_path):
    connection, service, _candidate_service, _pdf_service, gateway = _service(tmp_path)
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()
    _write_document(
        tmp_path,
        "note-empty",
        "Empty Note",
        "# Empty Note",
    )
    service.update_settings(TermDiscoverySettings(enabled_lanes=["concept"]))

    run = service.scheduled_check()

    assert run is None
    assert service.list_runs() == []
    assert gateway.calls == []
    connection.close()


def test_external_discovery_is_disabled_by_default(tmp_path):
    external = _FakeExternalDiscovery([])
    connection, service, _candidate_service, _pdf_service, gateway = _service(
        tmp_path, external_discovery=external
    )
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()

    run = service.run()

    assert service.get_settings().external_enabled is False
    assert external.calls == []
    assert gateway.calls == []
    assert run.status == "success"
    connection.close()


def test_external_discovery_creates_wikipedia_evidence_with_focus_query(tmp_path):
    output = {
        "candidates": [
            _suggestion(
                "elastic weight consolidation",
                "concept",
                "Elastic weight consolidation is a regularization method for continual learning.",
                "core_gap",
                "This method directly supports the current continual learning focus.",
            )
        ]
    }
    result = ExternalDiscoveryResult(
        url="https://en.wikipedia.org/wiki/Elastic_weight_consolidation",
        title="Elastic weight consolidation",
        snippet="Elastic weight consolidation is a regularization method for continual learning.",
    )
    external = _FakeExternalDiscovery([result])
    connection, service, candidate_service, _pdf_service, gateway = _service(
        tmp_path, output, external_discovery=external
    )
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["concept"],
            focus_override="continual learning",
            external_enabled=True,
        )
    )

    run = service.run()

    candidate = candidate_service.list_candidates("pending")[0]
    evidence = candidate_service.get_candidate(candidate.id).evidence[0]
    assert run.candidate_count == 1
    assert len(external.calls) == 1
    assert external.calls[0] == ("continual learning", 2)
    assert [call[1]["lane"] for call in gateway.calls] == ["concept"]
    assert evidence.origin_type == "external"
    assert evidence.origin_id == result.url
    assert evidence.origin_title == result.title
    assert evidence.context_excerpt == result.snippet
    connection.close()


def test_notes_run_before_pdfs_and_external_search_waits_for_remaining_budget(tmp_path):
    output = {
        "candidates": [
            _suggestion(
                "elastic weight consolidation",
                "concept",
                "Elastic weight consolidation limits catastrophic forgetting.",
                "core_gap",
                "It connects directly to the current learning focus.",
            )
        ]
    }
    external = _FakeExternalDiscovery([])
    connection, service, candidate_service, pdf_service, gateway = _service(
        tmp_path, output, external_discovery=external
    )
    _write_document(
        tmp_path,
        "note-one",
        "Continual Learning Notes",
        "Elastic weight consolidation limits catastrophic forgetting.",
        topics=["continual-learning"],
    )
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["concept"],
            lane_capacities={"concept": 1, "entity": 4, "vocabulary": 6},
            focus_override="continual learning",
            external_enabled=True,
        )
    )

    run = service.run()

    candidate = candidate_service.list_candidates("pending")[0]
    evidence = candidate_service.get_candidate(candidate.id).evidence[0]
    assert run.candidate_count == 1
    assert run.items[0].source_id == "note-one"
    assert evidence.origin_type == "document"
    assert pdf_service.calls == []
    assert external.calls == []
    assert [call[1]["source"]["id"] for call in gateway.calls] == ["note-one"]
    connection.close()


def test_external_query_uses_configured_focus_without_recent_activity():
    explicit_focus = [
        "continual learning",
        "Continual Learning Profile",
        "Class-Incremental Learning",
        "continual learning methods",
        "class incremental learning",
    ]
    snapshot = {
        "focus": {
            "recent_terms": [
                {"title": "iCaRL"},
                {"title": "Herding"},
            ],
            "recent_topics": ["exemplar selection"],
            "recent_domains": ["machine-learning"],
        }
    }

    focus = _discovery_focus(
        explicit_focus, snapshot, focus_override="continual learning"
    )

    assert focus[:5] == [
        "continual learning",
        "Continual Learning Profile",
        "Class-Incremental Learning",
        "continual learning methods",
        "class incremental learning",
    ]
    query = _external_query(focus)
    assert query == (
        "continual learning Continual Learning Profile Class-Incremental Learning "
        "continual learning methods"
    )
    assert "iCaRL" not in query


def test_scheduled_discovery_ignores_pdf_external_and_unselected_course(tmp_path):
    external = _FakeExternalDiscovery([])
    connection, service, _candidate_service, pdf_service, gateway = _service(
        tmp_path, external_discovery=external
    )
    course_path = (
        tmp_path / "knowledge" / "documents" / "courses" / "ethernet-course.md"
    )
    course_path.parent.mkdir(parents=True, exist_ok=True)
    course_path.write_text(
        "---\nschema_version: 1\nid: ethernet-course\ntitle: Ethernet course\n"
        "type: course-note\ndomains: []\ntopics: []\ntags: []\nsources: []\n"
        "---\n\nEthernet frames connect devices in a local network.\n",
        encoding="utf-8",
    )
    learning_context = LearningContextService(tmp_path)
    learning_context.set_sources([])
    service.learning_context = learning_context
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["entity"],
            focus_override="continual learning systems",
            external_enabled=True,
        )
    )

    run = service.scheduled_check()

    assert run is None
    assert service.list_runs() == []
    assert pdf_service.calls == []
    assert gateway.calls == []
    assert external.calls == []

    general = service.run(discovery_mode="general")

    assert general.trigger == "manual"
    assert general.snapshot["discovery_mode"] == "general"
    assert len(external.calls) == 1
    assert external.calls[0] == ("continual learning systems", 2)
    connection.close()


def test_changed_note_is_discovered_incrementally_without_a_local_pdf(tmp_path):
    output = {
        "candidates": [
            _suggestion(
                "performance on previously learned classes",
                "concept",
                "Performance on previously learned classes drops sharply.",
                "core_gap",
                "This note connects retention to the current continual learning focus.",
            )
        ]
    }
    connection, service, candidate_service, _pdf_service, gateway = _service(
        tmp_path, output
    )
    service.update_settings(TermDiscoverySettings(enabled_lanes=["concept"]))
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()
    _write_document(
        tmp_path,
        "note-one",
        "Continual Learning Notes",
        """Performance on previously learned classes drops sharply. This pattern
        signals that a model has lost prior capability after learning a new task.
        Continual learning systems measure retention across sequential tasks.""",
        domains=["machine-learning"],
        topics=["continual-learning"],
    )
    learning_context = LearningContextService(tmp_path)
    learning_context.set_sources(["note-one"])
    learning_context.sync_if_stale = lambda: {
        "state": "synced",
        "stale": False,
        "used_previous_context": False,
        "message": "学习上下文已是最新。",
    }
    service.learning_context = learning_context

    first = service.scheduled_check()
    second = service.run()

    assert first is not None, "scheduled check should run for an eligible note"
    assert first.candidate_count == 1, first.model_dump()
    candidate = candidate_service.list_candidates("pending")[0]
    evidence = candidate_service.get_candidate(candidate.id).evidence
    assert first.items[0].source_id == "note-one"
    assert evidence[0].origin_type == "document"
    assert evidence[0].origin_id == "note-one"
    assert second is not None and second.candidate_count == 0
    assert len(gateway.calls_by_task("discover_terms")) == 1
    connection.close()


def test_deleted_candidate_reopens_same_note_discovery_cache_without_resetting_quota(
    tmp_path,
):
    output = {
        "candidates": [
            _suggestion(
                "performance on previously learned classes",
                "concept",
                "Performance on previously learned classes drops sharply.",
                "core_gap",
                "This note connects retention to the current continual learning focus.",
            )
        ]
    }
    connection, service, candidate_service, _pdf_service, gateway = _service(
        tmp_path, output
    )
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["concept"],
            daily_max_new=2,
            focus_override="continual learning",
        )
    )
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()
    _write_document(
        tmp_path,
        "note-one",
        "Continual Learning Notes",
        "Performance on previously learned classes drops sharply. This pattern "
        "signals that a model has lost prior capability after learning a new task. "
        "Continual learning systems measure retention across sequential tasks.",
        domains=["machine-learning"],
        topics=["continual-learning"],
    )
    service.repository.save_analysis_state(
        "document:note-one", "entity-text", "entity-focus", "entity", 1, "now"
    )
    service.repository.save_analysis_state(
        "document:note-three", "other-text", "other-focus", "concept", 1, "now"
    )

    first = service.run()
    candidate = candidate_service.list_candidates("pending")[0]
    cached_note = service.repository.get_analysis_state("document:note-one", "concept")
    assert first.candidate_count == 1
    assert cached_note is not None
    assert candidate_service.discovery_lock is service._lock
    assert service.get_state().daily_remaining == 1

    assert service._lock.try_acquire()
    try:
        with pytest.raises(TermCandidateConflict, match="Term Discovery is running"):
            candidate_service.delete_candidate(candidate.id)
        assert service.repository.get_analysis_state("document:note-one", "concept") == cached_note
    finally:
        service._lock.release()

    cached_run = service.run()
    assert cached_run.candidate_count == 0
    assert len(gateway.calls_by_task("discover_terms")) == 1
    assert candidate_service.list_candidates("pending")[0].id == candidate.id

    candidate_service.delete_candidate(candidate.id)
    assert service.repository.get_analysis_state("document:note-one", "concept") is None
    assert service.repository.get_analysis_state("document:note-one", "entity") is not None
    assert service.repository.get_analysis_state("document:note-three", "concept") is not None
    assert service.get_state().daily_remaining == 1

    rediscovered = service.run()
    candidates = candidate_service.list_candidates("pending")
    assert rediscovered.candidate_count == 1
    assert len(candidates) == 1
    assert candidates[0].id != candidate.id
    assert candidates[0].display_name == candidate.display_name
    assert len(gateway.calls_by_task("discover_terms")) == 2
    assert service.get_state().daily_remaining == 0
    connection.close()


def test_note_discovery_enriches_manual_candidate_without_creating_a_duplicate(tmp_path):
    output = {
        "candidates": [
            _suggestion(
                "elastic weight consolidation",
                "concept",
                "Elastic weight consolidation limits catastrophic forgetting.",
                "core_gap",
                "This method connects to the current learning focus.",
            )
        ]
    }
    connection, service, candidate_service, _pdf_service, _gateway = _service(
        tmp_path, output
    )
    service.update_settings(TermDiscoverySettings(enabled_lanes=["concept"]))
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()
    _write_document(
        tmp_path,
        "note-one",
        "Continual Learning Notes",
        "Elastic weight consolidation limits catastrophic forgetting. "
        "It uses parameter importance to protect prior tasks.",
    )
    manual = candidate_service.create_candidate(
        "elastic weight consolidation",
        "concept",
        [
            TermCandidateEvidenceInput(
                origin_type="document",
                origin_id="note-one",
                mention="elastic weight consolidation",
                context_excerpt="Elastic weight consolidation limits catastrophic forgetting.",
            )
        ],
    )

    run = service.run()

    assert run.candidate_count == 0
    assert [item.id for item in candidate_service.list_candidates("pending")] == [
        manual.id
    ]
    assert len(candidate_service.get_candidate(manual.id).evidence) == 1
    connection.close()


def test_vocabulary_counts_are_per_source_and_replace_changed_source_rows():
    connection = connect_database(":memory:")
    repository = TermDiscoveryRepository(connection)
    first_counts = mine_vocabulary("latent latent state-of-the-art model model")
    second_counts = mine_vocabulary("latent state-of-the-art empirical result")

    assert repository.replace_vocabulary_source_statistics(
        "source-one", "hash-one", first_counts, "2026-10-07T00:00:00+00:00"
    )
    assert repository.replace_vocabulary_source_statistics(
        "source-two", "hash-two", second_counts, "2026-10-07T00:00:00+00:00"
    )
    assert not repository.replace_vocabulary_source_statistics(
        "source-one", "hash-one", {}, "2026-10-07T00:00:00+00:00"
    )
    latent = next(
        item for item in repository.vocabulary_candidates(50)
        if item["normalized_term"] == "latent"
    )
    assert latent["document_frequency"] == 2
    assert latent["total_count"] == 3

    changed = mine_vocabulary("new specialized vocabulary repeated repeated")
    repository.replace_vocabulary_source_statistics(
        "source-one", "hash-changed", changed, "2026-10-08T00:00:00+00:00"
    )
    assert all(
        item["normalized_term"] != "latent"
        for item in repository.vocabulary_candidates(50)
    )
    connection.close()


def test_knowledge_state_keeps_activity_exposure_and_knowledge_distinct(tmp_path):
    connection = connect_database(":memory:")
    terms = tmp_path / "knowledge" / "terms"
    terms.mkdir(parents=True)
    _write_term(terms / "stub-term.md", "stub-term", "Stub Term", "stub")
    _write_term(terms / "standard-term.md", "standard-term", "Standard Term", "standard")
    _write_term(terms / "deep-term.md", "deep-term", "Deep Term", "deep")
    document = tmp_path / "knowledge" / "documents" / "learning" / "note-one.md"
    document.parent.mkdir(parents=True)
    document.write_text(
        "---\nschema_version: 1\nid: note-one\ntitle: Note One\n"
        "type: learning-note\n---\n# Note One\n",
        encoding="utf-8",
    )
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    connection.execute(
        """INSERT INTO term_entity_relations (
               id, entity_type, entity_id, term_id, created_from_candidate_id, created_at
           ) VALUES ('relation-1', 'document', 'note-one', 'stub-term', NULL, ?)""",
        ((now - timedelta(days=40)).isoformat(),),
    )
    connection.execute(
        """INSERT INTO usage_events (id, entity_type, entity_id, event_type, created_at)
           VALUES ('open-1', 'document', 'note-one', 'document_open', ?)""",
        ((now - timedelta(days=1)).isoformat(),),
    )
    connection.execute(
        """INSERT INTO pdf_corpus (
               source_id, pdf_hash, extractor_version, text_hash, text,
               status, extracted_at, error_message, updated_at
           ) VALUES ('source-one', 'pdf-hash', 'pypdf-text-v1', 'text-hash',
                    'Stub Term appears in this research paper.', 'ready', ?, NULL, ?)""",
        (now.isoformat(), now.isoformat()),
    )
    connection.commit()

    snapshot = KnowledgeStateService(
        tmp_path, connection, clock=lambda: now
    ).build_snapshot(["continual learning"])

    assert snapshot["term_states"]["stub-term"] == "exposed"
    assert snapshot["term_states"]["standard-term"] == "unknown"
    assert snapshot["term_states"]["deep-term"] == "unknown"
    assert snapshot["activity"]["recently_used_terms"][0]["id"] == "stub-term"
    assert snapshot["exposure"]["terms"][0]["id"] == "stub-term"
    assert "stub-term" not in {item["id"] for item in snapshot["knowledge"]["established"]}
    stub = terms / "stub-term.md"
    stub.write_text(stub.read_text(encoding="utf-8").replace("---\n#", "review: {human: {status: approved}}\n---\n#") + "\nA short reviewed definition.\n", encoding="utf-8")
    approved = KnowledgeStateService(tmp_path, connection, clock=lambda: now).build_snapshot([])
    assert approved["term_states"]["stub-term"] == "established"
    assert next(item for item in approved["registry"] if item["id"] == "stub-term")["content_excerpt"] == "A short reviewed definition."
    connection.close()


def test_recent_note_focus_does_not_change_term_mastery(tmp_path):
    connection = connect_database(":memory:")
    terms = tmp_path / "knowledge" / "terms"
    documents = tmp_path / "knowledge" / "documents" / "learning"
    terms.mkdir(parents=True)
    documents.mkdir(parents=True)
    _write_term(terms / "stub-term.md", "stub-term", "Stub Term", "stub")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    note = documents / "note-one.md"
    note.write_text(
        "---\nschema_version: 1\nid: note-one\ntitle: Continual Learning Notes\n"
        "type: learning-note\ndomains: [machine-learning]\n"
        "topics: [continual-learning]\n---\n# Notes\n[[Stub Term]]\n",
        encoding="utf-8",
    )
    note_time = now.timestamp()
    os.utime(note, (note_time, note_time))
    connection.execute(
        """INSERT INTO usage_events (id, entity_type, entity_id, event_type, created_at)
           VALUES ('open-note', 'document', 'note-one', 'document_open', ?)""",
        ((now - timedelta(days=1)).isoformat(),),
    )
    connection.commit()

    snapshot = KnowledgeStateService(
        tmp_path, connection, clock=lambda: now
    ).build_snapshot(["continual learning"])

    assert snapshot["focus"]["explicit"] == ["continual learning"]
    assert snapshot["focus"]["recent_topics"] == ["continual-learning"]
    assert snapshot["focus"]["recent_domains"] == ["machine-learning"]
    assert snapshot["focus"]["recent_terms"] == [
        {"id": "stub-term", "title": "Stub Term", "type": "concept"}
    ]
    assert snapshot["term_states"]["stub-term"] == "unknown"
    assert snapshot["activity"]["recently_used_terms"] == []
    connection.close()


def test_selected_learning_context_guides_terms_without_unselected_course_pollution(tmp_path):
    selected_note_text = (
        "Learning without Forgetting uses distillation to preserve prior-task behavior. "
        "Elastic Weight Consolidation protects important parameters. "
        "iCaRL combines exemplar replay with representation learning. "
        "Gradient Episodic Memory constrains updates using past-task gradients. "
        "Synaptic Intelligence estimates parameter importance over time. "
        "RLHF uses feedback from human preferences.\n"
    )
    selected_notes = {
        "lwf": "Learning without Forgetting",
        "ewc": "Elastic Weight Consolidation",
        "icarl": "iCaRL",
        "gem": "Gradient Episodic Memory",
    }
    for document_id, title in selected_notes.items():
        _write_document(
            tmp_path,
            document_id,
            title,
            selected_note_text,
            domains=["machine-learning"],
            topics=["continual-learning"],
        )

    course_path = tmp_path / "knowledge" / "documents" / "courses" / "ethernet-course.md"
    course_path.parent.mkdir(parents=True, exist_ok=True)
    course_path.write_text(
        "---\nschema_version: 1\nid: ethernet-course\n"
        "title: Ethernet in Physical Networks\ntype: course-note\n"
        "domains: [computer-networking]\ntopics: [ethernet]\n---\n"
        "# Ethernet\nEthernet frames connect devices in a local network.\n",
        encoding="utf-8",
    )
    os.utime(course_path, (_clock().timestamp(), _clock().timestamp()))

    context_service = LearningContextService(tmp_path)
    context_service.set_sources(list(selected_notes))
    context_service.sync_if_stale = lambda: {
        "state": "synced",
        "stale": False,
        "used_previous_context": False,
        "message": "学习上下文已是最新。",
    }
    context_service.set_preferences(
        {
            "fixed_direction": "Continual learning",
            "keywords": ["continual learning"],
            "exclude_keywords": ["RLHF", "Ethernet"],
            "exploration_directions": ["reinforcement learning basics"],
            "important_anchors": ["Gradient Episodic Memory"],
        }
    )
    context_service._write_yaml(
        "index.yaml",
        {
            "topics": [
                {
                    "id": "continual-learning",
                    "title": "Continual Learning",
                    "aliases": ["EWC", "LwF", "iCaRL", "GEM"],
                    "keywords": ["continual learning", "catastrophic forgetting"],
                }
            ]
        },
    )
    source_summaries = {
        "lwf": "### Learning without Forgetting (LwF)\n"
        "LwF uses distillation to preserve prior-task behavior.",
        "ewc": "### Elastic Weight Consolidation (EWC)\n"
        "EWC protects important parameters to reduce forgetting.",
        "icarl": "### iCaRL\n"
        "iCaRL combines exemplar replay with representation learning.",
        "gem": "### Gradient Episodic Memory (GEM)\n"
        "GEM constrains updates using past-task gradients.",
    }
    context_service._atomic_write(
        "topics/continual-learning.md",
        render_entry(
            {
                "entry_id": "covered-methods",
                "owner": "auto",
                "title": "Covered methods",
                "source_headings": {
                    document_id: ["Method"] for document_id in selected_notes
                },
                "source_summaries": source_summaries,
                "summary": "\n\n".join(source_summaries.values()),
            }
        ),
    )

    output = {
        "candidates": [
            _suggestion(
                "Learning without Forgetting",
                "concept",
                "Learning without Forgetting uses distillation to preserve prior-task behavior.",
                "core_gap",
                "This method is covered by a selected learning note.",
            ),
            _suggestion(
                "Elastic Weight Consolidation",
                "concept",
                "Elastic Weight Consolidation protects important parameters.",
                "core_gap",
                "This method is covered by a selected learning note.",
            ),
            _suggestion(
                "iCaRL",
                "concept",
                "iCaRL combines exemplar replay with representation learning.",
                "core_gap",
                "This method is covered by a selected learning note.",
            ),
            _suggestion(
                "Gradient Episodic Memory",
                "concept",
                "Gradient Episodic Memory constrains updates using past-task gradients.",
                "core_gap",
                "This method is covered by a selected learning note.",
            ),
            _suggestion(
                "Synaptic Intelligence",
                "concept",
                "Synaptic Intelligence estimates parameter importance over time.",
                "next",
                "It directly extends the selected continual learning methods.",
            ),
            _suggestion(
                "RLHF",
                "concept",
                "RLHF uses feedback from human preferences.",
                "core_gap",
                "It is outside the fixed learning direction and is excluded.",
            ),
            _suggestion(
                "Ethernet",
                "concept",
                "Ethernet connects devices in a local network.",
                "core_gap",
                "It appears only in an unselected course note.",
            ),
        ]
    }
    corpus_text = (
        "Learning without Forgetting uses distillation to preserve prior-task behavior. "
        "Elastic Weight Consolidation protects important parameters. "
        "iCaRL combines exemplar replay with representation learning. "
        "Gradient Episodic Memory constrains updates using past-task gradients. "
        "Synaptic Intelligence estimates parameter importance over time. "
        "RLHF uses feedback from human preferences. "
        "Ethernet connects devices in a local network.\n"
    ) * 3
    connection, service, candidate_service, _pdf_service, gateway = _service(
        tmp_path,
        output,
        corpus_text=corpus_text,
        learning_context_service=context_service,
    )
    service.update_settings(
        TermDiscoverySettings(enabled_lanes=["concept"], focus_override="continual learning")
    )

    run = service.run()

    source_call = next(
        context
        for task, context in gateway.calls
        if task == "discover_terms" and context["source"]["id"] in selected_notes
    )
    assert run.status == "success"
    assert "ethernet" in [item.casefold() for item in run.snapshot["focus"]["recent_topics"]]
    assert "ethernet" not in " ".join(source_call["focus"]).casefold()
    assert source_call["learning_context"]["current_focus"] == run.snapshot["effective_focus"]
    assert {
        item["id"] for item in source_call["learning_context"]["included_sources"]
    } == set(selected_notes)
    assert "ethernet-course" not in {
        item["id"] for item in source_call["learning_context"]["included_sources"]
    }
    assert source_call["learning_context"]["topics"][0]["id"] == "continual-learning"
    assert {
        "Learning without Forgetting (LwF)",
        "Elastic Weight Consolidation (EWC)",
        "iCaRL",
        "Gradient Episodic Memory (GEM)",
    } <= set(source_call["learning_context"]["covered_term_headings"])
    assert source_call["learning_context"]["preferences"]["fixed_direction"] == "Continual learning"
    document_context_ids = {
        context["source"]["id"]
        for task, context in gateway.calls
        if task == "discover_terms"
        and context["source"]["id"]
        in {*selected_notes, "ethernet-course"}
    }
    assert document_context_ids <= set(selected_notes)
    assert "ethernet-course" not in document_context_ids
    assert "source-alpha" not in {
        context["source"]["id"]
        for task, context in gateway.calls
        if task == "discover_terms"
    }
    assert [item.display_name for item in candidate_service.list_candidates("pending")] == [
        "Synaptic Intelligence"
    ]
    connection.close()


def test_personalized_terms_require_selected_notes_and_general_scope_is_explicit(tmp_path):
    course_path = tmp_path / "knowledge" / "documents" / "courses" / "ethernet-course.md"
    course_path.parent.mkdir(parents=True, exist_ok=True)
    course_path.write_text(
        "---\nschema_version: 1\nid: ethernet-course\n"
        "title: Ethernet in Physical Networks\ntype: course-note\n"
        "domains: [computer-networking]\ntopics: [ethernet]\n---\n"
        "# Ethernet\nEthernet frames connect devices in a local network.\n",
        encoding="utf-8",
    )
    context_service = LearningContextService(tmp_path)
    context_service.set_sources([])
    context_service.sync_if_stale = lambda: {
        "state": "synced",
        "stale": False,
        "used_previous_context": False,
        "message": "学习上下文已是最新。",
    }
    connection, service, _candidates, pdf_service, gateway = _service(
        tmp_path,
        learning_context_service=context_service,
    )
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["concept"],
            focus_override="continual learning Ethernet",
        )
    )

    personalized = service.run(discovery_mode="personalized")

    assert personalized.status == "success"
    assert personalized.snapshot["discovery_mode"] == "personalized"
    assert gateway.calls == []
    assert pdf_service.calls == []

    general = service.run(discovery_mode="general")
    general_document_ids = {
        context["source"]["id"]
        for task, context in gateway.calls
        if task == "discover_terms"
    }
    assert general.snapshot["discovery_mode"] == "general"
    assert "ethernet-course" in general_document_ids
    assert "source-alpha" in general_document_ids
    connection.close()


def test_personalized_terms_analyzes_only_the_selected_gem_note(tmp_path):
    for document_id, title in {
        "gem": "Gradient Episodic Memory",
        "ewc": "Elastic Weight Consolidation",
    }.items():
        _write_document(
            tmp_path,
            document_id,
            title,
            "{} constrains continual learning updates.".format(title),
            domains=["machine-learning"],
            topics=["continual-learning"],
        )
    context_service = LearningContextService(tmp_path)
    context_service.set_sources(["gem"])
    context_service.sync_if_stale = lambda: {
        "state": "synced",
        "stale": False,
        "used_previous_context": False,
        "message": "学习上下文已是最新。",
    }
    connection, service, _candidates, pdf_service, gateway = _service(
        tmp_path,
        output={"candidates": []},
        learning_context_service=context_service,
    )
    service.update_settings(
        TermDiscoverySettings(enabled_lanes=["concept"], focus_override="continual learning")
    )

    run = service.run(discovery_mode="personalized")

    analyzed_source_ids = [
        context["source"]["id"]
        for task, context in gateway.calls
        if task == "discover_terms"
    ]
    assert run.status == "success"
    assert analyzed_source_ids == ["gem"]
    assert pdf_service.calls == []
    connection.close()


@pytest.mark.parametrize("trigger", ["manual", "scheduled"])
def test_terms_run_marks_fallback_when_context_sync_fails(tmp_path, trigger):
    context_service = LearningContextService(tmp_path)
    context_service.sync_if_stale = lambda: {
        "state": "failed",
        "stale": True,
        "used_previous_context": True,
        "message": "学习上下文同步未完成；本次使用上次保存的学习上下文。AI 分析失败。",
    }
    connection, service, _candidate_service, _pdf_service, _gateway = _service(
        tmp_path,
        output={"candidates": []},
        learning_context_service=context_service,
    )
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["concept"], focus_override="continual learning"
        )
    )

    run = service.run(trigger)

    assert run.status == "partial"
    assert run.snapshot["learning_context"]["sync_status"]["used_previous_context"] is True
    assert "使用上次保存的学习上下文" in run.error_summary
    connection.close()


def test_learning_context_coverage_requires_a_specific_source_supported_entry(tmp_path):
    context = {
        "active": render_entry(
            {
                "entry_id": "ewc-mechanism",
                "owner": "auto",
                "source_headings": {"gem-note": ["Mechanism"]},
                "source_summaries": {
                    "gem-note": "EWC protects parameters that matter to earlier tasks."
                },
                "layer": "topic",
                "topic_id": "continual-learning",
                "topic_title": "Continual Learning",
                "title": "Elastic Weight Consolidation (EWC)",
                "summary": "EWC protects parameters that matter to earlier tasks.",
            }
        ),
        "important": "",
        "topics": [],
        "selected_source_ids": ["gem-note"],
    }
    context["covered_term_headings"] = _learning_context_headings(context)
    term_path = tmp_path / "knowledge" / "terms" / "elastic-weight-consolidation.md"
    term_path.parent.mkdir(parents=True)
    term_path.write_text(
        "---\nschema_version: 1\nid: elastic-weight-consolidation\n"
        "title: 弹性权重巩固\ntype: concept\ndepth: standard\n"
        "aliases: [Elastic Weight Consolidation, EWC]\n"
        "domains: []\ntopics: []\ntags: []\nsources: []\n---\n"
        "# 弹性权重巩固\n",
        encoding="utf-8",
    )
    resolver = TermResolver(TermRegistry.load(term_path.parent))

    assert _covered_by_learning_context(
        "Elastic Weight Consolidation", context, resolver
    )
    assert _covered_by_learning_context("EWC", context, resolver)
    assert _covered_by_learning_context("弹性权重巩固", context, resolver)
    assert not _covered_by_learning_context("Continual Learning", context)
    assert not _covered_by_learning_context("Replay", context)
    direction_only = {
        **context,
        "user_direction": "希望下一步学习 Synaptic Intelligence (SI)。",
    }
    assert not _covered_by_learning_context("SI", direction_only)
    mentioned_only = {
        **context,
        "active": "# Current focus\n\n## Next steps\n\n"
        "Synaptic Intelligence (SI) is mentioned as a method to learn next.",
    }
    mentioned_only["covered_term_headings"] = _learning_context_headings(
        mentioned_only
    )
    assert not _covered_by_learning_context("SI", mentioned_only)
    unstructured_mention = {
        "active": "# Current focus\n\n## Notes\n\n"
        "Elastic Weight Consolidation (EWC) appears in this paragraph.",
        "important": "",
        "topics": [],
        "selected_source_ids": ["gem-note"],
    }
    unstructured_mention["covered_term_headings"] = _learning_context_headings(
        unstructured_mention
    )
    assert not _covered_by_learning_context("EWC", unstructured_mention)


def test_term_discovery_api_exposes_settings_and_run_history(tmp_path):
    @asynccontextmanager
    async def lifespan(app):
        connection = connect_database(tmp_path / "runtime.db")
        app.state.term_discovery_service = _service(
            tmp_path, connection=connection
        )[1]
        try:
            yield
        finally:
            connection.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(terms_router)

    with TestClient(app) as client:
        initial = client.get("/api/terms/discovery")
        assert initial.status_code == 200
        assert initial.json()["global_capacity"] == 12

        settings = client.put(
            "/api/terms/discovery/settings",
            json={
                "enabled_lanes": ["entity"],
                "daily_max_new": 3,
                "lane_capacities": {"concept": 5, "entity": 4, "vocabulary": 6},
                "source_preferences": ["source-alpha"],
                "focus_override": "model evaluation",
            },
        )
        assert settings.status_code == 200, settings.json()
        assert settings.json()["settings"]["enabled_lanes"] == ["entity"]

        run = client.post("/api/terms/discovery/run?trigger=manual")
        assert run.status_code == 200, run.json()
        assert run.json()["status"] == "success"
        assert run.json()["snapshot"]["discovery_mode"] == "personalized"
        general = client.post(
            "/api/terms/discovery/run?trigger=manual&discovery_mode=general"
        )
        assert general.status_code == 200, general.json()
        assert general.json()["snapshot"]["discovery_mode"] == "general"
        history = client.get("/api/terms/discovery/runs")
        assert history.status_code == 200
        histories_by_id = {item["id"]: item for item in history.json()}
        assert histories_by_id[run.json()["id"]]["snapshot"]["discovery_mode"] == "personalized"
        assert histories_by_id[general.json()["id"]]["snapshot"]["discovery_mode"] == "general"


def test_semantic_existing_suggestion_is_allowed_when_literal_is_unresolved(tmp_path):
    output = {
        "candidates": [
            {
                **_suggestion(
                    "performance on previously learned classes",
                    "concept",
                    "Performance on previously learned classes drops sharply.",
                    "core_gap",
                    "This phrase describes the current learning focus.",
                ),
                "existing_term_id": "catastrophic-forgetting",
            }
        ]
    }
    connection, service, candidate_service, _pdf_service, _gateway = _service(
        tmp_path,
        output,
        corpus_text=(
            "Performance on previously learned classes drops sharply. "
            "This pattern indicates that an old model has lost prior capability. "
            "Continual learning systems measure retention after learning new tasks. "
        ) * 2,
    )
    _write_term(
        tmp_path / "knowledge" / "terms" / "catastrophic-forgetting.md",
        "catastrophic-forgetting",
        "Catastrophic Forgetting",
        "standard",
    )

    run = service.run()

    assert run.candidate_count == 1, run.model_dump()
    candidate = candidate_service.list_candidates("pending")[0]
    assert candidate.display_name == "performance on previously learned classes"
    assert candidate.suggested_term_id == "catastrophic-forgetting"
    connection.close()


def test_semantic_existing_suggestion_rejects_deterministic_conflict(tmp_path):
    output = {
        "candidates": [
            {
                **_suggestion(
                    "elastic weight consolidation",
                    "concept",
                    "Elastic weight consolidation limits catastrophic forgetting.",
                    "core_gap",
                    "This term is related to the current learning focus.",
                ),
                "existing_term_id": "catastrophic-forgetting",
            }
        ]
    }
    connection, service, candidate_service, _pdf_service, _gateway = _service(
        tmp_path, output
    )
    terms = tmp_path / "knowledge" / "terms"
    _write_term(terms / "elastic-weight-consolidation.md", "elastic-weight-consolidation", "Elastic Weight Consolidation", "standard")
    _write_term(terms / "catastrophic-forgetting.md", "catastrophic-forgetting", "Catastrophic Forgetting", "standard")

    run = service.run()

    assert run.candidate_count == 0
    assert run.filtered_counts["concept"] == 1
    assert candidate_service.list_candidates("pending") == []
    connection.close()


def _service(
    tmp_path,
    output=None,
    connection=None,
    corpus_text=None,
    external_discovery=None,
    learning_context_service=None,
):
    connection = connection or connect_database(":memory:")
    terms = tmp_path / "knowledge" / "terms"
    sources = tmp_path / "knowledge" / "sources"
    papers = tmp_path / "storage" / "papers"
    terms.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)
    papers.mkdir(parents=True, exist_ok=True)
    (sources / "source-alpha.yaml").write_text(
        "schema_version: 1\nid: source-alpha\ntype: paper\ntitle: Continual Learning\n"
        "attachments:\n  local_pdf: storage://papers/source-alpha.pdf\n",
        encoding="utf-8",
    )
    (papers / "source-alpha.pdf").write_bytes(b"not a real PDF; extractor is injected")
    text = corpus_text or (
        "Elastic weight consolidation limits catastrophic forgetting.\n\n"
        "An advanced consolidation variant builds on elastic weight consolidation. "
        "This paper discusses continual learning and useful research methods. "
    ) * 3
    pdf_calls = []

    def extract(_payload):
        pdf_calls.append("source-alpha")
        return text

    candidate_repository = TermCandidateRepository(connection)
    candidate_service = TermCandidateService(tmp_path, candidate_repository)
    pdf_service = PdfCorpusService(
        tmp_path,
        PdfCorpusRepository(connection),
        extractor=extract,
        clock=_clock,
    )

    class FakeGateway:
        def __init__(self):
            self.calls = []

        def run(self, task, context):
            self.calls.append((task, context))
            return TermDiscoveryOutput.model_validate(output or {"candidates": []})

    gateway = FakeGateway()
    repository = TermDiscoveryRepository(connection)
    service = TermDiscoveryService(
        tmp_path,
        repository,
        pdf_service,
        candidate_service,
        gateway,
        clock=_clock,
        external_discovery=external_discovery,
        learning_context_service=learning_context_service,
    )
    pdf_service.calls = pdf_calls
    gateway.calls_by_task = lambda task: [call for call in gateway.calls if call[0] == task]
    return connection, service, candidate_service, pdf_service, gateway


class _FakeExternalDiscovery:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, query, limit):
        self.calls.append((query, limit))
        return self.results


def _suggestion(mention, term_type, excerpt, level, why_now):
    return {
        "mention": mention,
        "term_type": term_type,
        "confidence": 0.9,
        "rationale": "This is reusable research knowledge.",
        "context_excerpt": excerpt,
        "readiness": "medium" if level == "stretch" else "high",
        "recommendation_level": level,
        "known_prerequisites": ["Fisher information"],
        "missing_prerequisites": ["Online updating"] if level == "stretch" else [],
        "why_now": why_now,
    }


def _write_term(path, term_id, title, depth):
    path.write_text(
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: concept\ndepth: {}\n"
        "aliases: []\ndomains: []\ntopics: []\ntags: []\nsources: []\n---\n# {}\n".format(
            term_id, title, depth, title
        ),
        encoding="utf-8",
    )


def _write_document(root, document_id, title, body, domains=None, topics=None):
    import yaml

    directory = root / "knowledge" / "documents" / "learning"
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema_version": 1,
        "id": document_id,
        "title": title,
        "type": "learning-note",
        "domains": domains or [],
        "topics": topics or [],
    }
    content = "---\n{}---\n\n{}\n".format(
        yaml.safe_dump(metadata, sort_keys=False), body
    )
    (directory / "{}.md".format(document_id)).write_text(
        content, encoding="utf-8"
    )


def _clock():
    return datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
