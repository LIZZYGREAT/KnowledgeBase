import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.app.db.connection import connect_database
from backend.app.domain.ai import ResearchCandidateAnalysisOutput
from backend.app.domain.research_runtime import ResearchWorkAnalysisRecord
from backend.app.main import app
from backend.app.repositories.proposal_repository import ProposalRepository
from backend.app.repositories.research_control_event_repository import (
    ResearchControlEventRepository,
)
from backend.app.repositories.research_search_repository import ResearchSearchRepository
from backend.app.services.ai_client import MockDeepSeekClient
from backend.app.services.ai_gateway import AIGateway
from backend.app.services.ai_proposal_service import AIProposalService
from backend.app.services.indexer import Indexer
from backend.app.services.proposal_service import ProposalService
from backend.app.services.research_providers.base import ProviderWork
from backend.tests.runtime_db import open_test_runtime
from backend.tests.test_research_runs import FakeProvider, _service


_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    repository = _create_repository(tmp_path / "repository")
    database = tmp_path / "runtime" / "knowledge.db"
    connection = connect_database(database)
    try:
        Indexer(repository, connection).full_rebuild()
    finally:
        connection.close()
    monkeypatch.setenv("KNOWLEDGE_REPO_PATH", str(repository))
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with TestClient(app) as client:
        yield client


def test_read_api_search_openapi_and_missing_entities(api_client):
    documents = api_client.get("/api/documents").json()
    assert [item["id"] for item in documents] == ["neural-indexing"]
    assert "path" not in documents[0]

    document = api_client.get("/api/documents/neural-indexing").json()
    assert document["content"].startswith("# Neural Indexing")
    assert [term["id"] for term in document["related_terms"]] == ["neural-indexing"]
    assert document["evidence"][0]["source_id"] == "source-alpha"

    term = api_client.get("/api/terms/neural-indexing").json()
    assert term["backlinks"][0]["source_entity_id"] == "neural-indexing"
    assert term["canonical_content"].startswith("---\nschema_version: 1")
    mention_content = _document_content("unlinked-note", "Unlinked Note").replace(
        "A stable index retains canonical facts", "Neural Indexing appears here without a wiki link"
    ).replace("[[Calibrated Optimizer]]", "unrelated content")
    mention_path = (
        api_client.app.state.repository_root
        / "knowledge" / "documents" / "learning" / "unlinked-note.md"
    )
    mention_path.write_text(mention_content, encoding="utf-8")
    connection = connect_database(api_client.app.state.database_path)
    try:
        Indexer(api_client.app.state.repository_root, connection).update_path(mention_path)
    finally:
        connection.close()
    term = api_client.get("/api/terms/neural-indexing").json()
    assert term["detected_mentions"] == [{"id": "unlinked-note", "title": "Unlinked Note"}]
    source = api_client.get("/api/sources/source-alpha").json()
    assert source["related_documents"][0]["id"] == "neural-indexing"
    assert [term["id"] for term in source["related_terms"]] == ["neural-indexing"]
    assert "path" not in source
    assert api_client.get("/api/topics").json() == [{"id": "graph-search", "title": "Graph Search"}]
    assert api_client.get("/api/taxonomy", params={"kind": "topic"}).json() == [
        {"id": "graph-search", "title": "Graph Search", "kind": "topic"}
    ]
    modified = api_client.get("/api/documents/recently-modified").json()
    assert modified[0]["id"] == "neural-indexing"
    assert modified[0]["modified_at"]
    link_issues = api_client.get("/api/review/link-issues").json()
    assert any(issue["target"] == "Missing Term" and issue["status"] == "unresolved" for issue in link_issues)
    assert api_client.get("/api/imports").json() == []

    results = api_client.get("/api/search", params={"query": "stable index"}).json()
    assert results[0]["entity_id"] == "neural-indexing"
    assert results[0]["matched_by"] == "full text"
    assert "path" not in results[0]
    assert api_client.get("/api/documents/missing").status_code == 404

    schema = api_client.get("/openapi.json").json()
    assert schema["info"]["version"] == "0.8.0"
    for path in (
        "/api/documents/{entity_id}",
        "/api/terms/{entity_id}",
        "/api/sources/{entity_id}",
        "/api/collections",
        "/api/collections/{collection_id}",
        "/api/collections/{collection_id}/navigation",
        "/api/collections/{collection_id}/progress/{document_id}",
        "/api/library/unfiled",
        "/api/search",
        "/api/taxonomy",
        "/api/review/link-issues",
        "/api/documents/recently-modified",
        "/api/sources/{entity_id}/pdf",
        "/api/imports/upload",
        "/api/context/export",
        "/api/ai/document-review",
        "/api/ai/metadata-suggest",
        "/api/drafts",
        "/api/drafts/{draft_id}/compare",
        "/api/drafts/{draft_id}/rebase",
        "/api/publish",
        "/api/publish/batch",
        "/api/annotations",
        "/api/annotations/stale",
        "/api/annotations/{annotation_id}",
    ):
        assert path in schema["paths"]
    context_schema = schema["components"]["schemas"]["ContextExportRequest"]
    assert "provisional traceability filter" in context_schema["properties"]["trust"]["description"]


