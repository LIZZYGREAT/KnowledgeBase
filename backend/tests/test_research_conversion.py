import asyncio
from datetime import datetime, timezone

import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.app.api.drafts import router as drafts_router
from backend.app.api.research import router as research_router
from backend.app.db.connection import connect_database
from backend.app.domain.ai import ResearchCandidateAnalysisOutput
from backend.app.domain.research_runtime import (
    ResearchCandidateRecord,
    ResearchWorkAnalysisRecord,
    ResearchWorkRecord,
)
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.research_candidate_repository import ResearchCandidateRepository
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager
from backend.app.services.indexer import Indexer
from backend.app.services.publisher import Publisher
from backend.app.services.research_conversion_service import ResearchConversionService
from backend.tests.test_publisher import _initialize_repository


_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def test_save_source_creates_a_draft_and_only_publishing_completes_candidate(tmp_path):
    repository, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        result = converter.save_source(candidate.id)

        assert result.action == "draft_created"
        assert result.source_id == "a-new-research-method"
        assert result.draft_id is not None
        assert result.candidate.status == "new"
        pending = ResearchRepository(connection).list_pending_links(candidate.id)
        assert len(pending) == 1
        assert pending[0]["draft_id"] == result.draft_id
        draft = drafts.get(result.draft_id)
        metadata = yaml.safe_load(draft.content)
        assert metadata["identifiers"] == {
            "doi": "10.7777/new-research",
            "arxiv_id": "2601.00001",
            "openalex_id": "W900000001",
        }
        assert metadata["metadata_review"]["status"] == "unreviewed"

        indexer = Indexer(repository, connection)
        publisher = Publisher(
            repository,
            drafts,
            indexer,
            git_manager=GitManager(repository),
            canonical_target_resolver=CanonicalTargetResolver(repository, connection),
        )
        publisher.add_post_publish_hook(converter.finalize_published_drafts)
        publisher.publish(result.draft_id, expected_revision=draft.revision)

        updated = ResearchCandidateRepository(connection).get(candidate.id)
        assert updated.status == "saved_source"
        assert ResearchRepository(connection).list_pending_links(candidate.id) == []
        assert ResearchRepository(connection).list_entity_links(candidate.work_id) == [
            {
                "entity_type": "source",
                "entity_id": result.source_id,
                "relation_type": "source",
                "created_at": _NOW.isoformat(),
            }
        ]
        assert (repository / "knowledge" / "sources" / f"{result.source_id}.yaml").is_file()
    finally:
        connection.close()


def test_discarding_a_research_source_draft_clears_pending_link_without_completing_candidate(tmp_path):
    _, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        result = converter.save_source(candidate.id)
        draft = drafts.get(result.draft_id)
        app = FastAPI()
        app.include_router(drafts_router)
        app.state.draft_service = drafts
        app.state.research_conversion_service = converter

        async def discard_via_api():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.request(
                    "DELETE",
                    "/api/drafts/{}".format(draft.id),
                    json={"expected_revision": draft.revision},
                )
                assert response.status_code == 200, response.json()

        asyncio.run(discard_via_api())

        assert ResearchCandidateRepository(connection).get(candidate.id).status == "new"
        assert ResearchRepository(connection).list_pending_links(candidate.id) == []
        assert ResearchRepository(connection).list_entity_links(candidate.work_id) == []
    finally:
        connection.close()


