import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.ai import router as ai_router
from backend.app.api.terms import router as terms_router
from backend.app.api.knowledge import router as knowledge_router
from backend.app.db.connection import connect_database, initialize_database
from backend.app.db.migrations import migrate_database
from backend.app.domain.ai import DraftTermOutput
from backend.app.domain.runtime import Draft, Proposal
from backend.app.domain.term import TermMetadata
from backend.app.domain.term_runtime import TermCandidateEvidenceInput
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.draft_service import DraftService
from backend.app.services.term_candidate_service import (
    TermCandidateConflict,
    TermCandidateService,
)
from backend.app.services.term_merge_service import (
    TermMergePreview,
    TermMergeResult,
    TermMergeSelectedTerm,
)


def test_runtime_schema_12_migrates_to_term_core_and_analysis_state_14():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA user_version = 12")

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 14
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
        "document_term_analysis_state",
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
    _write_document(tmp_path, "note-one")
    connection = connect_database(":memory:")
    try:
        repository = TermCandidateRepository(connection)
        service = TermCandidateService(
            tmp_path,
            repository,
            canonical_target_resolver=CanonicalTargetResolver(tmp_path, connection),
        )
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


@pytest.mark.parametrize(
    ("origin_type", "origin_id", "origin_exists", "expect_relation"),
    [
        ("source", "source-one", True, True),
        ("source", "source-one", False, False),
        ("research_work", "work-one", True, True),
        ("research_work", "work-one", False, False),
        ("external", "https://example.test/paper-one", True, False),
    ],
)
def test_accept_existing_only_links_live_canonical_origins(
    tmp_path, origin_type, origin_id, origin_exists, expect_relation
):
    _write_term(tmp_path)
    connection = connect_database(":memory:")
    try:
        if origin_type == "source" and origin_exists:
            sources = tmp_path / "knowledge" / "sources"
            sources.mkdir(parents=True)
            (sources / "source-one.yaml").write_text(
                "schema_version: 1\nid: source-one\ntype: paper\ntitle: Source One\n",
                encoding="utf-8",
            )
        elif origin_type == "research_work" and origin_exists:
            connection.execute(
                """INSERT INTO research_works (
                       id, canonical_key, title, normalized_title, authors_json,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (origin_id, "doi:10.1/work-one", "Work One", "work one", "[]", "now", "now"),
            )

        repository = TermCandidateRepository(connection)
        service = TermCandidateService(
            tmp_path,
            repository,
            canonical_target_resolver=CanonicalTargetResolver(tmp_path, connection),
        )
        candidate = service.create_candidate(
            "Existing Term Evidence",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type=origin_type,
                    origin_id=origin_id,
                    mention="Existing Term Evidence",
                )
            ],
        )

        accepted = service.accept_existing(candidate.id, "neural-indexing")

        assert accepted.status == "accepted"
        relations = connection.execute(
            "SELECT entity_type, entity_id FROM term_entity_relations"
        ).fetchall()
        if expect_relation:
            assert [(row["entity_type"], row["entity_id"]) for row in relations] == [
                (origin_type, origin_id)
            ]
        else:
            assert relations == []
    finally:
        connection.close()


def test_semantic_existing_suggestion_cannot_create_a_new_term_draft(tmp_path):
    _write_term(tmp_path)
    connection = connect_database(":memory:")
    try:
        repository = TermCandidateRepository(connection)
        drafts = DraftService(DraftRepository(connection))
        target_resolver = CanonicalTargetResolver(tmp_path, connection)

        class FakeGit:
            def current_revision(self):
                return "a" * 40

            def content_hash(self, path):
                return "b" * 64

        service = TermCandidateService(
            tmp_path, repository, drafts, FakeGit(), target_resolver
        )
        candidate = service.create_candidate(
            "Earlier category performance drops",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type="external",
                    origin_id="ref:semantic-existing",
                    mention="Earlier category performance drops",
                    context_excerpt="Earlier category performance drops after learning a new task.",
                )
            ],
            preferred_term_id="neural-indexing",
        )

        resolution = service.resolve_against_registry(candidate)
        assert candidate.suggested_term_id == "neural-indexing"
        assert resolution.status == "existing_term"
        assert resolution.term_id == "neural-indexing"
        with pytest.raises(TermCandidateConflict, match="existing Term"):
            service.create_term_draft(candidate.id)
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

        rejected = service.reject_candidate(
            candidate.id,
            "local",
            "Not useful here",
            origin_type="document",
            origin_id="note-one",
        )
        assert rejected.status == "pending"
        assert service.resolve_against_registry(candidate).status == "new_term"
        assert repository.is_rejected("latent space", "origin:document:note-one")
        assert not repository.is_rejected("latent space", "origin:source:paper-one")
        assert not repository.is_rejected("latent space", "origin:document:note-two")
        assert not repository.is_rejected("latent space", "global")
        with pytest.raises(TermCandidateConflict, match="Every origin"):
            service.create_candidate(
                "Latent Space",
                "concept",
                [
                    TermCandidateEvidenceInput(
                        origin_type="document",
                        origin_id="note-one",
                        mention="latent space",
                    )
                ],
            )
        allowed_elsewhere = service.create_candidate(
            "Latent Space",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type="document", origin_id="note-two", mention="latent space"
                )
            ],
        )
        assert allowed_elsewhere.id == candidate.id
        evidence = service.get_candidate(candidate.id).evidence
        assert {(item.origin_type, item.origin_id) for item in evidence} == {
            ("document", "note-one"),
            ("source", "paper-one"),
            ("document", "note-two"),
        }
        assert next(
            item for item in evidence if item.origin_id == "note-one"
        ).origin_rejected
        assert service.resolve_against_registry(allowed_elsewhere).status == "new_term"

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
        assert service.resolve_against_registry(global_candidate).status == "rejected"
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


def test_candidate_term_draft_lifecycle_and_publish_relations(tmp_path):
    _write_term(tmp_path)
    document_path = tmp_path / "knowledge" / "documents" / "learning" / "note-one.md"
    document_path.parent.mkdir(parents=True, exist_ok=True)
    document_path.write_text(
        "---\nschema_version: 1\nid: note-one\ntitle: Note One\n"
        "type: learning-note\ndomains: []\ntopics: []\ntags: []\nsources: []\n"
        "---\nA canonical note.\n",
        encoding="utf-8",
    )
    connection = connect_database(":memory:")
    try:
        repository = TermCandidateRepository(connection)
        drafts = DraftService(DraftRepository(connection))
        target_resolver = CanonicalTargetResolver(tmp_path, connection)

        class FakeGit:
            def current_revision(self):
                return "a" * 40

            def content_hash(self, path):
                return "b" * 64

        service = TermCandidateService(
            tmp_path,
            repository,
            drafts,
            FakeGit(),
            target_resolver,
        )
        candidate = service.create_candidate(
            "Adaptive Token Pruning",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type="document",
                    origin_id="note-one",
                    mention="adaptive token pruning",
                    context_excerpt="Adaptive token pruning reduces redundant tokens.",
                )
            ],
        )

        result = service.create_term_draft(candidate.id)
        assert result["created"] is True
        assert result["candidate"].status == "drafting"
        assert result["draft"].entity_id == "adaptive-token-pruning"
        assert "type: concept" in result["draft"].content
        assert "depth: stub" in result["draft"].content
        with pytest.raises(TermCandidateConflict, match="discard the linked Draft"):
            service.reject_candidate(candidate.id, "global")
        with pytest.raises(TermCandidateConflict, match="discard the linked Draft"):
            service.accept_existing(candidate.id, "neural-indexing")

        reused = service.create_term_draft(candidate.id)
        assert reused["created"] is False
        assert reused["draft"].id == result["draft"].id

        drafts.discard(result["draft"].id, result["draft"].revision)
        service.discard_term_draft(result["draft"].id)
        reset = repository.get_candidate(candidate.id)
        assert reset.status == "pending"
        assert reset.draft_id is None

        second = service.create_term_draft(candidate.id)
        draft = second["draft"]
        service.finalize_published_drafts(
            [
                Draft(
                    id=draft.id,
                    entity_type="term",
                    entity_id=draft.entity_id,
                    base_git_revision=draft.base_git_revision,
                    base_content_hash=draft.base_content_hash,
                    content=draft.content,
                    revision=draft.revision,
                    created_at=draft.created_at,
                    updated_at=draft.updated_at,
                )
            ]
        )

        accepted = repository.get_candidate(candidate.id)
        assert accepted.status == "accepted"
        assert accepted.accepted_term_id == "adaptive-token-pruning"
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT entity_type, entity_id, term_id FROM term_entity_relations"
            ).fetchall()
        ] == [("document", "note-one", "adaptive-token-pruning")]
    finally:
        connection.close()


@pytest.mark.parametrize("origin_type", ["source", "research_work", "external"])
def test_candidate_term_draft_accepts_generic_evidence_origins(tmp_path, origin_type):
    _write_term(tmp_path)
    origin_id = {
        "source": "source-one",
        "research_work": "work-one",
        "external": "https://example.test/paper-one",
    }[origin_type]
    if origin_type == "source":
        source_path = tmp_path / "knowledge" / "sources" / "source-one.yaml"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(
            "schema_version: 1\nid: source-one\ntype: paper\ntitle: Source One\n",
            encoding="utf-8",
        )

    connection = connect_database(":memory:")
    try:
        if origin_type == "research_work":
            connection.execute(
                """INSERT INTO research_works (
                       id, canonical_key, title, normalized_title, authors_json,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (origin_id, "doi:10.1/work-one", "Work One", "work one", "[]", "now", "now"),
            )
        repository = TermCandidateRepository(connection)
        drafts = DraftService(DraftRepository(connection))
        target_resolver = CanonicalTargetResolver(tmp_path, connection)

        class FakeGit:
            def current_revision(self):
                return "a" * 40

            def content_hash(self, path):
                return "b" * 64

        service = TermCandidateService(
            tmp_path, repository, drafts, FakeGit(), target_resolver
        )
        candidate = service.create_candidate(
            "Generic Evidence Term",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type=origin_type,
                    origin_id=origin_id,
                    mention="Generic Evidence Term",
                    context_excerpt="A bounded excerpt about the generic evidence term.",
                    rationale="This evidence is useful context for a reusable term.",
                )
            ],
        )

        result = service.create_term_draft(candidate.id)
        assert result["candidate"].status == "drafting"
        assert result["draft"].entity_id == "generic-evidence-term"

        service.finalize_published_drafts(
            [
                Draft(
                    id=result["draft"].id,
                    entity_type="term",
                    entity_id=result["draft"].entity_id,
                    base_git_revision=result["draft"].base_git_revision,
                    base_content_hash=result["draft"].base_content_hash,
                    content=result["draft"].content,
                    revision=result["draft"].revision,
                    created_at=result["draft"].created_at,
                    updated_at=result["draft"].updated_at,
                )
            ]
        )
        relations = connection.execute(
            "SELECT entity_type, entity_id FROM term_entity_relations"
        ).fetchall()
        if origin_type == "external":
            assert relations == []
        else:
            assert [(row["entity_type"], row["entity_id"]) for row in relations] == [
                (origin_type, origin_id)
            ]
    finally:
        connection.close()