def test_presentation_annotations_never_change_canonical_markdown(api_client):
    entity = api_client.get("/api/documents/neural-indexing").json()
    canonical_path = (
        api_client.app.state.repository_root
        / "knowledge" / "documents" / "learning" / "neural-indexing.md"
    )
    before = canonical_path.read_bytes()
    body = entity["content"]
    selected = "stable index"
    start = body.index(selected)
    base_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

    created = api_client.post(
        "/api/annotations",
        json={
            "entity_type": "document",
            "entity_id": "neural-indexing",
            "style_type": "highlight",
            "style_value": "yellow",
            "selected_text": selected,
            "prefix_text": "",
            "suffix_text": "",
            "start_offset": start,
            "end_offset": start + len(selected),
            "base_content_hash": base_hash,
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "active"
    assert api_client.get(
        "/api/annotations",
        params={"entity_type": "document", "entity_id": "neural-indexing"},
    ).json()[0]["selected_text"] == selected
    assert canonical_path.read_bytes() == before

    annotation_id = created.json()["id"]
    assert api_client.put(
        "/api/annotations/{}".format(annotation_id),
        json={"style_type": "underline", "style_value": None},
    ).json()["style_type"] == "underline"
    assert api_client.delete("/api/annotations/{}".format(annotation_id)).json() == {"deleted": True}
    assert api_client.get(
        "/api/annotations",
        params={"entity_type": "document", "entity_id": "neural-indexing"},
    ).json() == []


def test_orphan_presentation_annotation_does_not_break_review(api_client):
    entity = api_client.get("/api/documents/neural-indexing").json()
    selected = "stable index"
    start = entity["content"].index(selected)
    base_hash = hashlib.sha256(entity["content"].encode("utf-8")).hexdigest()
    created = api_client.post(
        "/api/annotations",
        json={
            "entity_type": "document",
            "entity_id": "neural-indexing",
            "style_type": "highlight",
            "style_value": "yellow",
            "selected_text": selected,
            "prefix_text": "",
            "suffix_text": "",
            "start_offset": start,
            "end_offset": start + len(selected),
            "base_content_hash": base_hash,
        },
    )
    assert created.status_code == 201

    canonical_path = (
        api_client.app.state.repository_root
        / "knowledge" / "documents" / "learning" / "neural-indexing.md"
    )
    canonical_path.unlink()
    connection = connect_database(api_client.app.state.database_path)
    try:
        Indexer(api_client.app.state.repository_root, connection).update_path(canonical_path)
    finally:
        connection.close()

    stale = api_client.get("/api/annotations/stale")
    assert stale.status_code == 200
    assert stale.json() == []
    assert api_client.get("/api/review/link-issues").status_code == 200


def test_context_export_applies_requested_trust_and_purpose(api_client):
    raw = api_client.post(
        "/api/context/export",
        json={"document_id": "neural-indexing", "trust": "raw", "purpose": "research"},
    )
    assert raw.status_code == 200
    raw_context = raw.json()
    assert raw_context["documents"][0]["content"].startswith("# Neural Indexing")
    assert raw_context["known_ambiguities"][0]["status"] == "unresolved"

    verified = api_client.post(
        "/api/context/export",
        json={"document_id": "neural-indexing", "trust": "verified", "purpose": "research"},
    ).json()
    assert [source["id"] for source in verified["sources"]] == ["source-alpha"]
    assert verified["claims"][0]["claim"] == "A stable index retains canonical facts"
    assert "content" not in verified["documents"][0]

    evidence_only = api_client.post(
        "/api/context/export",
        json={"source_id": "source-alpha", "trust": "verified", "purpose": "evidence"},
    ).json()
    assert evidence_only["documents"] == []
    assert evidence_only["terms"] == []
    assert evidence_only["claims"]
    assert api_client.post("/api/context/export", json={}).status_code == 422


def test_draft_compare_rebase_list_and_discard_are_revision_guarded(api_client):
    created = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "document",
            "entity_id": "neural-indexing",
            "content": _document_content(),
        },
    )
    assert created.status_code == 201
    assert created.json()["created"] is True
    draft = created.json()["draft"]
    repeated = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "document",
            "entity_id": "neural-indexing",
            "content": _document_content() + "\nDifferent request body.\n",
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["created"] is False
    assert repeated.json()["draft"]["id"] == draft["id"]
    assert repeated.json()["draft"]["content"] == draft["content"]
    drafts = api_client.get(
        "/api/drafts", params={"entity_type": "document", "entity_id": "neural-indexing"}
    )
    assert drafts.status_code == 200
    assert len(drafts.json()) == 1
    assert drafts.json()[0]["id"] == draft["id"]

    unchanged = api_client.get("/api/drafts/{}/compare".format(draft["id"])).json()
    assert unchanged["canonical_changed"] is False
    assert unchanged["base_content"].startswith("---\nschema_version: 1")
    assert unchanged["current_content_hash"] == draft["base_content_hash"]

    canonical_path = (
        api_client.app.state.repository_root
        / "knowledge" / "documents" / "learning" / "neural-indexing.md"
    )
    changed_content = _document_content().replace(
        "A stable index retains canonical facts", "A revised canonical claim"
    )
    canonical_path.write_text(changed_content, encoding="utf-8")
    changed = api_client.get("/api/drafts/{}/compare".format(draft["id"])).json()
    assert changed["canonical_changed"] is True
    assert "A revised canonical claim" in changed["current_content"]

    rebased_content = _document_content() + "\nA reviewed Draft change.\n"
    rebased = api_client.put(
        "/api/drafts/{}/rebase".format(draft["id"]),
        json={
            "content": rebased_content,
            "expected_revision": draft["revision"],
            "expected_current_hash": changed["current_content_hash"],
        },
    )
    assert rebased.status_code == 200, rebased.json()
    assert rebased.json()["content"] == rebased_content
    assert rebased.json()["base_content_hash"] == changed["current_content_hash"]
    assert api_client.get("/api/drafts/{}/compare".format(draft["id"])).json()["canonical_changed"] is False

    stale_revision = api_client.put(
        "/api/drafts/{}/rebase".format(draft["id"]),
        json={
            "content": rebased_content,
            "expected_revision": draft["revision"],
            "expected_current_hash": changed["current_content_hash"],
        },
    )
    assert stale_revision.status_code == 409

    stale = api_client.put(
        "/api/drafts/{}/rebase".format(draft["id"]),
        json={
            "content": rebased_content,
            "expected_revision": rebased.json()["revision"],
            "expected_current_hash": "0" * 64,
        },
    )
    assert stale.status_code == 422
    stale_delete = api_client.request(
        "DELETE",
        "/api/drafts/{}".format(draft["id"]),
        json={"expected_revision": draft["revision"]},
    )
    assert stale_delete.status_code == 409
    discarded = api_client.request(
        "DELETE",
        "/api/drafts/{}".format(draft["id"]),
        json={"expected_revision": rebased.json()["revision"]},
    )
    assert discarded.status_code == 200
    assert discarded.json() == {"deleted": True}
    assert api_client.get("/api/drafts/{}".format(draft["id"])).status_code == 404


def test_runtime_draft_revision_conflict_returns_structured_error(api_client):
    created = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "document",
            "entity_id": "neural-indexing",
            "content": _document_content(),
        },
    )
    draft = created.json()["draft"]
    first_update = api_client.put(
        "/api/drafts/{}".format(draft["id"]),
        json={"content": "first update", "expected_revision": draft["revision"]},
    )
    assert first_update.status_code == 200

    stale_update = api_client.put(
        "/api/drafts/{}".format(draft["id"]),
        json={"content": "stale update", "expected_revision": draft["revision"]},
    )
    assert stale_update.status_code == 409
    assert stale_update.json()["code"] == "draft_revision_conflict"
    assert stale_update.json()["expected_revision"] == draft["revision"]
    assert stale_update.json()["current_revision"] == first_update.json()["revision"]


