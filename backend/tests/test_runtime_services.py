import sqlite3
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.app.db.connection import connect_database
from backend.app.repositories.draft_repository import (
    DraftNotFoundError,
    DraftRepository,
    DraftRevisionConflict,
)
from backend.app.repositories.proposal_repository import (
    ProposalRepository,
    ProposalTransitionError,
)
from backend.app.services.draft_service import DraftService
from backend.app.services.proposal_service import (
    ProposalService,
    StaleProposalError,
)


@pytest.fixture
def runtime_connection():
    connection = connect_database(":memory:")
    yield connection
    connection.close()


def test_runtime_schema_contains_runtime_and_derived_index_tables(runtime_connection):
    tables = {
        row[0]
        for row in runtime_connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert {
        "drafts",
        "proposals",
        "rejected_candidates",
        "document_index",
        "term_index",
        "source_index",
        "collection_index",
        "collection_node_index",
        "collection_progress",
        "alias_index",
        "taxonomy_index",
        "backlink_index",
        "evidence_index",
        "usage_events",
        "document_stats",
        "import_jobs",
        "import_items",
        "document_fts",
        "term_fts",
        "source_fts",
        "evidence_fts",
    } <= tables
    assert runtime_connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert runtime_connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'drafts_target_unique_idx'"
    ).fetchone() is not None


def test_runtime_data_persists_when_database_is_reopened(tmp_path):
    database_path = tmp_path / "runtime" / "knowledge.db"
    connection = connect_database(database_path)
    draft = DraftService(DraftRepository(connection)).create(
        "document", "note", "draft", "git-rev-a", "content-hash-a"
    )
    connection.close()

    reopened = connect_database(database_path)
    try:
        loaded = DraftRepository(reopened).get(draft.id)
        assert loaded.content == "draft"
        assert loaded.revision == 1
    finally:
        reopened.close()


def test_draft_create_and_autosave_keep_canonical_file_untouched(tmp_path, runtime_connection):
    canonical = tmp_path / "knowledge" / "documents" / "papers" / "note.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("published content", encoding="utf-8")
    repository = DraftRepository(runtime_connection)
    service = DraftService(repository)

    draft = service.create(
        "document", "note", "first draft", "git-rev-a", "content-hash-a"
    )
    saved = service.save(draft.id, "edited draft", expected_revision=1)

    assert draft.revision == 1
    assert saved.revision == 2
    assert saved.content == "edited draft"
    assert saved.base_git_revision == "git-rev-a"
    assert saved.base_content_hash == "content-hash-a"
    assert canonical.read_text(encoding="utf-8") == "published content"


def test_create_or_get_returns_existing_draft_without_overwriting_it(runtime_connection):
    service = DraftService(DraftRepository(runtime_connection))
    original_result = service.create_or_get("document", "note", "first", "rev-a", "hash-a")
    existing_result = service.create_or_get("document", "note", "second", "rev-b", "hash-b")
    original = original_result.draft
    existing = existing_result.draft

    assert original_result.created is True
    assert existing_result.created is False
    assert existing.id == original.id
    assert existing.content == "first"
    assert existing.base_git_revision == "rev-a"
    assert len(service.list_for_target("document", "note")) == 1


def test_two_connections_racing_to_create_a_target_return_one_draft(tmp_path):
    database_path = tmp_path / "runtime" / "knowledge.db"
    initialized = connect_database(database_path)
    initialized.close()

    connections = [
        sqlite3.connect(str(database_path), timeout=10, check_same_thread=False)
        for _ in range(2)
    ]
    for connection in connections:
        connection.row_factory = sqlite3.Row
    barrier = Barrier(2)

    def create(connection, content):
        barrier.wait(timeout=5)
        service = DraftService(DraftRepository(connection))
        return service.create_or_get("document", "racing-note", content, "revision", "hash")

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, connections, ["one", "two"]))
        assert results[0].draft.id == results[1].draft.id
        assert sorted(result.created for result in results) == [False, True]
        winner = next(result.draft for result in results if result.created)
        assert DraftRepository(connections[0]).list_for_target("document", "racing-note") == [winner]
    finally:
        for connection in connections:
            connection.close()


def test_draft_rejects_stale_autosave_and_unknown_ids(runtime_connection):
    service = DraftService(DraftRepository(runtime_connection))
    draft = service.create("term", "sgd", "one", "rev-a", "hash-a")
    service.save(draft.id, "two", expected_revision=1)

    with pytest.raises(DraftRevisionConflict, match="expected 1, found 2"):
        service.save(draft.id, "stale write", expected_revision=1)
    with pytest.raises(DraftNotFoundError):
        service.save("missing", "content", expected_revision=1)


def test_proposal_draft_approve_assert_and_merge_follow_state_machine(runtime_connection):
    service = ProposalService(ProposalRepository(runtime_connection))
    proposal = service.create(
        "document",
        "note",
        "document_revision",
        hashlib.sha256(b"# Before\n").hexdigest(),
        {"title": "新标题"},
        "human",
        base_content="# Before\n",
        proposed_content="# After\n",
    )
    assert proposal.status == "proposed"
    assert "-# Before" in proposal.diff_text
    assert "+# After" in proposal.diff_text

    drafted = service.draft(proposal.id, {"title": "更新标题"}, "metadata diff")
    current_hash = hashlib.sha256(b"# Before\n").hexdigest()
    approved = service.approve(proposal.id, current_hash, "reviewed")
    applicable = service.assert_applicable(proposal.id, current_hash)
    merged = service.merge(proposal.id, current_hash)

    assert drafted.status == "drafted"
    assert approved.status == "approved"
    assert applicable.payload == {"title": "更新标题"}
    assert merged.status == "merged"
    assert merged.review_note == "reviewed"


