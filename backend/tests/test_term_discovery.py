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
from backend.app.services.pdf_corpus_service import PdfCorpusService
from backend.app.services.term_candidate_service import TermCandidateService
from backend.app.services.term_discovery_service import (
    DiscoveryCorpus,
    TermDiscoveryService,
    _allocate_lane_budgets,
    _dynamic_allowance,
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
    assert run.snapshot == {}
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


def test_scheduled_check_runs_once_per_utc_day(tmp_path):
    connection, service, _candidate_service, _pdf_service, gateway = _service(
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
    )
    now = datetime(2026, 10, 7, 10, tzinfo=timezone.utc)
    service.clock = lambda: now
    service.update_settings(TermDiscoverySettings(enabled_lanes=["concept"]))

    first = service.scheduled_check()
    second = service.scheduled_check()

    assert first is not None
    assert first.trigger == "scheduled"
    assert first.status == "success"
    assert second is None
    assert [call[0] for call in gateway.calls] == ["discover_terms"]
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


def test_scheduled_external_discovery_can_run_without_local_corpus(tmp_path):
    external = _FakeExternalDiscovery([])
    connection, service, _candidate_service, _pdf_service, _gateway = _service(
        tmp_path, external_discovery=external
    )
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()
    service.update_settings(
        TermDiscoverySettings(
            enabled_lanes=["entity"],
            focus_override="continual learning systems",
            external_enabled=True,
        )
    )

    run = service.scheduled_check()

    assert run is not None
    assert run.trigger == "scheduled"
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

    assert snapshot["term_states"]["stub-term"] == "learning"
    assert snapshot["term_states"]["standard-term"] == "established"
    assert snapshot["term_states"]["deep-term"] == "established"
    assert snapshot["activity"]["recently_used_terms"][0]["id"] == "stub-term"
    assert snapshot["exposure"]["terms"][0]["id"] == "stub-term"
    assert "stub-term" not in {item["id"] for item in snapshot["knowledge"]["established"]}
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
        history = client.get("/api/terms/discovery/runs")
        assert history.status_code == 200
        assert history.json()[0]["id"] == run.json()["id"]


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
    tmp_path, output=None, connection=None, corpus_text=None, external_discovery=None
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