def test_collection_draft_uses_the_existing_runtime_lifecycle(api_client):
    repository = api_client.app.state.repository_root
    collection_path = repository / "knowledge" / "collections" / "reading.yaml"
    collection_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "schema_version: 1\nid: reading\ntitle: Reading\nstatus: active\n"
        "position: 0\nnodes:\n  - id: notes\n    kind: section\n"
        "    title: Notes\n    children:\n      - id: neural-indexing-node\n"
        "        kind: entity\n        entity_type: document\n"
        "        entity_id: neural-indexing\n"
    )
    collection_path.write_text(content, encoding="utf-8")

    created = api_client.post(
        "/api/drafts",
        json={"entity_type": "collection", "entity_id": "reading", "content": content},
    )

    assert created.status_code == 201, created.json()
    assert created.json()["created"] is True
    draft = created.json()["draft"]
    assert draft["entity_type"] == "collection"
    assert api_client.get(
        "/api/drafts", params={"entity_type": "collection", "entity_id": "reading"}
    ).json()[0]["id"] == draft["id"]
    comparison = api_client.get("/api/drafts/{}/compare".format(draft["id"]))
    assert comparison.status_code == 200
    assert comparison.json()["canonical_changed"] is False

    updated = api_client.put(
        "/api/drafts/{}".format(draft["id"]),
        json={"content": content.replace("title: Reading", "title: New Reading"), "expected_revision": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["entity_type"] == "collection"

    current_content = content.replace("title: Reading", "title: Current Reading")
    collection_path.write_text(current_content, encoding="utf-8")
    changed = api_client.get("/api/drafts/{}/compare".format(draft["id"]))
    assert changed.status_code == 200
    assert changed.json()["canonical_changed"] is True
    assert "Current Reading" in changed.json()["current_content"]

    rebased_content = content.replace("title: Reading", "title: Kept Draft")
    rebased = api_client.put(
        "/api/drafts/{}/rebase".format(draft["id"]),
        json={
            "content": rebased_content,
            "expected_revision": updated.json()["revision"],
            "expected_current_hash": changed.json()["current_content_hash"],
        },
    )
    assert rebased.status_code == 200, rebased.json()
    assert rebased.json()["entity_type"] == "collection"
    assert rebased.json()["content"] == rebased_content
    comparison = api_client.get("/api/drafts/{}/compare".format(draft["id"]))
    assert comparison.status_code == 200
    assert comparison.json()["canonical_changed"] is False


def test_research_profile_draft_publish_validates_and_refreshes_runtime_registry(api_client):
    repository = api_client.app.state.repository_root
    profile_path = (
        repository / "config" / "research" / "profiles" / "continual-learning.yaml"
    )
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["title"] = "Updated Continual Learning"
    profile["context"]["documents"] = ["missing-research-document"]
    invalid_content = yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)

    created = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "research_profile",
            "entity_id": "continual-learning",
            "content": invalid_content,
        },
    )

    assert created.status_code == 201, created.json()
    draft = created.json()["draft"]
    assert draft["entity_type"] == "research_profile"
    assert api_client.get(
        "/api/drafts",
        params={
            "entity_type": "research_profile",
            "entity_id": "continual-learning",
        },
    ).json()[0]["id"] == draft["id"]
    invalid_preflight = api_client.get(
        "/api/drafts/{}/preflight".format(draft["id"])
    )
    assert invalid_preflight.status_code == 200
    assert invalid_preflight.json()["valid"] is False
    assert "unknown pinned Document id(s): missing-research-document" in " ".join(
        invalid_preflight.json()["errors"]
    )

    profile["context"]["documents"] = ["neural-indexing"]
    valid_content = yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)
    updated = api_client.put(
        "/api/drafts/{}".format(draft["id"]),
        json={"content": valid_content, "expected_revision": draft["revision"]},
    )
    assert updated.status_code == 200, updated.json()
    assert updated.json()["revision"] == 2
    preflight = api_client.get("/api/drafts/{}/preflight".format(draft["id"]))
    assert preflight.status_code == 200
    assert preflight.json()["valid"] is True
    reactivation_review = api_client.post(
        "/api/research/profiles/continual-learning/reactivation-review",
        json={"draft_id": draft["id"]},
    )
    assert reactivation_review.status_code == 200, reactivation_review.json()
    assert reactivation_review.json()["required"] is False

    published = api_client.post(
        "/api/publish",
        json={"draft_id": draft["id"], "expected_revision": updated.json()["revision"]},
    )

    assert published.status_code == 200, published.json()
    assert published.json()["entity_type"] == "research_profile"
    visible_profiles = api_client.get("/api/research/profiles").json()
    assert next(
        item for item in visible_profiles if item["id"] == "continual-learning"
    )["title"] == "Updated Continual Learning"
    assert subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "research(continual-learning): update research profile"


def test_research_profile_publish_rejects_missing_reactivation_strategy(api_client):
    service = api_client.app.state.research_service
    repository = api_client.app.state.repository_root
    profile = service.profile_registry.get("continual-learning")
    disabled = profile.model_copy(update={"enabled": False})
    service.profile_registry = replace(
        service.profile_registry,
        profiles=tuple(
            disabled if item.id == profile.id else item
            for item in service.profile_registry.profiles
        ),
    )
    query = service.query_builder.build(disabled)[0]
    stale = service.now() - timedelta(days=90)
    with open_test_runtime(api_client) as connection:
        search_repository = ResearchSearchRepository(connection)
        search_repository.record_attempt(
            profile.id,
            query.lens_id,
            "arxiv",
            query.query_key,
            query.text,
            stale.isoformat(),
        )
        search_repository.complete_slice(
            profile.id,
            query.lens_id,
            "arxiv",
            query.query_key,
            stale.isoformat(),
            stale.isoformat(),
        )

    profile_path = repository / "config" / "research" / "profiles" / "continual-learning.yaml"
    candidate = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    candidate["title"] = "Reactivation Gate Test"
    created = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "research_profile",
            "entity_id": profile.id,
            "content": yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True),
        },
    )
    assert created.status_code == 201, created.json()
    draft = created.json()["draft"]

    review = api_client.post(
        "/api/research/profiles/{}/reactivation-review".format(profile.id),
        json={"draft_id": draft["id"]},
    )
    assert review.status_code == 200, review.json()
    assert review.json()["required"] is True
    assert review.json()["triggers"] == ["profile_enabled"]

    published = api_client.post(
        "/api/publish",
        json={"draft_id": draft["id"], "expected_revision": draft["revision"]},
    )
    assert published.status_code == 409, published.json()
    assert "requires Reactivation Review" in published.json()["detail"]


