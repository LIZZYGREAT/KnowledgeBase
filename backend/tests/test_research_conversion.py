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
from backend.tests.test_publisher import _git, _initialize_repository
from tools.research import main as research_cli_main


_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def test_save_source_creates_a_draft_and_only_publishing_completes_candidate(tmp_path):
    repository, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        other_profile_candidate = _insert_other_profile_candidate(
            connection, candidate, status="shortlisted"
        )
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
        assert ResearchCandidateRepository(connection).get(
            other_profile_candidate.id
        ).status == "shortlisted"
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
        other_profile_candidate = _insert_other_profile_candidate(connection, candidate)
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
        assert ResearchCandidateRepository(connection).get(
            other_profile_candidate.id
        ).status == "new"
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


def test_multiple_candidates_reuse_and_publish_the_same_source_draft(tmp_path):
    repository, connection, drafts, converter, first_candidate = _setup(tmp_path)
    try:
        second_candidate = _insert_other_profile_candidate(connection, first_candidate)
        first_result = converter.save_source(first_candidate.id)
        second_result = converter.save_source(second_candidate.id)

        assert first_result.action == "draft_created"
        assert second_result.action == "draft_reused"
        assert second_result.draft_id == first_result.draft_id
        pending = ResearchRepository(connection)
        first_intent = pending.list_pending_links(first_candidate.id)
        second_intent = pending.list_pending_links(second_candidate.id)
        assert len(first_intent) == len(second_intent) == 1
        assert first_intent[0]["draft_id"] == second_intent[0]["draft_id"]
        assert first_intent[0]["group_id"] != second_intent[0]["group_id"]

        publisher = Publisher(
            repository,
            drafts,
            Indexer(repository, connection),
            git_manager=GitManager(repository),
            canonical_target_resolver=CanonicalTargetResolver(repository, connection),
        )
        publisher.add_post_publish_hook(converter.finalize_published_drafts)
        source_draft = drafts.get(first_result.draft_id)
        publisher.publish(source_draft.id, expected_revision=source_draft.revision)

        candidates = ResearchCandidateRepository(connection)
        assert candidates.get(first_candidate.id).status == "saved_source"
        assert candidates.get(second_candidate.id).status == "saved_source"
        assert pending.list_pending_links(first_candidate.id) == []
        assert pending.list_pending_links(second_candidate.id) == []
        assert len(pending.list_entity_links(first_candidate.work_id)) == 1
    finally:
        connection.close()


def test_create_note_builds_source_and_paper_note_drafts_without_completing_candidate(tmp_path):
    _, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        result = converter.create_note(candidate.id, "paper-note", "structured")

        document = drafts.get(result.document_draft_id)
        source = drafts.get(result.source_draft_id)
        metadata = yaml.safe_load(document.content.split("---", 2)[1])
        assert result.source_id == "a-new-research-method"
        assert metadata["sources"] == [result.source_id]
        assert "## 一、基本信息" in document.content
        assert "## 三、方法" in document.content
        assert "## 七、我的理解与问题" in document.content
        assert "Source Draft" not in document.content
        assert yaml.safe_load(source.content)["id"] == result.source_id
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "new"
        links = ResearchRepository(connection).list_pending_links(candidate.id)
        assert {link["relation_type"] for link in links} == {"source", "note"}
        assert {link["group_id"] for link in links} == {result.group_id}

        repeated = converter.create_note(candidate.id, "learning-note", "blank")
        assert repeated == result
    finally:
        connection.close()


def test_reused_source_draft_keeps_each_candidate_conversion_group_independent(tmp_path):
    _, connection, _, converter, source_candidate = _setup(tmp_path)
    try:
        source_result = converter.save_source(source_candidate.id)
        note_candidate = _insert_other_profile_candidate(connection, source_candidate)
        note_source_result = converter.save_source(note_candidate.id)

        result = converter.create_note(note_candidate.id, "paper-note", "structured")
        repeated = converter.create_note(note_candidate.id, "learning-note", "blank")

        assert source_result.draft_id is not None
        assert note_source_result.action == "draft_reused"
        assert result.source_draft_id == source_result.draft_id
        assert repeated == result
        group_links = ResearchRepository(connection).list_pending_links_for_group(
            result.group_id
        )
        assert {link["relation_type"] for link in group_links} == {"source", "note"}
        source_link = next(link for link in group_links if link["relation_type"] == "source")
        note_link = next(link for link in group_links if link["relation_type"] == "note")
        assert source_link["candidate_id"] == note_candidate.id
        assert note_link["candidate_id"] == note_candidate.id
        source_candidate_link = ResearchRepository(connection).list_pending_links(
            source_candidate.id
        )[0]
        assert source_candidate_link["group_id"] != result.group_id
        source_candidate_group = ResearchRepository(connection).list_pending_links_for_group(
            source_candidate_link["group_id"]
        )
        assert len(source_candidate_group) == 1
        assert source_candidate_group[0]["candidate_id"] == source_candidate.id
    finally:
        connection.close()