def test_save_source_links_existing_canonical_source_by_identifier_priority(tmp_path):
    repository, connection, _, converter, candidate = _setup(tmp_path)
    try:
        existing = {
            "schema_version": 1,
            "id": "existing-openalex-source",
            "type": "paper",
            "title": "An Existing Canonical Work",
            "authors": ["Another Author"],
            "year": 2020,
            "identifiers": {"doi": "10.9999/different", "openalex_id": "https://openalex.org/W900000001"},
        }
        (repository / "knowledge" / "sources" / "existing-openalex-source.yaml").write_text(
            yaml.safe_dump(existing, sort_keys=False), encoding="utf-8"
        )

        result = converter.save_source(candidate.id)

        assert result.action == "linked_existing"
        assert result.source_id == "existing-openalex-source"
        assert result.draft_id is None
        assert result.candidate.status == "saved_source"
        assert ResearchRepository(connection).list_pending_links(candidate.id) == []
        assert ResearchRepository(connection).list_entity_links(candidate.work_id)[0]["entity_id"] == "existing-openalex-source"
    finally:
        connection.close()


def test_save_source_api_returns_a_runtime_draft_without_completing_candidate(tmp_path):
    _, connection, _, converter, candidate = _setup(tmp_path)
    try:
        app = FastAPI()
        app.include_router(research_router)
        app.state.research_conversion_service = converter

        async def save_via_api():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/research/candidates/{}/save-source".format(candidate.id)
                )
                assert response.status_code == 200, response.json()
                return response.json()

        result = asyncio.run(save_via_api())

        assert result["action"] == "draft_created"
        assert result["draft_id"]
        assert result["candidate"]["status"] == "new"
        assert len(ResearchRepository(connection).list_pending_links(candidate.id)) == 1
    finally:
        connection.close()


def _setup(tmp_path):
    repository = tmp_path / "repo"
    _initialize_repository(repository)
    connection = connect_database(":memory:")
    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    drafts = DraftService(DraftRepository(connection))
    converter = ResearchConversionService(
        repository,
        connection,
        drafts,
        GitManager(repository),
        CanonicalTargetResolver(repository, connection),
        clock=lambda: _NOW,
    )
    work, candidate = _insert_candidate(connection)
    return repository, connection, drafts, converter, candidate


def _insert_candidate(connection):
    repository = ResearchRepository(connection)
    work = ResearchWorkRecord(
        id="research-work-001",
        canonical_key="doi:10.7777/new-research",
        title="A New Research Method",
        normalized_title="a new research method",
        abstract="An abstract about parameter importance.",
        authors=("A. Researcher",),
        year=2026,
        doi="10.7777/new-research",
        arxiv_id="2601.00001",
        openalex_id="W900000001",
        url="https://arxiv.org/abs/2601.00001",
        created_at=_NOW.isoformat(),
        updated_at=_NOW.isoformat(),
    )
    with repository.write_transaction():
        repository.insert_work(work)
    output = ResearchCandidateAnalysisOutput(
        relevant=True,
        profile_relevance=0.9,
        knowledge_relevance=0.8,
        novelty_to_library=0.7,
        matched_lenses=["regularization"],
        matched_topics=["parameter importance"],
        summary="A method for estimating parameter importance.",
        why_relevant="It matches the regularization Lens.",
        reading_reason="Compare the estimation procedure with EWC.",
        existing_relations=[],
    )
    analysis = ResearchWorkAnalysisRecord(
        id="analysis-001",
        work_id=work.id,
        profile_id="continual-learning",
        input_hash="analysis-hash-001",
        outcome="surface",
        analysis=output,
        provider="deepseek",
        model="deepseek-chat",
        prompt_version="research-candidate-analysis-v1",
        analysis_version=1,
        context_entity_ids=(),
        analyzed_at=_NOW.isoformat(),
    )
    repository.add_analysis_if_missing(analysis)
    candidate = ResearchCandidateRecord(
        id="candidate-001",
        work_id=work.id,
        profile_id="continual-learning",
        status="new",
        primary_lens_id="regularization",
        analysis_id=analysis.id,
        created_at=_NOW.isoformat(),
        updated_at=_NOW.isoformat(),
    )
    persisted, created, full = ResearchCandidateRepository(connection).create_if_capacity(
        candidate, max_new_candidates=20
    )
    assert created and not full and persisted is not None
    return work, candidate