def test_research_profile_publish_persists_hash_bound_reactivation_choice(api_client):
    service = api_client.app.state.research_service
    repository = api_client.app.state.repository_root
    profile = service.profile_registry.get("continual-learning")
    disabled = profile.model_copy(update={"enabled": False})
    service.profile_registry = replace(
        service.profile_registry,
        profiles=tuple(
            disabled if item.id == profile.id else item
            for item in service.profile_registry.profiles
        ),
    )
    query = service.query_builder.build(disabled)[0]
    stale = service.now() - timedelta(days=90)
    with open_test_runtime(api_client) as connection:
        search_repository = ResearchSearchRepository(connection)
        search_repository.record_attempt(
            profile.id,
            query.lens_id,
            "arxiv",
            query.query_key,
            query.text,
            stale.isoformat(),
        )
        search_repository.complete_slice(
            profile.id,
            query.lens_id,
            "arxiv",
            query.query_key,
            stale.isoformat(),
            stale.isoformat(),
        )

    profile_path = repository / "config" / "research" / "profiles" / "continual-learning.yaml"
    candidate = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    candidate["title"] = "Durable Reactivation Choice Test"
    created = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "research_profile",
            "entity_id": profile.id,
            "content": yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True),
        },
    )
    assert created.status_code == 201, created.json()
    draft = created.json()["draft"]

    published = api_client.post(
        "/api/publish",
        json={
            "draft_id": draft["id"],
            "expected_revision": draft["revision"],
            "reactivation_strategy": "last_window",
        },
    )

    assert published.status_code == 200, published.json()
    canonical_hash = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    with open_test_runtime(api_client) as connection:
        choice = ResearchControlEventRepository(
            connection
        ).latest_reactivation_choice(profile.id)
        state = ResearchSearchRepository(connection).get_state(
            profile.id, query.lens_id, "arxiv", query.query_key
        )

    assert choice is not None
    assert choice["payload"] == {
        "profile_content_hash": canonical_hash,
        "strategy": "last_window",
        "catchup_days": candidate["search"]["max_catchup_days"],
    }
    assert state is not None and state.completed_through == stale.isoformat()


def test_publishing_source_refreshes_research_screening_registry(api_client):
    content = (
        "schema_version: 1\nid: source-beta\ntype: web\ntitle: Source Beta\n"
        "url: https://example.test/source-beta\n"
    )
    created = api_client.post(
        "/api/drafts",
        json={"entity_type": "source", "entity_id": "source-beta", "content": content},
    )
    assert created.status_code == 201, created.json()
    draft = created.json()["draft"]

    published = api_client.post(
        "/api/publish",
        json={"draft_id": draft["id"], "expected_revision": draft["revision"]},
    )

    assert published.status_code == 200, published.json()
    source = api_client.app.state.research_service.screening.sources.get("source-beta")
    assert source is not None and source.title == "Source Beta"


def test_collection_api_resolves_tree_navigation_unfiled_and_progress(api_client):
    repository = api_client.app.state.repository_root
    collections_root = repository / "knowledge" / "collections"
    collections_root.mkdir(parents=True, exist_ok=True)
    collection_path = collections_root / "reading.yaml"
    collection_path.write_text(
        "schema_version: 1\nid: reading\ntitle: Reading\ndescription: A reading path\n"
        "status: active\nposition: 2\nnodes:\n"
        "  - id: foundations\n    kind: section\n    title: Foundations\n"
        "    children:\n      - id: note-node\n        kind: entity\n"
        "        entity_type: document\n        entity_id: neural-indexing\n"
        "      - id: term-node\n        kind: entity\n"
        "        entity_type: term\n        entity_id: neural-indexing\n",
        encoding="utf-8",
    )
    archived_path = collections_root / "archived-reading.yaml"
    archived_path.write_text(
        "schema_version: 1\nid: archived-reading\ntitle: Archived Reading\n"
        "status: archived\nposition: 1\nnodes: []\n",
        encoding="utf-8",
    )
    connection = connect_database(api_client.app.state.database_path)
    try:
        indexer = Indexer(repository, connection)
        indexer.update_path(collection_path)
        indexer.update_path(archived_path)
    finally:
        connection.close()

    assert [item["id"] for item in api_client.get("/api/collections").json()] == ["reading"]
    assert [item["id"] for item in api_client.get(
        "/api/collections", params={"status": "archived"}
    ).json()] == ["archived-reading"]
    assert [item["id"] for item in api_client.get("/api/library/unfiled").json()] == []

    detail = api_client.get("/api/collections/reading")
    assert detail.status_code == 200
    section = detail.json()["nodes"][0]
    assert section["title"] == "Foundations"
    assert [(node["entity_type"], node["title"]) for node in section["children"]] == [
        ("document", "Neural Indexing"),
        ("term", "Neural Indexing"),
    ]

    navigation = api_client.get(
        "/api/collections/reading/navigation",
        params={"entity_type": "document", "entity_id": "neural-indexing"},
    )
    assert navigation.status_code == 200
    assert navigation.json()["breadcrumbs"] == ["Foundations"]
    assert navigation.json()["previous"] is None
    assert navigation.json()["next"]["entity_type"] == "term"
    assert navigation.json()["next"]["entity_id"] == "neural-indexing"

    progress = api_client.put(
        "/api/collections/reading/progress/neural-indexing", json={"status": "reading"}
    )
    assert progress.status_code == 200
    assert progress.json()["status"] == "reading"
    updated_detail = api_client.get("/api/collections/reading").json()
    assert updated_detail["nodes"][0]["children"][0]["progress"] == "reading"
    assert api_client.put(
        "/api/collections/reading/progress/missing-note", json={"status": "done"}
    ).status_code == 422
    assert api_client.get("/api/collections/missing-collection").status_code == 404


def test_source_pdf_open_is_confined_to_valid_attached_papers(api_client):
    root = api_client.app.state.repository_root
    source_path = root / "knowledge" / "sources" / "source-alpha.yaml"
    pdf_path = root / "storage" / "papers" / "source-alpha.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\nlocal test fixture\n")
    assert api_client.get("/api/sources/source-alpha/pdf").status_code == 404

    source_text = source_path.read_text(encoding="utf-8")
    source_text = source_text.replace(
        "metadata_review:",
        "attachments:\n  local_pdf: storage://papers/source-alpha.pdf\nmetadata_review:",
    )
    source_path.write_text(source_text, encoding="utf-8")
    connection = connect_database(api_client.app.state.database_path)
    try:
        Indexer(root, connection).update_path(source_path)
    finally:
        connection.close()

    opened = api_client.get("/api/sources/source-alpha/pdf")
    assert opened.status_code == 200
    assert opened.headers["content-type"] == "application/pdf"
    assert opened.headers["content-disposition"].startswith("inline;")
    assert opened.content.startswith(b"%PDF-")

    unrelated_pdf = root / "storage" / "papers" / "source-beta.pdf"
    unrelated_pdf.write_bytes(b"%PDF-1.4\nunrelated Source PDF")
    mismatched_source = source_text.replace(
        "storage://papers/source-alpha.pdf",
        "storage://papers/source-beta.pdf",
    )
    source_path.write_text(mismatched_source, encoding="utf-8")
    connection = connect_database(api_client.app.state.database_path)
    try:
        Indexer(root, connection).update_path(source_path)
    finally:
        connection.close()
    assert api_client.get("/api/sources/source-alpha/pdf").status_code == 404

    source_path.write_text(
        source_text.replace(
            "storage://papers/source-alpha.pdf",
            "storage://papers/../../uploads/private.pdf",
        ),
        encoding="utf-8",
    )
    connection = connect_database(api_client.app.state.database_path)
    try:
        Indexer(root, connection).update_path(source_path)
    finally:
        connection.close()
    assert api_client.get("/api/sources/source-alpha/pdf").status_code == 404


