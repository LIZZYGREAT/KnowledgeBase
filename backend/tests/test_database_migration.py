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
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
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
        assert reopened.execute("PRAGMA user_version").fetchone()[0] == 16
        assert reopened.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 5
        assert reopened.execute("SELECT COUNT(*) FROM collection_progress").fetchone()[0] == 1
    finally:
        reopened.close()


def test_migration_rejects_a_database_from_a_newer_schema_version():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA user_version = 17")

    with pytest.raises(RuntimeError, match="newer than supported"):
        migrate_database(connection)

    connection.close()


def test_version_fourteen_migration_adds_pdf_corpus():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA user_version = 14")

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(pdf_corpus)")
    }
    assert columns == {
        "source_id",
        "pdf_hash",
        "extractor_version",
        "text_hash",
        "text",
        "status",
        "extracted_at",
        "error_message",
        "updated_at",
    }
    connection.close()


def test_version_fifteen_migration_adds_discovery_state_and_candidate_assessments():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """CREATE TABLE term_candidates (
               id TEXT PRIMARY KEY,
               normalized_name TEXT NOT NULL,
               display_name TEXT NOT NULL,
               suggested_type TEXT NOT NULL,
               suggested_term_id TEXT,
               status TEXT NOT NULL,
               draft_id TEXT,
               accepted_term_id TEXT,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               reviewed_at TEXT
           )"""
    )
    connection.execute("PRAGMA user_version = 15")

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    candidate_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(term_candidates)")
    }
    assert "recommendation_json" in candidate_columns
    for table in (
        "corpus_analysis_state",
        "vocabulary_source_statistics",
        "term_discovery_settings",
        "term_discovery_runs",
    ):
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone() is not None
    connection.close()


def test_version_ten_migration_adds_overlap_floor_and_preserves_watermarks():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE research_search_state (
               profile_id TEXT NOT NULL,
               lens_id TEXT NOT NULL,
               provider TEXT NOT NULL,
               query_key TEXT NOT NULL,
               query_text TEXT NOT NULL,
               completed_through TEXT,
               last_attempt_at TEXT,
               last_success_at TEXT,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               PRIMARY KEY (profile_id, lens_id, provider, query_key)
           );
           INSERT INTO research_search_state VALUES (
               'profile-1', 'lens-1', 'arxiv', 'query-1', 'query text',
               '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00',
               '2026-10-01T00:00:00+00:00', 'created', 'updated'
           );
           PRAGMA user_version = 10;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    assert "overlap_floor" in {
        row[1] for row in connection.execute("PRAGMA table_info(research_search_state)")
    }
    assert connection.execute(
        "SELECT completed_through, overlap_floor, last_success_at "
        "FROM research_search_state WHERE profile_id = 'profile-1'"
    ).fetchone() == (
        "2026-10-01T00:00:00+00:00",
        None,
        "2026-10-01T00:00:00+00:00",
    )
    connection.close()


def test_version_nine_migration_preserves_control_events_and_removes_reactivation_choice():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE research_control_events (
               id TEXT PRIMARY KEY,
               profile_id TEXT NOT NULL,
               event_type TEXT NOT NULL CHECK (
                   event_type IN ('pause', 'resume', 'watermark_skip')
               ),
               payload_json TEXT NOT NULL,
               created_at TEXT NOT NULL
           );
           CREATE INDEX research_control_events_profile_idx
               ON research_control_events (profile_id, created_at DESC);
           INSERT INTO research_control_events VALUES (
               'resume-1', 'profile-1', 'resume', '{"strategy":"catch_up"}', '2026-10-01'
           );
           PRAGMA user_version = 9;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    assert connection.execute(
        "SELECT id, profile_id, event_type, payload_json, created_at "
        "FROM research_control_events"
    ).fetchone() == (
        "resume-1",
        "profile-1",
        "resume",
        '{"strategy":"catch_up"}',
        "2026-10-01",
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO research_control_events VALUES (
                   'choice-1', 'profile-1', 'reactivation_choice', '{}', '2026-10-02'
               )"""
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO research_control_events VALUES (
                   'invalid-1', 'profile-1', 'skip', '{}', '2026-10-03'
               )"""
        )
    connection.close()