def test_apply_proposal_updates_draft_and_proposal_in_one_lifecycle(runtime_connection):
    drafts = DraftService(DraftRepository(runtime_connection))
    proposals = ProposalService(ProposalRepository(runtime_connection))
    base_content = "# Before\n"
    candidate = "# Candidate\n"
    draft = drafts.create(
        "document", "note", base_content, "rev-a", hashlib.sha256(b"canonical").hexdigest()
    )
    proposal = proposals.create(
        "document",
        "note",
        "document_revision",
        hashlib.sha256(base_content.encode("utf-8")).hexdigest(),
        {"draft_id": draft.id, "content": candidate},
        "ai",
    )

    applied_proposal, applied_draft = proposals.apply_to_draft(
        proposal.id, draft, expected_revision=1
    )

    assert applied_proposal.status == "drafted"
    assert applied_proposal.payload["applied_content_hash"] == hashlib.sha256(
        candidate.encode("utf-8")
    ).hexdigest()
    assert applied_draft.content == candidate
    assert applied_draft.revision == 2


def test_metadata_proposal_applies_changes_without_replacing_markdown_body(runtime_connection):
    drafts = DraftService(DraftRepository(runtime_connection))
    proposals = ProposalService(ProposalRepository(runtime_connection))
    base_content = (
        "---\nschema_version: 1\nid: note\ntitle: Before\ntype: learning-note\n"
        "domains: []\ntopics: []\ntags: []\nsources: []\n---\n# Body\n\nKeep this text.\n"
    )
    draft = drafts.create(
        "document", "note", base_content, "rev-a", hashlib.sha256(b"canonical").hexdigest()
    )
    proposal = proposals.create(
        "document",
        "note",
        "metadata",
        hashlib.sha256(base_content.encode("utf-8")).hexdigest(),
        {"draft_id": draft.id, "result": {"changes": {"title": "After", "tags": ["reviewed"]}}},
        "ai",
    )

    applied_proposal, applied_draft = proposals.apply_to_draft(
        proposal.id, draft, expected_revision=1
    )

    assert applied_proposal.status == "drafted"
    assert "title: After" in applied_draft.content
    assert "reviewed" in applied_draft.content
    assert applied_draft.content.endswith("# Body\n\nKeep this text.\n")


def test_approved_proposal_cannot_be_rejected_after_merge(runtime_connection):
    service = ProposalService(ProposalRepository(runtime_connection))
    proposal = service.create(
        "term", "sgd", "term_revision", hashlib.sha256(b"before").hexdigest(), {}, "human"
    )
    current_hash = hashlib.sha256(b"before").hexdigest()
    service.approve(proposal.id, current_hash)
    service.merge(proposal.id, current_hash)

    with pytest.raises(ProposalTransitionError, match="Cannot reject"):
        service.reject(proposal.id, "too late")


def test_stale_proposal_is_marked_and_cannot_be_approved_or_applied(runtime_connection):
    service = ProposalService(ProposalRepository(runtime_connection))
    proposal = service.create(
        "document", "note", "metadata", hashlib.sha256(b"before").hexdigest(), {"tags": ["ai"]}, "ai"
    )
    changed_hash = hashlib.sha256(b"after").hexdigest()

    with pytest.raises(StaleProposalError):
        service.approve(proposal.id, changed_hash)
    assert service.get(proposal.id).status == "stale"
    with pytest.raises(StaleProposalError):
        service.assert_applicable(proposal.id, changed_hash)
    with pytest.raises(StaleProposalError):
        service.merge(proposal.id, changed_hash)


def test_reject_records_candidate_atomically_and_normalizes_lookup(runtime_connection):
    service = ProposalService(ProposalRepository(runtime_connection))
    proposal = service.create(
        "taxonomy", "learning", "taxonomy", hashlib.sha256(b"before").hexdigest(), {"title": "Bad Topic"}, "ai"
    )
    rejected = service.reject(
        proposal.id,
        "Duplicate concept",
        candidate_type="taxonomy",
        candidate_value="  Bad   Topic ",
        scope="topic",
    )

    assert rejected.status == "rejected"
    assert rejected.review_note == "Duplicate concept"
    assert service.is_rejected_candidate("taxonomy", "bad topic", "topic")
    assert not service.is_rejected_candidate("taxonomy", "bad topic", "domain")


def test_rejected_candidate_upsert_is_idempotent(runtime_connection):
    service = ProposalService(ProposalRepository(runtime_connection))
    first = service.record_rejected_candidate("term", "Bad Term", "not useful")
    second = service.record_rejected_candidate("term", " bad   term ", "duplicate")
    rows = runtime_connection.execute(
        "SELECT COUNT(*) FROM rejected_candidates"
    ).fetchone()[0]

    assert rows == 1
    assert second.id == first.id
    assert second.reason == "duplicate"


def test_proposal_status_constraint_rejects_unknown_state(runtime_connection):
    with pytest.raises(sqlite3.IntegrityError):
        runtime_connection.execute(
            """INSERT INTO proposals (
                id, target_type, target_id, kind, status, base_content_hash,
                payload_json, created_by, created_at
            ) VALUES ('p', 'document', 'd', 'metadata', 'unknown', 'rev', '{}', 'human', 'now')"""
        )