def test_ai_endpoints_disclose_provider_and_store_only_valid_proposals(api_client):
    document = api_client.get("/api/documents/neural-indexing").json()
    draft_response = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "document",
            "entity_id": "neural-indexing",
            "content": _document_content(),
        },
    )
    assert draft_response.status_code == 201
    draft = draft_response.json()["draft"]

    # AI calls are disabled without a configured server key and never fall back to networkless output.
    assert api_client.post(
        "/api/ai/document-review", json={"draft_id": draft["id"]}
    ).status_code == 422
    unavailable = api_client.post(
        "/api/ai/document-review",
        json={"draft_id": draft["id"], "confirm_deepseek_transfer": True},
    )
    assert unavailable.status_code == 503, unavailable.json()

    api_client.app.state.ai_proposal_service = AIProposalService(
        api_client.app.state.repository_root,
        api_client.app.state.draft_service,
        api_client.app.state.proposal_service,
        AIGateway(
            MockDeepSeekClient(
                {
                    "review_document": {"summary": "Review complete", "findings": []},
                    "review_format_semantics": {"summary": "Selection reviewed", "findings": []},
                    "draft_term": {
                        "id": "api-term",
                        "title": "API Term",
                        "type": "concept",
                        "depth": "stub",
                        "aliases": [],
                        "definition": "A Term created through the API.",
                    },
                    "suggest_evidence": {
                        "candidates": [
                            {
                                "source_id": "source-alpha",
                                "claim": "A stable index retains canonical facts",
                                "rationale": "The Source title is relevant to the Draft claim.",
                            }
                        ]
                    },
                }
            )
        ),
    )
    generated = api_client.post(
        "/api/ai/document-review",
        json={"draft_id": draft["id"], "confirm_deepseek_transfer": True},
    )
    assert generated.status_code == 201
    result = generated.json()
    assert "DeepSeek" in result["external_provider_notice"]
    assert result["proposal"]["provider"] == "mock"
    assert result["proposal"]["payload"]["task"] == "review_document"

    selected = api_client.post(
        "/api/ai/selection-review",
        json={
            "draft_id": draft["id"],
            "selection": "A stable index",
            "confirm_deepseek_transfer": True,
        },
    )
    assert selected.status_code == 201
    assert selected.json()["proposal"]["kind"] == "format"

    evidence = api_client.post(
        "/api/ai/evidence-suggest",
        json={"draft_id": draft["id"], "confirm_deepseek_transfer": True},
    )
    assert evidence.status_code == 201
    candidate = evidence.json()["proposal"]["payload"]["result"]["candidates"][0]
    assert candidate["source_id"] == "source-alpha"
    assert "locator" not in candidate
    assert "quote" not in candidate

    proposal_id = result["proposal"]["id"]
    assert not any(
        path.endswith(("/approve", "/merge"))
        for path in api_client.app.openapi()["paths"]
    )

    stale_draft = api_client.post(
        "/api/drafts",
        json={"entity_type": "document", "entity_id": "neural-indexing", "content": _document_content()},
    ).json()["draft"]
    stale_proposal = api_client.post(
        "/api/ai/document-review",
        json={"draft_id": stale_draft["id"], "confirm_deepseek_transfer": True},
    ).json()["proposal"]
    changed = api_client.put(
        "/api/drafts/{}".format(stale_draft["id"]),
        json={"content": stale_draft["content"] + "\nA revision.\n", "expected_revision": 1},
    )
    assert changed.status_code == 200
    conflict = api_client.post(
        "/api/proposals/{}/apply".format(stale_proposal["id"]),
        json={"draft_id": stale_draft["id"], "expected_draft_revision": changed.json()["revision"]},
    )
    assert conflict.status_code == 409
    assert api_client.get("/api/proposals/{}".format(stale_proposal["id"])).json()["status"] == "stale"

    term_draft = api_client.post(
        "/api/drafts",
        json={"entity_type": "term", "entity_id": "api-term", "content": _term_draft_content()},
    ).json()["draft"]
    term_proposal = api_client.post(
        "/api/ai/term-draft",
        json={"draft_id": term_draft["id"], "confirm_deepseek_transfer": True},
    )
    assert term_proposal.status_code == 201
    proposal_id = term_proposal.json()["proposal"]["id"]
    applied = api_client.post(
        "/api/proposals/{}/apply".format(proposal_id),
        json={"draft_id": term_draft["id"], "expected_draft_revision": term_draft["revision"]},
    )
    assert applied.status_code == 200, applied.json()
    assert applied.json()["proposal"]["status"] == "drafted"
    merged = api_client.post(
        "/api/publish",
        json={"draft_id": term_draft["id"], "expected_revision": applied.json()["draft"]["revision"]},
    )
    assert merged.status_code == 200
    assert api_client.get("/api/proposals/{}".format(proposal_id)).json()["status"] == "merged"
    assert (api_client.app.state.repository_root / "knowledge/terms/api-term.md").is_file()


def test_apply_proposal_api_checks_draft_revision_and_publish_closes_proposal(api_client):
    base = _document_content("apply-target", "Before Apply")
    candidate = _document_content("apply-target", "Applied Candidate")
    draft_response = api_client.post(
        "/api/drafts",
        json={"entity_type": "document", "entity_id": "apply-target", "content": base},
    )
    assert draft_response.status_code == 201, draft_response.json()
    draft = draft_response.json()["draft"]
    proposal_connection = connect_database(api_client.app.state.database_path)
    try:
        proposal = ProposalService(ProposalRepository(proposal_connection)).create(
            "document",
            "apply-target",
            "document_revision",
            hashlib.sha256(base.encode("utf-8")).hexdigest(),
            {"draft_id": draft["id"], "content": candidate},
            "ai",
        )
    finally:
        proposal_connection.close()
    path = "/api/proposals/{}/apply".format(proposal.id)

    stale_revision = api_client.post(
        path,
        json={"draft_id": draft["id"], "expected_draft_revision": 2},
    )
    assert stale_revision.status_code == 409
    assert api_client.get("/api/proposals/{}".format(proposal.id)).json()["status"] == "proposed"
    assert api_client.get("/api/drafts/{}".format(draft["id"])).json()["content"] == base

    applied = api_client.post(
        path,
        json={"draft_id": draft["id"], "expected_draft_revision": 1},
    )
    assert applied.status_code == 200, applied.json()
    assert applied.json()["proposal"]["status"] == "drafted"
    assert applied.json()["draft"]["revision"] == 2
    assert applied.json()["draft"]["content"] == candidate

    published = api_client.post(
        "/api/publish",
        json={"draft_id": draft["id"], "expected_revision": 2},
    )
    assert published.status_code == 200, published.json()
    assert api_client.get("/api/proposals/{}".format(proposal.id)).json()["status"] == "merged"


