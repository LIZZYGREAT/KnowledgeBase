import sqlite3

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
        "alias_index",
        "taxonomy_index",
        "backlink_index",
        "evidence_index",
        "usage_events",
        "document_stats",
        "document_fts",
        "term_fts",
        "source_fts",
        "evidence_fts",
    } <= tables


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
        "git-rev-a",
        {"title": "新标题"},
        "human",
        base_content="# Before\n",
        proposed_content="# After\n",
    )
    assert proposal.status == "proposed"
    assert "-# Before" in proposal.diff_text
    assert "+# After" in proposal.diff_text

    drafted = service.draft(proposal.id, {"title": "更新标题"}, "metadata diff")
    approved = service.approve(proposal.id, "git-rev-a", "reviewed")
    applicable = service.assert_applicable(proposal.id, "git-rev-a")
    merged = service.merge(proposal.id, "git-rev-a")

    assert drafted.status == "drafted"
    assert approved.status == "approved"
    assert applicable.payload == {"title": "更新标题"}
    assert merged.status == "merged"
    assert merged.review_note == "reviewed"


def test_approved_proposal_cannot_be_rejected_after_merge(runtime_connection):
    service = ProposalService(ProposalRepository(runtime_connection))
    proposal = service.create(
        "term", "sgd", "term_revision", "rev-a", {}, "human"
    )
    service.approve(proposal.id, "rev-a")
    service.merge(proposal.id, "rev-a")

    with pytest.raises(ProposalTransitionError, match="Cannot reject"):
        service.reject(proposal.id, "too late")


def test_stale_proposal_is_marked_and_cannot_be_approved_or_applied(runtime_connection):
    service = ProposalService(ProposalRepository(runtime_connection))
    proposal = service.create(
        "document", "note", "metadata", "rev-a", {"tags": ["ai"]}, "ai"
    )

    with pytest.raises(StaleProposalError):
        service.approve(proposal.id, "rev-b")
    assert service.get(proposal.id).status == "stale"
    with pytest.raises(StaleProposalError):
        service.assert_applicable(proposal.id, "rev-b")
    with pytest.raises(StaleProposalError):
        service.merge(proposal.id, "rev-b")


def test_reject_records_candidate_atomically_and_normalizes_lookup(runtime_connection):
    service = ProposalService(ProposalRepository(runtime_connection))
    proposal = service.create(
        "taxonomy", "learning", "taxonomy", "rev-a", {"title": "Bad Topic"}, "ai"
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
                id, target_type, target_id, kind, status, base_revision,
                payload_json, created_by, created_at
            ) VALUES ('p', 'document', 'd', 'metadata', 'unknown', 'rev', '{}', 'human', 'now')"""
        )
