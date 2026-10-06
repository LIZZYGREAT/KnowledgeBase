import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.terms import router as terms_router
from backend.app.db.connection import connect_database, initialize_database
from backend.app.db.migrations import migrate_database
from backend.app.domain.ai import DraftTermOutput
from backend.app.domain.term import TermMetadata
from backend.app.domain.term_runtime import TermCandidateEvidenceInput
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.services.term_candidate_service import (
    TermCandidateConflict,
    TermCandidateService,
)


def test_runtime_schema_12_migrates_to_term_core_13():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA user_version = 12")

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 13
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "term_candidates",
        "term_candidate_evidence",
        "term_entity_relations",
        "term_merge_history",
    } <= tables
    connection.close()


def test_term_entity_type_is_canonical_and_available_to_term_drafts():
    metadata = {
        "schema_version": 1,
        "id": "pytorch",
        "title": "PyTorch",
        "type": "entity",
        "depth": "stub",
    }

    assert TermMetadata.model_validate(metadata).type == "entity"
    assert DraftTermOutput.model_validate(
        {
            "id": metadata["id"],
            "title": metadata["title"],
            "type": "entity",
            "depth": "stub",
            "definition": "A machine learning framework.",
        }
    ).type == "entity"
    with pytest.raises(ValueError):
        TermMetadata.model_validate({**metadata, "type": "framework"})


def test_candidate_resolution_evidence_dedup_and_existing_acceptance(tmp_path):
    _write_term(tmp_path)
    connection = connect_database(":memory:")
    try:
        repository = TermCandidateRepository(connection)
        service = TermCandidateService(tmp_path, repository)
        evidence = TermCandidateEvidenceInput(
            origin_type="document",
            origin_id="note-one",
            mention="Calibrated Optimizer",
            context_excerpt="A paragraph that names it.",
            confidence=0.9,
        )
        second_mention = TermCandidateEvidenceInput(
            origin_type="document",
            origin_id="note-one",
            mention="calibration",
        )

        candidate = service.create_candidate(
            "Calibrated Optimizer", "entity", [evidence, second_mention]
        )
        duplicate = service.create_candidate(
            "  CALIBRATED   OPTIMIZER ", "entity", [evidence, second_mention]
        )

        assert duplicate.id == candidate.id
        assert candidate.normalized_name == "calibrated optimizer"
        assert candidate.suggested_term_id == "neural-indexing"
        assert len(service.get_candidate(candidate.id).evidence) == 2
        resolution = service.resolve_against_registry(candidate)
        assert resolution.status == "existing_term"
        assert resolution.term_id == "neural-indexing"

        accepted = service.accept_existing(candidate.id, "neural-indexing")
        assert accepted.status == "accepted"
        assert accepted.accepted_term_id == "neural-indexing"
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT entity_type, entity_id, term_id FROM term_entity_relations"
            ).fetchall()
        ] == [("document", "note-one", "neural-indexing")]
    finally:
        connection.close()


def test_local_reject_memory_is_origin_scoped_and_global_reject_blocks_new_candidates(
    tmp_path,
):
    _write_term(tmp_path)
    connection = connect_database(":memory:")
    try:
        repository = TermCandidateRepository(connection)
        service = TermCandidateService(tmp_path, repository)
        candidate = service.create_candidate(
            "Latent Space",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type="document", origin_id="note-one", mention="latent space"
                ),
                TermCandidateEvidenceInput(
                    origin_type="source", origin_id="paper-one", mention="latent space"
                ),
            ],
        )

        rejected = service.reject_candidate(candidate.id, "local", "Not useful here")
        assert rejected.status == "rejected"
        assert repository.is_rejected("latent space", "origin:document:note-one")
        assert repository.is_rejected("latent space", "origin:source:paper-one")
        assert not repository.is_rejected("latent space", "origin:document:note-two")
        assert not repository.is_rejected("latent space", "global")

        global_candidate = service.create_candidate(
            "Global Reject",
            "vocabulary",
            [
                TermCandidateEvidenceInput(
                    origin_type="external", origin_id="ref:42", mention="global reject"
                )
            ],
        )
        service.reject_candidate(global_candidate.id, "global")
        with pytest.raises(TermCandidateConflict, match="rejected globally"):
            service.create_candidate(
                "Global Reject",
                "vocabulary",
                [
                    TermCandidateEvidenceInput(
                        origin_type="document", origin_id="note-two", mention="Global Reject"
                    )
                ],
            )
    finally:
        connection.close()