def test_draft_publish_usage_and_import_routes(api_client, tmp_path):
    opened = api_client.post(
        "/api/usage/document-open", json={"document_id": "neural-indexing"}
    )
    assert opened.status_code == 201
    clicked = api_client.post(
        "/api/usage/search-click", json={"document_id": "neural-indexing"}
    )
    assert clicked.status_code == 201
    assert api_client.get("/api/usage/recent").json()[0]["entity_id"] == "neural-indexing"
    assert api_client.get("/api/usage/frequent").json()[0]["search_click_count"] == 1

    blank = api_client.post(
        "/api/imports/blank-document",
        json={"title": "API Draft", "entity_id": "api-draft"},
    )
    assert blank.status_code == 201
    draft = blank.json()
    preflight = api_client.get("/api/drafts/{}/preflight".format(draft["id"]))
    assert preflight.status_code == 200
    assert preflight.json()["valid"] is True
    assert not (
        api_client.app.state.repository_root
        / "knowledge/documents/learning/api-draft.md"
    ).exists()
    published = api_client.post(
        "/api/publish",
        json={"draft_id": draft["id"], "expected_revision": draft["revision"]},
    )
    assert published.status_code == 200
    assert published.json()["entity_id"] == "api-draft"
    assert "path" not in published.json()
    published_path = api_client.app.state.repository_root / "knowledge/documents/learning/api-draft.md"
    assert published_path.is_file()
    assert api_client.get("/api/drafts/{}".format(draft["id"])).status_code == 404

    uploads = api_client.app.state.repository_root / "storage" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    import_path = uploads / "staged.md"
    import_path.write_text(_document_content("staged-note", "Staged Note"), encoding="utf-8")
    staged = api_client.post("/api/imports", json={"paths": ["staged.md"]})
    assert staged.status_code == 201
    job = staged.json()
    item = job["items"][0]
    assert "path" not in item
    assert "staging_path" not in item["metadata"]
    item_content = api_client.get(
        "/api/import-items/{}/content".format(item["id"])
    )
    assert item_content.status_code == 200
    assert item_content.json()["content"] == import_path.read_text(encoding="utf-8")
    assert "staging_path" not in item_content.json()["metadata"]
    assert api_client.get("/api/imports/{}".format(job["id"])).status_code == 200
    assert api_client.get("/api/imports").json()[0]["id"] == job["id"]
    created_draft = api_client.post(
        "/api/import-items/{}/draft".format(item["id"])
    )
    assert created_draft.status_code == 201

    pdf_path = uploads / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test PDF\n")
    pdf_job = api_client.post("/api/imports", json={"paths": ["source.pdf"]}).json()
    pdf_item = pdf_job["items"][0]
    source_draft = api_client.post(
        "/api/import-items/{}/confirm-source".format(pdf_item["id"]),
        json={"title": "Imported PDF"},
    )
    assert source_draft.status_code == 201, source_draft.json()
    assert source_draft.json()["entity_type"] == "source"
    assert (api_client.app.state.repository_root / "storage/papers/imported-pdf.pdf").is_file()
    blocked = api_client.post("/api/imports", json={"paths": ["../../knowledge/private.md"]})
    assert blocked.status_code == 422


def test_batch_publish_api_publishes_document_and_collection_in_one_commit(api_client):
    document = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "document",
            "entity_id": "batch-api-note",
            "content": _document_content("batch-api-note", "Batch API Note"),
        },
    )
    assert document.status_code == 201, document.json()
    collection_content = (
        "schema_version: 1\nid: api-reading\ntitle: API Reading\n"
        "status: active\nposition: 0\nnodes:\n"
        "  - id: batch-api-note\n    kind: entity\n"
        "    entity_type: document\n    entity_id: batch-api-note\n"
    )
    collection = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "collection",
            "entity_id": "api-reading",
            "content": collection_content,
        },
    )
    assert collection.status_code == 201, collection.json()

    published = api_client.post(
        "/api/publish/batch",
        json={
            "drafts": [
                {
                    "draft_id": document.json()["draft"]["id"],
                    "expected_revision": document.json()["draft"]["revision"],
                },
                {
                    "draft_id": collection.json()["draft"]["id"],
                    "expected_revision": collection.json()["draft"]["revision"],
                },
            ]
        },
    )

    assert published.status_code == 200, published.json()
    body = published.json()
    assert [item["entity_id"] for item in body["results"]] == [
        "batch-api-note",
        "api-reading",
    ]
    assert all(
        item["commit_revision"] == body["commit_revision"] for item in body["results"]
    )
    assert body["warnings"] == []
    assert api_client.get(
        "/api/drafts/{}".format(document.json()["draft"]["id"])
    ).status_code == 404
    assert api_client.get(
        "/api/drafts/{}".format(collection.json()["draft"]["id"])
    ).status_code == 404


def test_batch_preflight_api_accepts_document_and_collection_drafts(api_client):
    document = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "document",
            "entity_id": "preflight-api-note",
            "content": _document_content("preflight-api-note", "Preflight API Note"),
        },
    )
    assert document.status_code == 201, document.json()
    collection = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "collection",
            "entity_id": "preflight-api-reading",
            "content": (
                "schema_version: 1\nid: preflight-api-reading\n"
                "title: Preflight API Reading\nstatus: active\nposition: 0\nnodes:\n"
                "  - id: preflight-api-note\n    kind: entity\n"
                "    entity_type: document\n    entity_id: preflight-api-note\n"
            ),
        },
    )
    assert collection.status_code == 201, collection.json()

    response = _preflight_batch(api_client, document, collection)

    assert response.status_code == 200, response.json()
    assert [item["entity_id"] for item in response.json()["results"]] == [
        "preflight-api-note",
        "preflight-api-reading",
    ]
    assert all(item["valid"] for item in response.json()["results"])


def test_batch_preflight_api_accepts_source_document_and_collection_drafts(api_client):
    source_id = "preflight-api-source"
    source = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "source",
            "entity_id": source_id,
            "content": (
                "schema_version: 1\nid: preflight-api-source\ntype: paper\n"
                "title: Preflight API Source\nauthors:\n  - Example Author\nyear: 2025\n"
            ),
        },
    )
    assert source.status_code == 201, source.json()
    document = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "document",
            "entity_id": "preflight-api-source-note",
            "content": _document_content(
                "preflight-api-source-note", "Preflight API Source Note"
            ).replace("source-alpha", source_id),
        },
    )
    assert document.status_code == 201, document.json()
    collection = api_client.post(
        "/api/drafts",
        json={
            "entity_type": "collection",
            "entity_id": "preflight-api-source-reading",
            "content": (
                "schema_version: 1\nid: preflight-api-source-reading\n"
                "title: Preflight API Source Reading\nstatus: active\n"
                "position: 0\nnodes:\n  - id: preflight-api-source-note\n"
                "    kind: entity\n    entity_type: document\n"
                "    entity_id: preflight-api-source-note\n"
            ),
        },
    )
    assert collection.status_code == 201, collection.json()

    response = _preflight_batch(api_client, source, document, collection)

    assert response.status_code == 200, response.json()
    assert [item["entity_id"] for item in response.json()["results"]] == [
        "preflight-api-source",
        "preflight-api-source-note",
        "preflight-api-source-reading",
    ]
    assert all(item["valid"] for item in response.json()["results"])


