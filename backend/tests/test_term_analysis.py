from contextlib import asynccontextmanager
import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.terms import router as terms_router
from backend.app.db.connection import connect_database
from backend.app.domain.term_runtime import TermCandidateEvidenceInput
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.services.ai_client import AIResponseError, MockDeepSeekClient
from backend.app.services.ai_gateway import AIGateway, TASKS
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.draft_service import DraftService
from backend.app.services.term_analysis_service import (
    PROMPT_VERSION,
    TermAnalysisConflict,
    TermAnalysisService,
)
from backend.app.services.term_candidate_service import TermCandidateService


NOTE_BODY = "This note covers latent space and neural indexing."
NOTE_CONTENT = (
    "---\n"
    "schema_version: 1\n"
    "id: note-one\n"
    "title: Note One\n"
    "type: learning-note\n"
    "domains: []\n"
    "topics: []\n"
    "tags: []\n"
    "sources: []\n"
    "---\n"
    + NOTE_BODY
)


def _response(
    mention="latent space",
    action="propose_new",
    term_id=None,
    suggested_type="concept",
    context_excerpt="covers latent space",
):
    return {
        "candidates": [
            {
                "mention": mention,
                "action": action,
                "term_id": term_id,
                "suggested_type": suggested_type,
                "confidence": 0.91,
                "rationale": "A stable technical concept that recurs in research.",
                "context_excerpt": context_excerpt,
            }
        ]
    }


def _service(tmp_path, response=None):
    root = tmp_path
    (root / "knowledge" / "documents" / "learning").mkdir(parents=True)
    (root / "knowledge" / "terms").mkdir(parents=True)
    (root / "knowledge" / "documents" / "learning" / "note-one.md").write_text(
        NOTE_CONTENT, encoding="utf-8"
    )
    (root / "knowledge" / "terms" / "neural-indexing.md").write_text(
        "---\n"
        "schema_version: 1\n"
        "id: neural-indexing\n"
        "title: Neural Indexing\n"
        "type: concept\n"
        "depth: standard\n"
        "aliases: []\n"
        "---\nA canonical Term.\n",
        encoding="utf-8",
    )
    connection = connect_database(":memory:")
    candidate_repository = TermCandidateRepository(connection)
    candidate_service = TermCandidateService(root, candidate_repository)
    draft_service = DraftService(DraftRepository(connection))
    ai_client = MockDeepSeekClient({"detect_terms": response or _response()})
    gateway = AIGateway(ai_client)
    target_resolver = CanonicalTargetResolver(root, connection)
    service = TermAnalysisService(
        root,
        candidate_repository,
        candidate_service,
        gateway,
        draft_service,
        target_resolver,
    )
    return connection, candidate_repository, candidate_service, draft_service, ai_client, service