def test_candidate_term_draft_rejects_all_rejected_evidence(tmp_path):
    _write_term(tmp_path)
    connection = connect_database(":memory:")
    try:
        repository = TermCandidateRepository(connection)
        drafts = DraftService(DraftRepository(connection))
        target_resolver = CanonicalTargetResolver(tmp_path, connection)

        class FakeGit:
            def current_revision(self):
                return "a" * 40

            def content_hash(self, path):
                return "b" * 64

        service = TermCandidateService(
            tmp_path, repository, drafts, FakeGit(), target_resolver
        )
        candidate = service.create_candidate(
            "Rejected Evidence Term",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type="external",
                    origin_id="ref:one",
                    mention="Rejected Evidence Term",
                    context_excerpt="A short excerpt.",
                )
            ],
        )
        service.reject_candidate(
            candidate.id,
            "local",
            origin_type="external",
            origin_id="ref:one",
        )
        with pytest.raises(TermCandidateConflict):
            service.create_term_draft(candidate.id)
    finally:
        connection.close()


@pytest.mark.parametrize("missing_origin_type", ["document", "source", "research_work"])
def test_candidate_term_draft_skips_missing_canonical_origins(
    tmp_path, missing_origin_type
):
    _write_term(tmp_path)
    connection = connect_database(":memory:")
    try:
        repository = TermCandidateRepository(connection)
        drafts = DraftService(DraftRepository(connection))
        target_resolver = CanonicalTargetResolver(tmp_path, connection)

        class FakeGit:
            def current_revision(self):
                return "a" * 40

            def content_hash(self, path):
                return "b" * 64

        service = TermCandidateService(
            tmp_path, repository, drafts, FakeGit(), target_resolver
        )
        candidate = service.create_candidate(
            "Remaining External Evidence",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type=missing_origin_type,
                    origin_id="missing-origin",
                    mention="Remaining External Evidence",
                    context_excerpt="Stale canonical context.",
                ),
                TermCandidateEvidenceInput(
                    origin_type="external",
                    origin_id="ref:remaining",
                    mention="Remaining External Evidence",
                    rationale="A live external evidence record.",
                ),
            ],
        )

        evidence = service.active_term_draft_evidence(candidate.id)
        assert [(item.origin_type, item.origin_id) for item in evidence] == [
            ("external", "ref:remaining")
        ]
        result = service.create_term_draft(candidate.id)
        service.finalize_published_drafts(
            [
                Draft(
                    id=result["draft"].id,
                    entity_type="term",
                    entity_id=result["draft"].entity_id,
                    base_git_revision=result["draft"].base_git_revision,
                    base_content_hash=result["draft"].base_content_hash,
                    content=result["draft"].content,
                    revision=result["draft"].revision,
                    created_at=result["draft"].created_at,
                    updated_at=result["draft"].updated_at,
                )
            ]
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM term_entity_relations"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_external_evidence_without_excerpt_or_rationale_cannot_create_term_draft(
    tmp_path,
):
    _write_term(tmp_path)
    connection = connect_database(":memory:")
    try:
        repository = TermCandidateRepository(connection)
        drafts = DraftService(DraftRepository(connection))
        target_resolver = CanonicalTargetResolver(tmp_path, connection)

        class FakeGit:
            def current_revision(self):
                return "a" * 40

            def content_hash(self, path):
                return "b" * 64

        service = TermCandidateService(
            tmp_path, repository, drafts, FakeGit(), target_resolver
        )
        candidate = service.create_candidate(
            "External Evidence Without Context",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type="external",
                    origin_id="ref:no-context",
                    mention="External Evidence Without Context",
                )
            ],
        )

        with pytest.raises(TermCandidateConflict, match="active Candidate Evidence"):
            service.create_term_draft(candidate.id)
    finally:
        connection.close()


