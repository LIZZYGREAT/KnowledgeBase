import hashlib
import sqlite3

import pytest

from backend.app.db.connection import _SCHEMA_PATH, connect_database
from backend.app.db.migrations import migrate_database
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.proposal_repository import ProposalRepository
from backend.app.services.draft_service import DraftService
from backend.app.services.proposal_service import ProposalService


def test_legacy_runtime_database_migrates_and_preserves_user_state(tmp_path):
    database_path = tmp_path / "runtime" / "knowledge.db"
    database_path.parent.mkdir(parents=True)
    _create_legacy_database(database_path)

    connection = connect_database(database_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'drafts_target_unique_idx'"
        ).fetchone() is not None
        drafts = DraftRepository(connection)
        assert [draft.entity_type for draft in drafts.list_for_target("document", "note")] == [
            "document"
        ]
        assert drafts.get("old-draft").content == "legacy content"
        assert drafts.list_for_target("taxonomy", "topics")[0].content == "legacy taxonomy"

        created = DraftService(drafts).create(
            "collection", "reading", "collection draft", "revision", "hash"
        )
        assert created.entity_type == "collection"
        assert drafts.get(created.id).content == "collection draft"

        assert connection.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM presentation_annotations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM import_jobs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM import_items").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM collection_index").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM collection_node_index").fetchone()[0] == 0

        connection.execute(
            "INSERT INTO collection_progress VALUES (?, ?, ?, ?)",
            ("reading", "note", "reading", "2026-10-02T00:00:00+00:00"),
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO collection_progress VALUES (?, ?, ?, ?)",
                ("reading", "other-note", "unread", "2026-10-02T00:00:00+00:00"),
            )

        with pytest.raises(ValueError, match="Unsupported Proposal target type"):
            ProposalService(ProposalRepository(connection)).create(
                "collection",
                "reading",
                "metadata",
                hashlib.sha256(b"content").hexdigest(),
                {},
                "human",
            )
    finally:
        connection.close()

    reopened = connect_database(database_path)
    try:
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == 3
        assert reopened.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 5
        assert reopened.execute("SELECT COUNT(*) FROM collection_progress").fetchone()[0] == 1
    finally:
        reopened.close()


def test_migration_rejects_a_database_from_a_newer_schema_version():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA user_version = 4")

    with pytest.raises(RuntimeError, match="newer than supported"):
        migrate_database(connection)

    connection.close()


def test_approved_proposals_migrate_to_stale_and_cannot_be_reinserted():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE proposals (
               id TEXT PRIMARY KEY,
               target_type TEXT NOT NULL,
               target_id TEXT NOT NULL,
               kind TEXT NOT NULL,
               status TEXT NOT NULL CHECK (
                   status IN ('proposed', 'drafted', 'approved', 'merged', 'rejected', 'stale')
               ),
               base_content_hash TEXT NOT NULL,
               payload_json TEXT NOT NULL,
               diff_text TEXT,
               created_by TEXT NOT NULL,
               provider TEXT,
               model TEXT,
               created_at TEXT NOT NULL,
               reviewed_at TEXT,
               review_note TEXT
           );
           CREATE INDEX proposals_target_status_idx
               ON proposals (target_type, target_id, status, created_at DESC);
           INSERT INTO proposals (
               id, target_type, target_id, kind, status, base_content_hash,
               payload_json, created_by, created_at, review_note
           ) VALUES (
               'legacy-approved', 'document', 'note', 'metadata', 'approved',
               'hash', '{}', 'human', 'created', 'reviewed'
           );
           PRAGMA user_version = 2;"""
    )

    migrate_database(connection)

    migrated = connection.execute(
        "SELECT status, review_note FROM proposals WHERE id = 'legacy-approved'"
    ).fetchone()
    assert migrated == (
        "stale",
        "Legacy approved Proposal requires re-application under the current Draft workflow.",
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO proposals (
                   id, target_type, target_id, kind, status, base_content_hash,
                   payload_json, created_by, created_at
               ) VALUES ('approved-again', 'document', 'note', 'metadata', 'approved', 'hash', '{}', 'human', 'now')"""
        )
    connection.close()