def test_candidate_unique_open_name_and_evidence_constraints():
    connection = connect_database(":memory:")
    try:
        first = _candidate("candidate-one", "latent space", "pending")
        second = _candidate("candidate-two", "latent space", "drafting")
        with connection:
            connection.execute(
                """INSERT INTO term_candidates (
                       id, normalized_name, display_name, suggested_type, status,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    first.id,
                    first.normalized_name,
                    first.display_name,
                    first.suggested_type,
                    first.status,
                    first.created_at,
                    first.updated_at,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO term_candidates (
                       id, normalized_name, display_name, suggested_type, status,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    second.id,
                    second.normalized_name,
                    second.display_name,
                    second.suggested_type,
                    second.status,
                    second.created_at,
                    second.updated_at,
                ),
            )
        connection.rollback()

        with connection:
            connection.execute(
                "UPDATE term_candidates SET status = 'accepted' WHERE id = ?",
                (first.id,),
            )
            connection.execute(
                """INSERT INTO term_candidates (
                       id, normalized_name, display_name, suggested_type, status,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    second.id,
                    second.normalized_name,
                    second.display_name,
                    second.suggested_type,
                    second.status,
                    second.created_at,
                    second.updated_at,
                ),
            )
    finally:
        connection.close()


def test_term_candidate_api_routes_bind_to_candidate_service(tmp_path):
    _write_term(tmp_path)
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    service = TermCandidateService(tmp_path, TermCandidateRepository(connection))
    candidate = service.create_candidate(
        "Calibrated Optimizer",
        "entity",
        [
            TermCandidateEvidenceInput(
                origin_type="document",
                origin_id="note-one",
                mention="Calibrated Optimizer",
            )
        ],
    )
    app = FastAPI()
    app.include_router(terms_router)
    app.state.term_candidate_service = service

    try:
        with TestClient(app) as client:
            listed = client.get("/api/terms/candidates")
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == candidate.id
            detail = client.get("/api/terms/candidates/{}".format(candidate.id))
            assert detail.status_code == 200
            assert detail.json()["evidence"][0]["mention"] == "Calibrated Optimizer"
            accepted = client.post(
                "/api/terms/candidates/{}/accept-existing".format(candidate.id),
                json={"term_id": "neural-indexing"},
            )
            assert accepted.status_code == 200, accepted.json()
            assert accepted.json()["accepted_term_id"] == "neural-indexing"
    finally:
        connection.close()


def _write_term(repository_root):
    terms = repository_root / "knowledge" / "terms"
    terms.mkdir(parents=True, exist_ok=True)
    (terms / "neural-indexing.md").write_text(
        "---\nschema_version: 1\nid: neural-indexing\ntitle: Neural Indexing\n"
        "type: concept\ndepth: standard\naliases:\n  - Calibrated Optimizer\n"
        "domains: []\ntopics: []\ntags: []\nsources: []\n---\n# Neural Indexing\n",
        encoding="utf-8",
    )


def _candidate(candidate_id, normalized_name, status):
    from backend.app.domain.term_runtime import TermCandidateRecord

    return TermCandidateRecord(
        id=candidate_id,
        normalized_name=normalized_name,
        display_name=normalized_name,
        suggested_type="concept",
        status=status,
        created_at="now",
        updated_at="now",
    )