def test_publish_api_rejects_draft_changed_after_review(api_client):
    created = api_client.post(
        "/api/imports/blank-document",
        json={"title": "Reviewed API Draft", "entity_id": "reviewed-api-draft"},
    )
    assert created.status_code == 201
    reviewed = created.json()
    changed = api_client.put(
        "/api/drafts/{}".format(reviewed["id"]),
        json={
            "content": reviewed["content"].replace("# Reviewed API Draft", "# Changed API Draft"),
            "expected_revision": reviewed["revision"],
        },
    )
    assert changed.status_code == 200
    repository = api_client.app.state.repository_root
    target = repository / "knowledge/documents/learning/reviewed-api-draft.md"
    current_commit = api_client.app.state.git_manager.current_revision()

    stale_publish = api_client.post(
        "/api/publish",
        json={"draft_id": reviewed["id"], "expected_revision": reviewed["revision"]},
    )

    assert stale_publish.status_code == 409
    assert "Refresh the Publish Review" in stale_publish.json()["detail"]
    assert not target.exists()
    assert api_client.app.state.git_manager.current_revision() == current_commit
    assert api_client.get("/api/drafts/{}".format(reviewed["id"])).json()["revision"] == reviewed["revision"] + 1


def test_browser_upload_stages_multiple_markdown_and_pdf_files(api_client):
    repository = api_client.app.state.repository_root
    original_revision = api_client.app.state.git_manager.current_revision()
    markdown_content = _document_content("browser-note", "Browser Note").encode("utf-8")
    files = [
        ("files[]", ("browser-note.md", markdown_content, "text/markdown")),
        ("files[]", ("browser-note.pdf", b"%PDF-1.7\nsource attachment", "application/pdf")),
    ]

    response = api_client.post(
        "/api/imports/upload",
        data={"profile": "legacy"},
        files=files,
    )

    assert response.status_code == 201, response.json()
    job = response.json()
    assert job["status"] == "ready"
    assert job["profile"] == "legacy"
    assert {item["display_name"] for item in job["items"]} == {
        "browser-note.md",
        "browser-note.pdf",
    }
    assert {item["file_type"] for item in job["items"]} == {"markdown", "pdf"}
    assert len(job["items"]) == 2

    connection = connect_database(api_client.app.state.database_path)
    try:
        rows = connection.execute(
            "SELECT path, file_type, metadata_json FROM import_items WHERE job_id = ?",
            (job["id"],),
        ).fetchall()
    finally:
        connection.close()
    assert all(not Path(row["path"]).exists() for row in rows)
    markdown_item = next(row for row in rows if row["file_type"] == "markdown")
    markdown_metadata = json.loads(markdown_item["metadata_json"])
    staged_markdown = repository / markdown_metadata["staging_path"]
    assert staged_markdown.read_text(encoding="utf-8") == markdown_content.decode("utf-8")
    assert markdown_metadata["profile"] == "legacy"
    browser_uploads = repository / "storage" / "uploads" / "browser"
    assert not list(browser_uploads.iterdir())
    assert api_client.app.state.git_manager.current_revision() == original_revision
    assert not (repository / "knowledge" / "documents" / "learning" / "browser-note.md").exists()
    assert not (repository / "knowledge" / "sources" / "browser-note.yaml").exists()
    assert not (repository / "storage" / "papers" / "browser-note.pdf").exists()

    standard = api_client.post(
        "/api/imports/upload",
        data={"profile": "standard"},
        files=[("files[]", ("standard-note.md", _document_content("standard-note", "Standard Note").encode("utf-8"), "text/markdown"))],
    )
    assert standard.status_code == 201, standard.json()
    assert standard.json()["profile"] == "standard"
    assert standard.json()["items"][0]["metadata"]["profile"] == "standard"
    assert not list(browser_uploads.iterdir())

    rejected = api_client.post(
        "/api/imports/upload",
        data={"profile": "standard"},
        files=[("files[]", ("unsupported.txt", b"text", "text/plain"))],
    )
    assert rejected.status_code == 422
    assert not list(browser_uploads.iterdir())