def test_unique_draft_migration_reports_duplicates_and_keeps_existing_rows():
    connection = connect_database(":memory:")
    connection.execute("DROP INDEX drafts_target_unique_idx")
    connection.executemany(
        """INSERT INTO drafts (
               id, entity_type, entity_id, base_git_revision, base_content_hash,
               content, revision, created_at, updated_at
           ) VALUES (?, 'document', 'duplicate-note', 'revision', 'hash', ?, 1, 'created', ?)""",
        [("draft-newer", "newer", "2026-10-02T02:00:00+00:00"),
         ("draft-older", "older", "2026-10-02T01:00:00+00:00")],
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()

    with pytest.raises(RuntimeError) as error:
        migrate_database(connection)

    message = str(error.value)
    assert "document:duplicate-note" in message
    assert "draft-newer" in message and "draft-older" in message
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM drafts WHERE entity_type = 'document' AND entity_id = 'duplicate-note'"
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'drafts_target_unique_idx'"
    ).fetchone() is None
    connection.close()


def _create_legacy_database(path):
    connection = sqlite3.connect(str(path))
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    connection.execute("DROP TABLE collection_node_index")
    connection.execute("DROP TABLE collection_index")
    connection.execute("DROP TABLE collection_progress")

    connection.execute("DROP INDEX drafts_target_updated_idx")
    connection.execute("ALTER TABLE drafts RENAME TO drafts_with_collection")
    connection.execute(
        """CREATE TABLE drafts (
               id TEXT PRIMARY KEY,
               entity_type TEXT NOT NULL CHECK (
                   entity_type IN ('document', 'term', 'source', 'taxonomy')
               ),
               entity_id TEXT NOT NULL,
               base_git_revision TEXT NOT NULL,
               base_content_hash TEXT NOT NULL,
               content TEXT NOT NULL,
               revision INTEGER NOT NULL CHECK (revision > 0),
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )"""
    )
    connection.execute(
        """INSERT INTO drafts (
               id, entity_type, entity_id, base_git_revision, base_content_hash,
               content, revision, created_at, updated_at
           ) SELECT id, entity_type, entity_id, base_git_revision, base_content_hash,
                    content, revision, created_at, updated_at
             FROM drafts_with_collection"""
    )
    connection.execute("DROP TABLE drafts_with_collection")
    connection.execute(
        """CREATE INDEX drafts_target_updated_idx
           ON drafts (entity_type, entity_id, updated_at DESC)"""
    )
    connection.executemany(
        """INSERT INTO drafts (
               id, entity_type, entity_id, base_git_revision, base_content_hash,
               content, revision, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            ("old-draft", "document", "note", "revision", "hash", "legacy content", 2, "created", "updated"),
            ("old-term", "term", "term", "revision", "hash", "legacy term", 1, "created", "updated"),
            ("old-source", "source", "source", "revision", "hash", "legacy source", 1, "created", "updated"),
            ("old-taxonomy", "taxonomy", "topics", "revision", "hash", "legacy taxonomy", 1, "created", "updated"),
        ],
    )
    connection.execute(
        """INSERT INTO proposals (
               id, target_type, target_id, kind, status, base_content_hash,
               payload_json, created_by, created_at
           ) VALUES ('proposal', 'document', 'note', 'metadata', 'proposed', 'hash', '{}', 'human', 'now')"""
    )
    connection.execute(
        """INSERT INTO presentation_annotations (
               id, entity_type, entity_id, style_type, style_value, selected_text,
               prefix_text, suffix_text, start_offset, end_offset, base_content_hash,
               status, created_at, updated_at
           ) VALUES (
               'annotation', 'document', 'note', 'underline', NULL, 'text', '', '',
               0, 4, 'hash', 'active', 'created', 'updated'
           )"""
    )
    connection.execute(
        "INSERT INTO import_jobs (id, status, profile, created_at, updated_at) "
        "VALUES ('job', 'ready', 'legacy', 'created', 'updated')"
    )
    connection.execute(
        """INSERT INTO import_items (
               id, job_id, path, file_type, sha256, status, detected_entity_type, metadata_json
           ) VALUES ('item', 'job', 'legacy.md', 'markdown', 'sha', 'ready', 'document', '{}')"""
    )
    connection.execute(
        "INSERT INTO usage_events (id, entity_type, entity_id, event_type, created_at) "
        "VALUES ('usage', 'document', 'note', 'document_open', 'now')"
    )
    connection.commit()
    connection.close()