def test_version_twelve_removes_obsolete_research_runtime_states_and_keeps_valid_rows():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE research_control_events (
               id TEXT PRIMARY KEY,
               profile_id TEXT NOT NULL,
               event_type TEXT NOT NULL CHECK (
                   event_type IN ('pause', 'resume', 'watermark_skip', 'reactivation_choice')
               ),
               payload_json TEXT NOT NULL,
               created_at TEXT NOT NULL
           );
           CREATE INDEX research_control_events_profile_idx
               ON research_control_events (profile_id, created_at DESC);
           INSERT INTO research_control_events VALUES
               ('pause-1', 'profile-1', 'pause', '{}', '2026-10-01'),
               ('choice-1', 'profile-1', 'reactivation_choice', '{}', '2026-10-02');
           CREATE TABLE research_runs (
               id TEXT PRIMARY KEY,
               profile_id TEXT NOT NULL,
               request_id TEXT,
               trigger TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual')),
               status TEXT NOT NULL CHECK (
                   status IN (
                       'running', 'success', 'partial', 'failed', 'interrupted',
                       'skipped_paused', 'skipped_disabled', 'skipped_ai_disabled',
                       'skipped_inbox_full', 'capacity_reached'
                   )
               ),
               profile_content_hash TEXT NOT NULL,
               effective_config_json TEXT NOT NULL,
               fetched_count INTEGER NOT NULL DEFAULT 0,
               new_work_count INTEGER NOT NULL DEFAULT 0,
               duplicate_count INTEGER NOT NULL DEFAULT 0,
               deterministic_filtered_count INTEGER NOT NULL DEFAULT 0,
               analysis_attempt_count INTEGER NOT NULL DEFAULT 0,
               analyzed_count INTEGER NOT NULL DEFAULT 0,
               analysis_counts_known INTEGER NOT NULL DEFAULT 1,
               surfaced_count INTEGER NOT NULL DEFAULT 0,
               provider_summary_json TEXT NOT NULL,
               error_summary TEXT,
               started_at TEXT NOT NULL,
               finished_at TEXT
           );
           CREATE INDEX research_runs_profile_idx
               ON research_runs (profile_id, started_at DESC);
           INSERT INTO research_runs (
               id, profile_id, trigger, status, profile_content_hash,
               effective_config_json, analysis_attempt_count, analyzed_count,
               analysis_counts_known, provider_summary_json, started_at, finished_at
           ) VALUES
               ('kept-run', 'profile-1', 'manual', 'success', 'hash', '{}', 3, 2, 0, '{}', 'start', 'finish'),
               ('obsolete-run', 'profile-1', 'manual', 'skipped_ai_disabled', 'hash', '{}', 0, 0, 1, '{}', 'start', 'finish');
           PRAGMA user_version = 11;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    assert connection.execute(
        "SELECT id, event_type FROM research_control_events"
    ).fetchall() == [("pause-1", "pause")]
    assert connection.execute(
        "SELECT id, analysis_attempt_count, analyzed_count, analysis_counts_known "
        "FROM research_runs"
    ).fetchall() == [("kept-run", 3, 2, 0)]
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO research_control_events VALUES ('choice-2', 'profile-1', "
            "'reactivation_choice', '{}', '2026-10-03')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO research_runs (
                   id, profile_id, trigger, status, profile_content_hash,
                   effective_config_json, provider_summary_json, started_at
               ) VALUES ('obsolete-2', 'profile-1', 'manual', 'skipped_ai_disabled',
                         'hash', '{}', '{}', 'start')"""
        )
    connection.close()


def test_version_seven_migration_separates_attempts_and_marks_old_analysis_totals_unknown():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE research_runs (
               id TEXT PRIMARY KEY,
               analyzed_count INTEGER NOT NULL DEFAULT 0
           );
           INSERT INTO research_runs VALUES ('old-run', 2);
           PRAGMA user_version = 7;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    row = connection.execute(
        """SELECT analysis_attempt_count, analyzed_count, analysis_counts_known
           FROM research_runs WHERE id = 'old-run'"""
    ).fetchone()
    assert tuple(row) == (2, 2, 0)
    connection.close()


def test_version_eight_migration_normalizes_historical_research_dismiss_reasons():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE research_candidates (
               id TEXT PRIMARY KEY,
               dismiss_reason TEXT
           );
           INSERT INTO research_candidates VALUES ('similar', 'too_similar');
           INSERT INTO research_candidates VALUES ('subfield', 'not_following_subfield');
           INSERT INTO research_candidates VALUES ('other', 'other');
           PRAGMA user_version = 8;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    assert connection.execute(
        "SELECT id, dismiss_reason FROM research_candidates ORDER BY id"
    ).fetchall() == [
        ("other", "other"),
        ("similar", "too_redundant"),
        ("subfield", "not_interested"),
    ]
    connection.close()


def test_version_five_migration_allows_multiple_candidates_to_share_source_draft():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE research_pending_links (
               id TEXT PRIMARY KEY,
               group_id TEXT NOT NULL,
               candidate_id TEXT NOT NULL,
               work_id TEXT NOT NULL,
               draft_id TEXT NOT NULL,
               intended_entity_type TEXT NOT NULL,
               intended_entity_id TEXT NOT NULL,
               relation_type TEXT NOT NULL CHECK (
                   relation_type IN ('source', 'note', 'collection')
               ),
               created_at TEXT NOT NULL,
               UNIQUE (draft_id, relation_type)
           );
           CREATE INDEX research_pending_links_group_idx
               ON research_pending_links (group_id);
           CREATE TABLE research_work_analyses (
               id TEXT PRIMARY KEY,
               work_id TEXT NOT NULL,
               profile_id TEXT NOT NULL,
               input_hash TEXT NOT NULL,
               outcome TEXT NOT NULL,
               analysis_json TEXT NOT NULL,
               provider TEXT NOT NULL,
               model TEXT NOT NULL,
               prompt_version TEXT NOT NULL,
               analysis_version INTEGER NOT NULL,
               context_entity_ids_json TEXT NOT NULL,
               analyzed_at TEXT NOT NULL
           );
           INSERT INTO research_pending_links VALUES (
               'link-a', 'group-a', 'candidate-a', 'work-a', 'source-draft',
               'source', 'source-a', 'source', 'now'
           );
           PRAGMA user_version = 5;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    assert connection.execute(
        "SELECT candidate_id, draft_id FROM research_pending_links"
    ).fetchall() == [("candidate-a", "source-draft")]
    connection.execute(
        """INSERT INTO research_pending_links VALUES (
               'link-b', 'group-b', 'candidate-b', 'work-a', 'source-draft',
               'source', 'source-a', 'source', 'later'
           )"""
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO research_pending_links VALUES (
                   'link-b-duplicate', 'group-b', 'candidate-b', 'work-a',
                   'source-draft', 'source', 'source-a', 'source', 'later'
               )"""
        )
    connection.close()


