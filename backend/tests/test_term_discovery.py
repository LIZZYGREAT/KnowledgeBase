from datetime import datetime, timedelta, timezone
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.terms import router as terms_router
from backend.app.db.connection import connect_database, initialize_database
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
    TermDiscoveryService,
    _allocate_lane_budgets,
    _dynamic_allowance,
)
from backend.app.services.vocabulary_mining import mine_vocabulary


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


def test_scheduled_check_is_idle_without_a_local_pdf(tmp_path):
    connection, service, _candidate_service, _pdf_service, gateway = _service(tmp_path)
    (tmp_path / "storage" / "papers" / "source-alpha.pdf").unlink()

    run = service.scheduled_check()

    assert run is None
    assert service.list_runs() == []
    assert gateway.calls == []
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
    _write_term(terms / "deep-term.md", "deep-term", "Deep Term", "deep")
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
    assert snapshot["term_states"]["deep-term"] == "established"
    assert snapshot["activity"]["recently_used_terms"][0]["id"] == "stub-term"
    assert snapshot["exposure"]["terms"][0]["id"] == "stub-term"
    assert "stub-term" not in {item["id"] for item in snapshot["knowledge"]["established"]}
    connection.close()


def test_term_discovery_api_exposes_settings_and_run_history(tmp_path):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    connection, service, _candidate_service, _pdf_service, _gateway = _service(
        tmp_path, connection=connection
    )
    app = FastAPI()
    app.include_router(terms_router)
    app.state.term_discovery_service = service

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
    connection.close()


def _service(tmp_path, output=None, connection=None):
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
    text = (
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
    )
    pdf_service.calls = pdf_calls
    gateway.calls_by_task = lambda task: [call for call in gateway.calls if call[0] == task]
    return connection, service, candidate_service, pdf_service, gateway


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


def _clock():
    return datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