def test_research_profile_controls_manual_queue_runs_and_candidate_actions(
    api_client, tmp_path, request
):
    api_service = api_client.app.state.research_service
    profile_id = "continual-learning"
    profile = api_service.profile_registry.get(profile_id)
    assert profile is not None

    # TestClient owns the app connection on its lifespan thread. Keep all
    # test-side repository reads and writes on a separate connection created
    # by this pytest thread.
    test_connection = connect_database(api_client.app.state.database_path)
    request.addfinalizer(test_connection.close)
    service, _, _, _ = _service(
        tmp_path, test_connection, FakeProvider([]), profile=profile
    )

    profiles = api_client.get("/api/research/profiles")
    assert profiles.status_code == 200
    assert profiles.json()[0]["id"] == profile_id
    assert profiles.json()[0]["inbox"] == {
        "new_count": 0,
        "capacity": profile.inbox.max_new_candidates,
        "remaining": profile.inbox.max_new_candidates,
    }
    detail = api_client.get("/api/research/profiles/{}".format(profile_id))
    assert detail.status_code == 200
    assert detail.json()["profile"]["lenses"][0]["id"] == "regularization"

    assert api_client.post(
        "/api/research/profiles/{}/pause".format(profile_id),
        json={"days": 3, "until": "2026-10-08T00:00:00Z"},
    ).status_code == 422
    paused = api_client.post(
        "/api/research/profiles/{}/pause".format(profile_id), json={"days": 3}
    )
    assert paused.status_code == 200
    assert paused.json()["runtime_state"]["paused_until"]
    resumed = api_client.post(
        "/api/research/profiles/{}/resume".format(profile_id),
        json={"strategy": "from_now"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["watermark_skipped"] is True
    assert service.control_event_repository.latest_resume(profile_id)["payload"]["strategy"] == "from_now"

    queued = api_client.post(
        "/api/research/profiles/{}/runs".format(profile_id),
        json={
            "lenses": ["regularization"],
            "breadth": "explore",
            "date_range": {"mode": "last_7_days"},
            "additional_queries": ["dynamic fisher continual learning"],
        },
    )
    assert queued.status_code == 202, queued.json()
    request_id = queued.json()["request_id"]
    assert queued.json()["status"] == "pending"
    request_row = service.run_request_repository.get(request_id)
    assert request_row is not None and request_row.status == "pending"
    assert request_row.override["breadth"] == "explore"
    assert request_row.override["additional_queries"] == ["dynamic fisher continual learning"]
    assert api_client.get("/api/research/runs").json()["count"] == 0

    query = service.query_builder.build(profile)[0]
    ingested = service.deduplicator.record_discovery(
        profile_id,
        query.lens_id,
        query.query_key,
        query.text,
        ProviderWork(
            provider="arxiv",
            provider_record_id="2501.01234",
            title="A Research API Candidate",
            abstract="A concrete abstract for the research candidate.",
            authors=("Example Author",),
            year=2026,
            arxiv_id="2501.01234",
        ),
        discovered_at=service.now(),
    )
    analysis_output = ResearchCandidateAnalysisOutput.model_validate(
        {
            "relevant": True,
            "profile_relevance": 0.9,
            "knowledge_relevance": 0.8,
            "novelty_to_library": 0.7,
            "matched_lenses": [query.lens_id],
            "matched_topics": ["continual learning"],
            "summary": "A concise analysis summary.",
            "why_relevant": "It matches the Profile's Research Lens.",
            "reading_reason": "It may provide a useful method comparison.",
            "existing_relations": [
                {
                    "entity_type": "document",
                    "entity_id": "neural-indexing",
                    "relation": "related",
                    "reason": "Both concern parameter importance.",
                }
            ],
        }
    )
    analysis = ResearchWorkAnalysisRecord(
        id="api-analysis",
        work_id=ingested.work.id,
        profile_id=profile_id,
        input_hash="api-analysis-hash",
        outcome="surface",
        analysis=analysis_output,
        provider="mock",
        model="mock",
        prompt_version="research-candidate-analysis-v1",
        analysis_version=1,
        context_entity_ids=("document:neural-indexing",),
        analyzed_at=service.now().isoformat(),
    )
    analysis, _ = service.work_repository.add_analysis_if_missing(analysis)
    generated = service.candidate_service.generate(analysis, profile, profile.lenses[0])
    candidate_id = generated.candidate.id

    candidate_page = api_client.get(
        "/api/research/candidates",
        params={"profile_id": profile_id, "status": "new", "sort": "recommended"},
    )
    assert candidate_page.status_code == 200, candidate_page.json()
    assert candidate_page.json()["count"] == 1
    assert candidate_page.json()["candidates"][0]["work"]["id"] == ingested.work.id
    candidate_detail = api_client.get(
        "/api/research/candidates/{}".format(candidate_id)
    )
    assert candidate_detail.status_code == 200, candidate_detail.json()
    assert candidate_detail.json()["knowledge_relations"][0]["entity_id"] == "neural-indexing"
    assert candidate_detail.json()["candidate"]["first_viewed_at"]

    shortlist = api_client.post(
        "/api/research/candidates/{}/shortlist".format(candidate_id),
        json={"note": "Read after the current review batch."},
    )
    assert shortlist.status_code == 200
    assert shortlist.json()["status"] == "shortlisted"
    dismissed = api_client.post(
        "/api/research/candidates/{}/dismiss".format(candidate_id),
        json={"reason": "too_redundant", "note": "Already covered in my notes."},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    assert dismissed.json()["dismiss_reason"] == "too_redundant"


def _create_repository(root: Path) -> Path:
    repository = root
    (repository / "config").mkdir(parents=True)
    shutil.copytree(_ROOT / "config", repository / "config", dirs_exist_ok=True)
    (repository / "knowledge").mkdir()
    shutil.copytree(
        _ROOT / "knowledge" / "taxonomy",
        repository / "knowledge" / "taxonomy",
    )
    (repository / "knowledge" / "documents" / "learning").mkdir(parents=True, exist_ok=True)
    (repository / "knowledge" / "terms").mkdir(parents=True, exist_ok=True)
    (repository / "knowledge" / "sources").mkdir(parents=True, exist_ok=True)
    (repository / "storage" / "uploads").mkdir(parents=True, exist_ok=True)
    (repository / "knowledge" / "taxonomy" / "topics.yaml").write_text(
        "schema_version: 1\nentries:\n  - id: graph-search\n    title: Graph Search\n",
        encoding="utf-8",
    )
    (repository / "knowledge" / "sources" / "source-alpha.yaml").write_text(
        "schema_version: 1\nid: source-alpha\ntype: paper\ntitle: Source Alpha\n"
        "authors:\n  - Example Author\nyear: 2024\nmetadata_review:\n  status: verified\n",
        encoding="utf-8",
    )
    term = (
        "---\nschema_version: 1\nid: neural-indexing\ntitle: Neural Indexing\n"
        "type: concept\ndepth: standard\naliases:\n  - Calibrated Optimizer\n"
        "domains: []\ntopics: []\ntags: []\nsources: []\n"
        "review:\n  human:\n    status: approved\n---\n# Neural Indexing\n\nA term definition.\n"
    )
    (repository / "knowledge" / "terms" / "neural-indexing.md").write_text(term, encoding="utf-8")
    (repository / "knowledge" / "documents" / "learning" / "neural-indexing.md").write_text(
        _document_content(), encoding="utf-8"
    )
    research_profile_path = (
        repository / "config" / "research" / "profiles" / "continual-learning.yaml"
    )
    research_profile = yaml.safe_load(research_profile_path.read_text(encoding="utf-8"))
    research_profile["context"]["documents"] = []
    research_profile_path.write_text(
        yaml.safe_dump(research_profile, sort_keys=False), encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.name", "API Tests"], cwd=repository, check=True)
    subprocess.run(["git", "config", "user.email", "api-tests@example.com"], cwd=repository, check=True)
    subprocess.run(["git", "add", "config", "knowledge"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repository, check=True)
    return repository


def _document_content(entity_id="neural-indexing", title="Neural Indexing"):
    return (
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: learning-note\n"
        "domains: []\ntopics: []\ntags: []\nsources:\n  - source-alpha\n"
        "review:\n  human:\n    status: approved\n"
        "maintenance:\n  status: current\n---\n"
        "# {}\n\nA stable index retains canonical facts [@source-alpha, Sec. 2].\n"
        "See [[Calibrated Optimizer]] and [[Missing Term]].\n"
    ).format(entity_id, title, title)


def _preflight_batch(api_client, *draft_responses):
    return api_client.post(
        "/api/publish/preflight-batch",
        json={
            "drafts": [
                {
                    "draft_id": response.json()["draft"]["id"],
                    "expected_revision": response.json()["draft"]["revision"],
                }
                for response in draft_responses
            ]
        },
    )


def _term_draft_content():
    return (
        "---\nschema_version: 1\nid: api-term\ntitle: API Term\ntype: concept\n"
        "depth: stub\naliases: []\ndomains: []\ntopics: []\ntags: []\nsources: []\n"
        "---\n# API Term\n\nDraft definition.\n"
    )