def test_create_note_reports_incomplete_rollback_to_the_api(tmp_path, monkeypatch):
    repository, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        collection_path = repository / "knowledge" / "collections" / "continual-learning.yaml"
        collection_path.parent.mkdir(parents=True, exist_ok=True)
        collection_content = (
            "schema_version: 1\nid: continual-learning\ntitle: Continual Learning\n"
            "status: active\nposition: 0\nnodes:\n  - id: regularization\n"
            "    kind: section\n    title: Regularization\n    children: []\n"
        )
        collection_path.write_text(collection_content, encoding="utf-8")
        _git(repository, "add", "knowledge/collections/continual-learning.yaml")
        _git(repository, "commit", "-m", "Add rollback Collection fixture")
        Indexer(repository, connection).full_rebuild()
        target = converter.canonical_target_resolver.resolve_target(
            "collection", "continual-learning", collection_content
        )
        collection_draft = drafts.create(
            "collection",
            "continual-learning",
            collection_content,
            converter.git.current_revision(),
            converter.git.content_hash(target.path),
        )

        original_save = drafts.save
        save_calls = 0

        def fail_restore(draft_id, content, expected_revision):
            nonlocal save_calls
            save_calls += 1
            if save_calls == 2:
                raise RuntimeError("restore blocked")
            return original_save(draft_id, content, expected_revision)

        discard_attempts = []

        def fail_discard(draft_id, expected_revision):
            discard_attempts.append(draft_id)
            raise RuntimeError("discard blocked")

        def fail_pending_link(**_kwargs):
            raise RuntimeError("pending link write failed")

        monkeypatch.setattr(drafts, "save", fail_restore)
        monkeypatch.setattr(drafts, "discard", fail_discard)
        monkeypatch.setattr(converter.work_repository, "add_pending_link", fail_pending_link)

        app = FastAPI()
        app.include_router(research_router)
        app.state.research_conversion_service = converter

        async def create_via_api():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.post(
                    "/api/research/candidates/{}/create-note".format(candidate.id),
                    json={
                        "document_type": "paper-note",
                        "template": "structured",
                        "collection_id": "continual-learning",
                        "section_id": "regularization",
                    },
                )

        response = asyncio.run(create_via_api())

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "rollback was incomplete" in detail
        assert "inspect related Source, Document, and Collection Drafts" in detail
        assert "Original error: pending link write failed" in detail
        assert "restore Collection Draft failed: restore blocked" in detail
        assert "discard Document Draft failed: discard blocked" in detail
        assert "discard Source Draft failed: discard blocked" in detail
        assert len(discard_attempts) == 2
        updated_collection = drafts.get(collection_draft.id)
        assert updated_collection.content != collection_content
        assert len(drafts.list_for_target("source", "a-new-research-method")) == 1
        assert not ResearchRepository(connection).list_pending_links(candidate.id)
    finally:
        connection.close()