def test_term_draft_ai_context_uses_generic_evidence(tmp_path):
    _write_term(tmp_path)
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    try:
        repository = TermCandidateRepository(connection)
        drafts = DraftService(DraftRepository(connection))
        target_resolver = CanonicalTargetResolver(tmp_path, connection)

        class FakeGit:
            def current_revision(self):
                return "a" * 40

            def content_hash(self, path):
                return "b" * 64

        service = TermCandidateService(
            tmp_path, repository, drafts, FakeGit(), target_resolver
        )
        candidate = service.create_candidate(
            "External Evidence Term",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type="external",
                    origin_id="ref:42",
                    mention="External Evidence Term",
                    context_excerpt="The external evidence excerpt.",
                    rationale="The external evidence rationale.",
                )
            ],
        )
        draft = service.create_term_draft(candidate.id)["draft"]

        class FakeAIProposalService:
            def __init__(self):
                self.context = None

            async def generate_async(self, task_name, draft_id, extra_context):
                self.context = extra_context
                return Proposal(
                    id="proposal-one",
                    target_type="term",
                    target_id=draft.entity_id,
                    kind="new_term",
                    status="proposed",
                    base_content_hash="b" * 64,
                    payload={},
                    diff_text=None,
                    created_by="ai",
                    provider="mock",
                    model="mock",
                    created_at="now",
                    reviewed_at=None,
                    review_note=None,
                )

        ai_proposals = FakeAIProposalService()
        app = FastAPI()
        app.include_router(ai_router)
        app.state.term_candidate_service = service
        app.state.draft_service = drafts
        app.state.ai_proposal_service = ai_proposals

        with TestClient(app) as client:
            response = client.post(
                "/api/ai/term-draft",
                json={
                    "draft_id": draft.id,
                    "candidate_id": candidate.id,
                    "confirm_deepseek_transfer": True,
                },
            )

        assert response.status_code == 201, response.json()
        evidence = ai_proposals.context["term_candidate"]["evidence"][0]
        assert evidence == {
            "origin_type": "external",
            "origin_id": "ref:42",
            "origin_title": "ref:42",
            "context_excerpt": "The external evidence excerpt.",
            "rationale": "The external evidence rationale.",
        }
        assert "note_evidence" not in ai_proposals.context["term_candidate"]
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
    sources = tmp_path / "knowledge" / "sources"
    sources.mkdir(parents=True)
    (sources / "paper-one.yaml").write_text(
        "schema_version: 1\nid: paper-one\ntype: paper\ntitle: Paper One\n",
        encoding="utf-8",
    )
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    service = TermCandidateService(
        tmp_path,
        TermCandidateRepository(connection),
        canonical_target_resolver=CanonicalTargetResolver(tmp_path, connection),
    )
    candidate = service.create_candidate(
        "Calibrated Optimizer",
        "entity",
        [
            TermCandidateEvidenceInput(
                origin_type="document",
                origin_id="note-one",
                mention="Calibrated Optimizer",
            ),
            TermCandidateEvidenceInput(
                origin_type="source",
                origin_id="paper-one",
                mention="Calibrated Optimizer",
            ),
        ],
    )
    app = FastAPI()
    app.include_router(terms_router)
    app.include_router(knowledge_router)
    app.state.term_candidate_service = service

    try:
        with TestClient(app) as client:
            listed = client.get("/api/terms/candidates")
            assert listed.status_code == 200
            assert listed.json()[0]["id"] == candidate.id
            detail = client.get("/api/terms/candidates/{}".format(candidate.id))
            assert detail.status_code == 200
            assert detail.json()["evidence"][0]["mention"] == "Calibrated Optimizer"
            rejected = client.post(
                "/api/terms/candidates/{}/reject".format(candidate.id),
                json={
                    "scope": "local",
                    "origin_type": "document",
                    "origin_id": "note-one",
                },
            )
            assert rejected.status_code == 200, rejected.json()
            assert rejected.json()["status"] == "pending"
            accepted = client.post(
                "/api/terms/candidates/{}/accept-existing".format(candidate.id),
                json={"term_id": "neural-indexing"},
            )
            assert accepted.status_code == 200, accepted.json()
            assert accepted.json()["accepted_term_id"] == "neural-indexing"
            assert [
                tuple(row)
                for row in connection.execute(
                    "SELECT entity_type, entity_id, term_id FROM term_entity_relations"
                ).fetchall()
            ] == [("source", "paper-one", "neural-indexing")]
    finally:
        connection.close()