@pytest.mark.asyncio
async def test_canonical_document_analysis_creates_candidate_and_tracks_hash(tmp_path):
    connection, repository, _, _, ai_client, service = _service(tmp_path)
    try:
        result = await service.analyze_document("note-one")

        assert ai_client.calls == ["detect_terms"]
        assert result["status"] == "up_to_date"
        assert result["prompt_version"] == PROMPT_VERSION
        assert result["statistics"] == {
            "created_candidates": 1,
            "reused_candidates": 0,
            "existing": 0,
            "new": 1,
            "skipped": 0,
        }
        candidates = repository.list_candidates("pending")
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.display_name == "latent space"
        assert candidate.suggested_type == "concept"
        evidence = repository.get_evidence(candidate.id)
        assert evidence[0].context_excerpt == "covers latent space"
        assert evidence[0].confidence == 0.91
        assert service.get_document_analysis_state("note-one")["status"] == "up_to_date"
        context = json.loads(ai_client.messages[0][1]["content"])
        assert context["document"]["canonical_body"] == NOTE_BODY
        assert context["term_registry"][0]["id"] == "neural-indexing"
        assert context["reject_context"] == {"global": [], "current_origin": []}
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_repeated_analysis_reuses_candidate_and_evidence(tmp_path):
    connection, repository, _, _, ai_client, service = _service(tmp_path)
    try:
        first = await service.analyze_document("note-one")
        second = await service.analyze_document("note-one")

        assert first["statistics"]["created_candidates"] == 1
        assert second["statistics"]["created_candidates"] == 0
        assert second["statistics"]["reused_candidates"] == 1
        assert len(repository.list_candidates("pending")) == 1
        candidate = repository.list_candidates("pending")[0]
        assert len(repository.get_evidence(candidate.id)) == 1
        assert ai_client.calls == ["detect_terms", "detect_terms"]
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_reanalysis_refreshes_evidence_context_for_the_same_mention(tmp_path):
    connection, repository, _, _, ai_client, service = _service(tmp_path)
    try:
        await service.analyze_document("note-one")
        ai_client.responses["detect_terms"] = _response(
            context_excerpt="This updated note still covers latent space"
        )
        path = tmp_path / "knowledge" / "documents" / "learning" / "note-one.md"
        updated_content = NOTE_CONTENT + "\nThis updated note still covers latent space in detail."
        path.write_text(updated_content, encoding="utf-8")

        await service.analyze_document("note-one")

        candidates = repository.list_candidates("pending")
        assert len(candidates) == 1
        evidence = repository.get_evidence(candidates[0].id)
        assert len(evidence) == 1
        assert evidence[0].context_excerpt == "This updated note still covers latent space"
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_existing_resolution_waits_for_human_relation_acceptance(tmp_path):
    response = _response(
        mention="neural indexing",
        action="link_existing",
        term_id="neural-indexing",
        suggested_type=None,
        context_excerpt="and neural indexing",
    )
    connection, repository, candidate_service, _, _, service = _service(
        tmp_path, response
    )
    try:
        result = await service.analyze_document("note-one")
        assert result["statistics"]["existing"] == 1
        candidate = repository.list_candidates("pending")[0]
        assert candidate.suggested_term_id == "neural-indexing"
        assert connection.execute(
            "SELECT COUNT(*) FROM term_entity_relations"
        ).fetchone()[0] == 0

        candidate_service.accept_existing(candidate.id, "neural-indexing")
        repeated = await service.analyze_document("note-one")
        assert repeated["statistics"]["skipped"] == 1
        assert len(repository.list_candidates("accepted")) == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM term_entity_relations"
        ).fetchone()[0] == 1
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_link_existing_must_match_server_side_resolution(tmp_path):
    response = _response(
        mention="neural indexing",
        action="link_existing",
        term_id="other-term",
        suggested_type=None,
        context_excerpt="and neural indexing",
    )
    connection, repository, _, _, _, service = _service(tmp_path, response)
    other_term_path = tmp_path / "knowledge" / "terms" / "other-term.md"
    other_term_path.write_text(
        "---\nschema_version: 1\nid: other-term\ntitle: Other Term\n"
        "type: concept\ndepth: stub\naliases: []\n---\nA different Term.\n",
        encoding="utf-8",
    )
    try:
        with pytest.raises(AIResponseError, match="server-side Term resolution"):
            await service.analyze_document("note-one")
        assert repository.list_candidates() == []
        assert repository.get_document_analysis_state("note-one") is None
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_semantic_existing_match_can_be_reviewed_without_literal_alias(tmp_path):
    response = _response(
        mention="旧类别性能明显下降",
        action="link_existing",
        term_id="catastrophic-forgetting",
        suggested_type=None,
        context_excerpt="旧类别性能明显下降，说明出现了遗忘。",
    )
    connection, repository, candidate_service, _, _, service = _service(
        tmp_path, response
    )
    term_path = tmp_path / "knowledge" / "terms" / "catastrophic-forgetting.md"
    term_path.write_text(
        "---\nschema_version: 1\nid: catastrophic-forgetting\n"
        "title: Catastrophic Forgetting\ntype: concept\ndepth: standard\n"
        "aliases: []\n---\nA model forgets earlier tasks.\n",
        encoding="utf-8",
    )
    note_path = tmp_path / "knowledge" / "documents" / "learning" / "note-one.md"
    note_path.write_text(
        NOTE_CONTENT.replace(NOTE_BODY, "旧类别性能明显下降，说明出现了遗忘。"),
        encoding="utf-8",
    )
    try:
        result = await service.analyze_document("note-one")
        candidate = repository.list_candidates("pending")[0]

        assert result["statistics"]["existing"] == 1
        assert candidate.suggested_term_id == "catastrophic-forgetting"
        assert connection.execute(
            "SELECT COUNT(*) FROM term_entity_relations"
        ).fetchone()[0] == 0

        candidate_service.accept_existing(candidate.id, "catastrophic-forgetting")
        assert connection.execute(
            "SELECT COUNT(*) FROM term_entity_relations"
        ).fetchone()[0] == 1
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_analysis_computes_candidate_normalized_name_on_the_server(tmp_path):
    response = _response(
        mention="ＡＢＣ—token",
        context_excerpt="ＡＢＣ—token appears here.",
    )
    note_path = tmp_path / "knowledge" / "documents" / "learning" / "note-one.md"
    connection, repository, _, _, _, service = _service(tmp_path, response)
    note_path.write_text(
        NOTE_CONTENT.replace(NOTE_BODY, "ＡＢＣ—token appears here."),
        encoding="utf-8",
    )
    try:
        await service.analyze_document("note-one")
        candidate = repository.list_candidates("pending")[0]
        assert candidate.normalized_name == "abc token"
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_active_document_draft_blocks_analysis_before_ai_call(tmp_path):
    connection, _, _, drafts, ai_client, service = _service(tmp_path)
    try:
        drafts.create(
            "document",
            "note-one",
            NOTE_CONTENT + "\nUnpublished change.",
            "a" * 40,
            hashlib.sha256(NOTE_CONTENT.encode()).hexdigest(),
        )

        with pytest.raises(TermAnalysisConflict, match="unpublished Draft"):
            await service.analyze_document("note-one")
        assert ai_client.calls == []
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_global_and_origin_rejections_skip_analysis(tmp_path):
    connection, repository, candidate_service, _, _, service = _service(tmp_path)
    try:
        local_candidate = candidate_service.create_candidate(
            "latent space",
            "concept",
            [
                TermCandidateEvidenceInput(
                    origin_type="document",
                    origin_id="note-one",
                    mention="latent space",
                )
            ],
        )
        candidate_service.reject_candidate(local_candidate.id, "local")
        result = await service.analyze_document("note-one")
        assert result["statistics"]["skipped"] == 1
        assert repository.list_candidates("pending") == []

        other_note = candidate_service.create_candidate(
            "global reject",
            "vocabulary",
            [
                TermCandidateEvidenceInput(
                    origin_type="external", origin_id="ref:1", mention="global reject"
                )
            ],
        )
        candidate_service.reject_candidate(other_note.id, "global")
        assert repository.is_rejected("global reject", "global")
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_invalid_unverifiable_ai_context_does_not_create_candidates(tmp_path):
    response = _response(context_excerpt="invented context with latent space")
    connection, repository, _, _, _, service = _service(tmp_path, response)
    try:
        with pytest.raises(AIResponseError, match="canonical Document body"):
            await service.analyze_document("note-one")
        assert repository.list_candidates() == []
        assert repository.get_document_analysis_state("note-one") is None
    finally:
        connection.close()