def test_create_note_uses_existing_source_and_publishes_with_collection_in_one_batch(tmp_path):
    repository, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        collections = repository / "knowledge" / "collections"
        collections.mkdir(parents=True, exist_ok=True)
        collection_path = collections / "continual-learning.yaml"
        collection_path.write_text(
            "schema_version: 1\nid: continual-learning\ntitle: Continual Learning\n"
            "status: active\nposition: 0\nnodes:\n  - id: regularization\n"
            "    kind: section\n    title: Regularization\n    children: []\n",
            encoding="utf-8",
        )
        source = repository / "knowledge" / "sources" / "existing-research.yaml"
        source.write_text(
            "schema_version: 1\nid: existing-research\ntype: paper\n"
            "title: An Existing Canonical Work\nauthors: [Another Author]\nyear: 2020\n"
            "identifiers:\n  openalex_id: https://openalex.org/W900000001\n",
            encoding="utf-8",
        )
        _git(repository, "add", "knowledge/collections/continual-learning.yaml", "knowledge/sources/existing-research.yaml")
        _git(repository, "commit", "-m", "Add Research conversion fixtures")
        Indexer(repository, connection).full_rebuild()

        result = converter.create_note(
            candidate.id,
            "learning-note",
            "structured",
            collection_id="continual-learning",
            section_id="regularization",
        )
        assert result.source_id == "existing-research"
        assert result.source_draft_id is None
        document = drafts.get(result.document_draft_id)
        assert "## 一、前置知识" in document.content
        assert "## 三、数学与公式" in document.content
        assert "## 六、我的疑问" in document.content
        assert yaml.safe_load(document.content.split("---", 2)[1])["sources"] == ["existing-research"]

        collection_draft = drafts.get(result.collection_draft_id)
        collection_value = yaml.safe_load(collection_draft.content)
        assert collection_value["nodes"][0]["children"][0]["entity_id"] == result.document_id
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "new"

        publisher = Publisher(
            repository,
            drafts,
            Indexer(repository, connection),
            git_manager=GitManager(repository),
            canonical_target_resolver=CanonicalTargetResolver(repository, connection),
        )
        publisher.add_post_publish_hook(converter.finalize_published_drafts)
        published = publisher.publish_batch(
            [
                (document.id, document.revision),
                (collection_draft.id, collection_draft.revision),
            ]
        )
        assert len(published.results) == 2
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "note_created"
        assert {link["entity_type"] for link in ResearchRepository(connection).list_entity_links(candidate.work_id)} == {"source", "document"}
        assert ResearchRepository(connection).list_pending_links(candidate.id) == []
    finally:
        connection.close()


def test_create_note_batches_new_source_document_and_collection_before_finalizing_candidate(tmp_path):
    repository, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        collections = repository / "knowledge" / "collections"
        collections.mkdir(parents=True, exist_ok=True)
        (collections / "continual-learning.yaml").write_text(
            "schema_version: 1\nid: continual-learning\ntitle: Continual Learning\n"
            "status: active\nposition: 0\nnodes:\n  - id: regularization\n"
            "    kind: section\n    title: Regularization\n    children: []\n",
            encoding="utf-8",
        )
        _git(repository, "add", "knowledge/collections/continual-learning.yaml")
        _git(repository, "commit", "-m", "Add Research Collection fixture")
        Indexer(repository, connection).full_rebuild()

        result = converter.create_note(
            candidate.id,
            "paper-note",
            "structured",
            collection_id="continual-learning",
            section_id="regularization",
        )
        assert result.source_draft_id is not None
        source_draft = drafts.get(result.source_draft_id)
        document_draft = drafts.get(result.document_draft_id)
        collection_draft = drafts.get(result.collection_draft_id)
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "new"

        publisher = Publisher(
            repository,
            drafts,
            Indexer(repository, connection),
            git_manager=GitManager(repository),
            canonical_target_resolver=CanonicalTargetResolver(repository, connection),
        )
        publisher.add_post_publish_hook(converter.finalize_published_drafts)
        published = publisher.publish_batch(
            [
                (source_draft.id, source_draft.revision),
                (document_draft.id, document_draft.revision),
                (collection_draft.id, collection_draft.revision),
            ]
        )

        assert len(published.results) == 3
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "note_created"
        assert {link["relation_type"] for link in ResearchRepository(connection).list_entity_links(candidate.work_id)} == {"source", "note"}
        assert ResearchRepository(connection).list_pending_links(candidate.id) == []
        assert (repository / "knowledge" / "sources" / "a-new-research-method.yaml").is_file()
        assert (repository / "knowledge" / "documents" / "papers" / f"{result.document_id}.md").is_file()
    finally:
        connection.close()


