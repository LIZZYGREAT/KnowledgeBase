import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from backend.app.db.connection import connect_database
from backend.app.main import app
from backend.app.services.ai_client import MockDeepSeekClient
from backend.app.services.ai_gateway import AIGateway
from backend.app.services.ai_proposal_service import AIProposalService
from backend.app.services.indexer import Indexer


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
        "/api/search",
        "/api/taxonomy",
        "/api/review/link-issues",
        "/api/documents/recently-modified",
        "/api/sources/{entity_id}/pdf",
        "/api/context/export",
        "/api/ai/document-review",
        "/api/drafts",
        "/api/drafts/{draft_id}/compare",
        "/api/drafts/{draft_id}/rebase",
        "/api/publish",
    ):
        assert path in schema["paths"]
    context_schema = schema["components"]["schemas"]["ContextExportRequest"]
    assert "provisional traceability filter" in context_schema["properties"]["trust"]["description"]


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
    draft = created.json()
    drafts = api_client.get(
        "/api/drafts", params={"entity_type": "document", "entity_id": "neural-indexing"}
    )
    assert drafts.status_code == 200
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
    draft = draft_response.json()

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
    approved = api_client.post(
        "/api/proposals/{}/approve".format(proposal_id), json={"review_note": "Reviewed"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    stale_draft = api_client.post(
        "/api/drafts",
        json={"entity_type": "document", "entity_id": "neural-indexing", "content": _document_content()},
    ).json()
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
        "/api/proposals/{}/approve".format(stale_proposal["id"]), json={}
    )
    assert conflict.status_code == 409
    assert api_client.get("/api/proposals/{}".format(stale_proposal["id"])).json()["status"] == "stale"

    term_draft = api_client.post(
        "/api/drafts",
        json={"entity_type": "term", "entity_id": "api-term", "content": _term_draft_content()},
    ).json()
    term_proposal = api_client.post(
        "/api/ai/term-draft",
        json={"draft_id": term_draft["id"], "confirm_deepseek_transfer": True},
    )
    assert term_proposal.status_code == 201
    proposal_id = term_proposal.json()["proposal"]["id"]
    assert api_client.post(
        "/api/proposals/{}/approve".format(proposal_id), json={}
    ).json()["status"] == "approved"
    merged = api_client.post("/api/proposals/{}/merge".format(proposal_id))
    assert merged.status_code == 200
    assert api_client.get("/api/proposals/{}".format(proposal_id)).json()["status"] == "merged"
    assert (api_client.app.state.repository_root / "knowledge/terms/api-term.md").is_file()


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
    published = api_client.post("/api/publish", json={"draft_id": draft["id"]})
    assert published.status_code == 200
    assert published.json()["entity_id"] == "api-draft"
    assert "path" not in published.json()
    published_path = api_client.app.state.repository_root / "knowledge/documents/learning/api-draft.md"
    assert published_path.is_file()
    refreshed_draft = api_client.get("/api/drafts/{}".format(draft["id"])).json()
    assert refreshed_draft["base_git_revision"] == published.json()["commit_revision"]
    assert refreshed_draft["base_content_hash"] == hashlib.sha256(published_path.read_bytes()).hexdigest()
    assert refreshed_draft["content"] == published_path.read_text(encoding="utf-8")

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


def _create_repository(root: Path) -> Path:
    repository = root
    (repository / "config").mkdir(parents=True)
    shutil.copytree(_ROOT / "config", repository / "config", dirs_exist_ok=True)
    shutil.copytree(_ROOT / "knowledge", repository / "knowledge", dirs_exist_ok=True)
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


def _term_draft_content():
    return (
        "---\nschema_version: 1\nid: api-term\ntitle: API Term\ntype: concept\n"
        "depth: stub\naliases: []\ndomains: []\ntopics: []\ntags: []\nsources: []\n"
        "---\n# API Term\n\nDraft definition.\n"
    )