def test_term_merge_api_serializes_preview_and_result():
    class FakeTermMergeService:
        def preview(self, survivor_term_id, loser_term_ids, final_title):
            return TermMergePreview(
                survivor_term_id,
                tuple(loser_term_ids),
                final_title,
                ("Former Title", "former-id"),
                ("former-id",),
                (
                    TermMergeSelectedTerm(
                        "survivor-term", "Survivor Term", "concept", "standard"
                    ),
                    TermMergeSelectedTerm(
                        "former-id", "Former Title", "concept", "stub"
                    ),
                ),
                True,
                True,
            )

        def merge(
            self,
            survivor_term_id,
            loser_term_ids,
            final_title,
            confirm_loser_bodies_not_merged=False,
            final_type=None,
            final_depth=None,
        ):
            return TermMergeResult(
                survivor_term_id,
                tuple(loser_term_ids),
                final_title,
                ("Former Title", "former-id"),
                ("former-id",),
                "a" * 40,
                ("Index rebuild warning",),
                (
                    TermMergeSelectedTerm(
                        "survivor-term", "Survivor Term", "concept", "standard"
                    ),
                    TermMergeSelectedTerm(
                        "former-id", "Former Title", "concept", "stub"
                    ),
                ),
                True,
                True,
            )

    app = FastAPI()
    app.include_router(terms_router)
    app.include_router(knowledge_router)
    app.state.term_merge_service = FakeTermMergeService()

    with TestClient(app) as client:
        payload = {
            "survivor_term_id": "survivor-term",
            "loser_term_ids": ["former-id"],
            "final_title": "Survivor Term",
        }
        preview = client.post("/api/terms/merge/preview", json=payload)
        assert preview.status_code == 200, preview.json()
        assert preview.json()["aliases"] == ["Former Title", "former-id"]
        assert preview.json()["selected_terms"] == [
            {
                "id": "survivor-term",
                "title": "Survivor Term",
                "type": "concept",
                "depth": "standard",
            },
            {
                "id": "former-id",
                "title": "Former Title",
                "type": "concept",
                "depth": "stub",
            },
        ]
        assert isinstance(preview.json()["loser_term_ids"], list)
        assert preview.json()["type_conflict"] is True
        merged = client.post(
            "/api/terms/merge",
            json={**payload, "confirm_loser_bodies_not_merged": True},
        )
        assert merged.status_code == 200, merged.json()
        assert merged.json()["commit_revision"] == "a" * 40
        assert merged.json()["warnings"] == ["Index rebuild warning"]


def _write_term(repository_root):
    terms = repository_root / "knowledge" / "terms"
    terms.mkdir(parents=True, exist_ok=True)
    (terms / "neural-indexing.md").write_text(
        "---\nschema_version: 1\nid: neural-indexing\ntitle: Neural Indexing\n"
        "type: concept\ndepth: standard\naliases:\n  - Calibrated Optimizer\n"
        "domains: []\ntopics: []\ntags: []\nsources: []\n---\n# Neural Indexing\n",
        encoding="utf-8",
    )


def _write_document(repository_root, document_id):
    documents = repository_root / "knowledge" / "documents" / "learning"
    documents.mkdir(parents=True, exist_ok=True)
    (documents / "{}.md".format(document_id)).write_text(
        "---\nschema_version: 1\nid: {}\ntitle: Test Note\ntype: learning-note\n"
        "domains: []\ntopics: []\ntags: []\nsources: []\n---\nA valid canonical note.\n".format(document_id),
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