def test_version_three_database_migrates_research_tables_and_preserves_drafts():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """CREATE TABLE drafts (
               id TEXT PRIMARY KEY,
               entity_type TEXT NOT NULL CHECK (
                   entity_type IN ('document', 'term', 'source', 'taxonomy', 'collection')
               ),
               entity_id TEXT NOT NULL,
               base_git_revision TEXT NOT NULL,
               base_content_hash TEXT NOT NULL,
               content TEXT NOT NULL,
               revision INTEGER NOT NULL CHECK (revision > 0),
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           );
           CREATE INDEX drafts_target_updated_idx
               ON drafts (entity_type, entity_id, updated_at DESC);
           CREATE UNIQUE INDEX drafts_target_unique_idx
               ON drafts (entity_type, entity_id);
           INSERT INTO drafts VALUES (
               'existing-draft', 'document', 'note', 'revision', 'hash',
               'preserved draft content', 2, 'created', 'updated'
           );
           PRAGMA user_version = 3;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    assert connection.execute(
        "SELECT content, revision FROM drafts WHERE id = 'existing-draft'"
    ).fetchone() == ("preserved draft content", 2)
    connection.execute(
        """INSERT INTO drafts VALUES (
               'profile-draft', 'research_profile', 'continual-learning',
               'revision', 'hash', 'profile draft', 1, 'created', 'updated'
           )"""
    )

    expected_tables = {
        "research_profile_state",
        "research_control_events",
        "research_works",
        "research_discoveries",
        "research_work_analyses",
        "research_candidates",
        "research_search_state",
        "research_runs",
        "research_run_requests",
        "research_entity_links",
        "research_pending_links",
    }
    actual_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert expected_tables <= actual_tables
    assert connection.execute(
        "SELECT entity_id FROM drafts WHERE id = 'profile-draft'"
    ).fetchone()[0] == "continual-learning"
    connection.close()


def test_version_four_research_run_migration_preserves_rows_and_v12_removes_ai_disabled_status():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE research_runs (
               id TEXT PRIMARY KEY,
               profile_id TEXT NOT NULL,
               request_id TEXT,
               trigger TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual')),
               status TEXT NOT NULL CHECK (
                   status IN (
                       'running', 'success', 'partial', 'failed', 'interrupted',
                       'skipped_paused', 'skipped_disabled', 'skipped_inbox_full',
                       'capacity_reached'
                   )
               ),
               profile_content_hash TEXT NOT NULL,
               effective_config_json TEXT NOT NULL,
               fetched_count INTEGER NOT NULL DEFAULT 0,
               new_work_count INTEGER NOT NULL DEFAULT 0,
               duplicate_count INTEGER NOT NULL DEFAULT 0,
               deterministic_filtered_count INTEGER NOT NULL DEFAULT 0,
               analyzed_count INTEGER NOT NULL DEFAULT 0,
               surfaced_count INTEGER NOT NULL DEFAULT 0,
               provider_summary_json TEXT NOT NULL,
               error_summary TEXT,
               started_at TEXT NOT NULL,
               finished_at TEXT
           );
           CREATE INDEX research_runs_profile_idx
               ON research_runs (profile_id, started_at DESC);
           CREATE TABLE research_pending_links (
               id TEXT PRIMARY KEY,
               group_id TEXT NOT NULL,
               candidate_id TEXT NOT NULL,
               work_id TEXT NOT NULL,
               draft_id TEXT NOT NULL,
               intended_entity_type TEXT NOT NULL,
               intended_entity_id TEXT NOT NULL,
               relation_type TEXT NOT NULL CHECK (
                   relation_type IN ('source', 'note', 'collection')
               ),
               created_at TEXT NOT NULL,
               UNIQUE (draft_id, relation_type)
           );
           CREATE INDEX research_pending_links_group_idx
               ON research_pending_links (group_id);
           CREATE TABLE research_work_analyses (
               id TEXT PRIMARY KEY,
               work_id TEXT NOT NULL,
               profile_id TEXT NOT NULL,
               input_hash TEXT NOT NULL,
               outcome TEXT NOT NULL,
               analysis_json TEXT NOT NULL,
               provider TEXT NOT NULL,
               model TEXT NOT NULL,
               prompt_version TEXT NOT NULL,
               analysis_version INTEGER NOT NULL,
               context_entity_ids_json TEXT NOT NULL,
               analyzed_at TEXT NOT NULL
           );
           INSERT INTO research_runs VALUES (
               'existing-run', 'profile', NULL, 'manual', 'success', 'hash', '{}',
               2, 1, 0, 0, 1, 1, '{}', NULL, 'started', 'finished'
           );
           PRAGMA user_version = 4;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    assert connection.execute(
        "SELECT status, fetched_count, finished_at FROM research_runs WHERE id = 'existing-run'"
    ).fetchone() == ("success", 2, "finished")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """INSERT INTO research_runs (
                   id, profile_id, trigger, status, profile_content_hash,
                   effective_config_json, provider_summary_json, started_at, finished_at
               ) VALUES ('disabled-run', 'profile', 'manual', 'skipped_ai_disabled',
                         'hash', '{}', '{}', 'started', 'finished')"""
        )
    connection.close()


def test_version_six_migration_preserves_analyses_with_empty_input_context():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """CREATE TABLE research_work_analyses (
               id TEXT PRIMARY KEY,
               work_id TEXT NOT NULL,
               profile_id TEXT NOT NULL,
               input_hash TEXT NOT NULL,
               outcome TEXT NOT NULL,
               analysis_json TEXT NOT NULL,
               provider TEXT NOT NULL,
               model TEXT NOT NULL,
               prompt_version TEXT NOT NULL,
               analysis_version INTEGER NOT NULL,
               context_entity_ids_json TEXT NOT NULL,
               analyzed_at TEXT NOT NULL
           );
           INSERT INTO research_work_analyses VALUES (
               'analysis-1', 'work-1', 'profile-1', 'hash', 'surface', '{}',
               'deepseek', 'model', 'prompt-v1', 1, '[]', 'analyzed'
           );
           PRAGMA user_version = 6;"""
    )

    migrate_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 16
    assert connection.execute(
        "SELECT input_context_json FROM research_work_analyses WHERE id = 'analysis-1'"
    ).fetchone()[0] == "{}"
    connection.close()


def test_research_schema_enforces_identity_capacity_and_control_values():
    connection = connect_database(":memory:")
    try:
        connection.execute(
            """INSERT INTO research_works (
                   id, canonical_key, title, normalized_title, authors_json,
                   doi, created_at, updated_at
               ) VALUES ('work-1', 'doi:10/example', 'Title', 'title', '[]',
                         '10/example', 'created', 'updated')"""
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO research_works (
                       id, canonical_key, title, normalized_title, authors_json,
                       doi, created_at, updated_at
                   ) VALUES ('work-2', 'doi:10/example', 'Other', 'other', '[]',
                             '10/example', 'created', 'updated')"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO research_control_events
                   (id, profile_id, event_type, payload_json, created_at)
                   VALUES ('event', 'profile', 'skip', '{}', 'created')"""
            )
    finally:
        connection.close()


def test_file_database_uses_wal_and_configurable_busy_timeout(tmp_path):
    database_path = tmp_path / "runtime" / "knowledge.db"
    connection = connect_database(database_path, busy_timeout_ms=1500)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1500
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        connection.close()


def test_memory_database_keeps_memory_journal_and_validates_busy_timeout():
    connection = connect_database(":memory:", busy_timeout_ms=250)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 250
    finally:
        connection.close()

    with pytest.raises(ValueError, match="busy_timeout_ms"):
        connect_database(":memory:", busy_timeout_ms=-1)


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