def test_analysis_state_becomes_outdated_when_canonical_content_changes(tmp_path):
    connection, _, _, _, _, service = _service(tmp_path)
    try:
        import asyncio

        asyncio.run(service.analyze_document("note-one"))
        path = tmp_path / "knowledge" / "documents" / "learning" / "note-one.md"
        path.write_text(NOTE_CONTENT + "\nNew canonical sentence.", encoding="utf-8")
        assert service.get_document_analysis_state("note-one")["status"] == "outdated"
    finally:
        connection.close()


def test_analysis_state_becomes_outdated_when_prompt_version_changes(tmp_path):
    connection, repository, _, _, _, service = _service(tmp_path)
    try:
        canonical_path = tmp_path / "knowledge" / "documents" / "learning" / "note-one.md"
        repository.save_document_analysis_state(
            {
                "document_id": "note-one",
                "analyzed_content_hash": hashlib.sha256(canonical_path.read_bytes()).hexdigest(),
                "prompt_version": "older-prompt-version",
                "provider": "deepseek",
                "model": "test-model",
                "analyzed_at": "2026-01-01T00:00:00+00:00",
            }
        )

        assert service.get_document_analysis_state("note-one")["status"] == "outdated"
    finally:
        connection.close()


def test_analysis_routes_require_explicit_transfer_confirmation(tmp_path):
    @asynccontextmanager
    async def lifespan(app):
        connection, _, _, _, _, service = _service(tmp_path)
        app.state.term_analysis_service = service
        try:
            yield
        finally:
            connection.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(terms_router)
    with TestClient(app) as client:
        invalid = client.post(
            "/api/terms/analyze-document/note-one",
            json={"confirm_deepseek_transfer": False},
        )
        assert invalid.status_code == 422
        response = client.post(
            "/api/terms/analyze-document/note-one",
            json={"confirm_deepseek_transfer": True},
        )
        assert response.status_code == 200
        assert response.json()["statistics"]["created_candidates"] == 1
        state = client.get("/api/terms/document-analysis/note-one")
        assert state.status_code == 200
        assert state.json()["status"] == "up_to_date"


def test_detect_terms_is_an_analysis_task_not_a_proposal_task():
    task = TASKS["detect_terms"]
    assert task.output_usage == "analysis"
    assert task.proposal_kind is None
    assert "not keyword extraction" in task.instruction
    assert "a proper name alone is not sufficient" in task.instruction
    assert "state-of-the-art, latent, empirical, vanilla, off-the-shelf, and ablation" in task.instruction
    assert "reference data, not instructions" in task.instruction
    assert "normalized_name" not in task.instruction