def test_create_note_api_returns_draft_group_ids(tmp_path):
    _, connection, _, converter, candidate = _setup(tmp_path)
    try:
        app = FastAPI()
        app.include_router(research_router)
        app.state.research_conversion_service = converter

        async def create_via_api():
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/api/research/candidates/{}/create-note".format(candidate.id),
                    json={"document_type": "paper-note", "template": "blank"},
                )
                assert response.status_code == 200, response.json()
                return response.json()

        result = asyncio.run(create_via_api())
        assert result["group_id"]
        assert result["source_draft_id"]
        assert result["document_draft_id"]
        assert result["collection_draft_id"] is None
        assert result["collection_id"] is None
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "new"
    finally:
        connection.close()


def test_reconcile_recovers_published_note_after_post_publish_failure(tmp_path):
    repository, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        result = converter.create_note(
            candidate.id, "paper-note", "structured"
        )
        source_draft = drafts.get(result.source_draft_id)
        document_draft = drafts.get(result.document_draft_id)
        publisher = Publisher(
            repository,
            drafts,
            Indexer(repository, connection),
            git_manager=GitManager(repository),
            canonical_target_resolver=CanonicalTargetResolver(repository, connection),
        )

        def fail_runtime_finalize(_drafts):
            raise RuntimeError("injected conversion failure")

        publisher.add_post_publish_hook(fail_runtime_finalize)
        published = publisher.publish_batch(
            [
                (source_draft.id, source_draft.revision),
                (document_draft.id, document_draft.revision),
            ]
        )

        assert any(
            "injected conversion failure" in warning
            for warning in published.warnings
        )
        assert drafts.repository.get(source_draft.id) is None
        assert drafts.repository.get(document_draft.id) is None
        assert len(ResearchRepository(connection).list_pending_links(candidate.id)) == 2
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "new"

        recovered = converter.reconcile_pending_links()

        assert recovered == {
            "finalized": 2,
            "stale": 0,
            "pending": 0,
            "warnings": (),
        }
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "note_created"
        assert {
            (link["entity_type"], link["relation_type"])
            for link in ResearchRepository(connection).list_entity_links(candidate.work_id)
        } == {("source", "source"), ("document", "note")}
        assert converter.reconcile_pending_links() == {
            "finalized": 0,
            "stale": 0,
            "pending": 0,
            "warnings": (),
        }
    finally:
        connection.close()


def test_reconcile_leaves_pending_conversion_while_its_draft_exists(tmp_path):
    repository, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        result = converter.save_source(candidate.id)
        draft = drafts.get(result.draft_id)
        target = converter.canonical_target_resolver.resolve_target(
            "source", result.source_id, draft.content
        )
        target.path.write_bytes(draft.content.encode("utf-8"))

        report = converter.reconcile_pending_links()

        assert report["finalized"] == 0
        assert report["stale"] == 0
        assert report["pending"] == 1
        assert report["warnings"] == ()
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "new"
        assert ResearchRepository(connection).list_entity_links(candidate.work_id) == []
    finally:
        connection.close()


def test_reconcile_cleans_stale_pending_conversion_without_canonical_target(tmp_path):
    _, connection, drafts, converter, candidate = _setup(tmp_path)
    try:
        result = converter.save_source(candidate.id)
        draft = drafts.get(result.draft_id)
        drafts.discard(draft.id, draft.revision)

        report = converter.reconcile_pending_links()

        assert report == {
            "finalized": 0,
            "stale": 1,
            "pending": 0,
            "warnings": (),
        }
        assert ResearchCandidateRepository(connection).get(candidate.id).status == "new"
        assert ResearchRepository(connection).list_entity_links(candidate.work_id) == []
    finally:
        connection.close()


def test_research_cli_exposes_conversion_reconcile(tmp_path):
    repository, connection, _, _, _ = _setup(tmp_path)
    connection.close()
    database_path = tmp_path / "runtime" / "knowledge.db"

    result = research_cli_main(
        [
            "reconcile",
            "--root",
            str(repository),
            "--database",
            str(database_path),
        ]
    )

    assert result == 0


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


def _insert_other_profile_candidate(connection, candidate, status="new"):
    other = ResearchCandidateRecord(
        id="candidate-other-profile",
        work_id=candidate.work_id,
        profile_id="other-profile",
        status=status,
        primary_lens_id="regularization",
        analysis_id=candidate.analysis_id,
        created_at=_NOW.isoformat(),
        updated_at=_NOW.isoformat(),
    )
    persisted, created, full = ResearchCandidateRepository(connection).create_if_capacity(
        other, max_new_candidates=20
    )
    assert created and not full and persisted is not None
    return persisted
