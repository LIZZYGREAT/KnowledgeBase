"""Versioned upgrades for disposable Runtime SQLite state."""

import sqlite3


CURRENT_SCHEMA_VERSION = 7


def migrate_database(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > CURRENT_SCHEMA_VERSION:
        raise RuntimeError(
            "Runtime database schema version {} is newer than supported version {}".format(
                version, CURRENT_SCHEMA_VERSION
            )
        )

    while version < CURRENT_SCHEMA_VERSION:
        target_version = version + 1
        if target_version == 1:
            migration = _migrate_to_collection_runtime
        elif target_version == 2:
            migration = _migrate_to_unique_draft_target
        elif target_version == 3:
            migration = _migrate_to_current_proposal_lifecycle
        elif target_version == 4:
            migration = _migrate_to_research_runtime
        elif target_version == 5:
            migration = _migrate_to_research_run_ai_disabled_status
        elif target_version == 6:
            migration = _migrate_to_shared_research_source_draft_intents
        elif target_version == 7:
            migration = _migrate_to_persist_research_analysis_input_context
        else:
            raise RuntimeError("No Runtime migration is defined for version {}".format(target_version))

        connection.execute("BEGIN")
        try:
            migration(connection)
            connection.execute("PRAGMA user_version = {}".format(target_version))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        version = target_version


def _migrate_to_shared_research_source_draft_intents(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("DROP INDEX IF EXISTS research_pending_links_group_idx")
    connection.execute(
        "ALTER TABLE research_pending_links RENAME TO research_pending_links_before_shared_drafts"
    )
    connection.execute(
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
               UNIQUE (candidate_id, draft_id, relation_type)
           )"""
    )
    connection.execute(
        """INSERT INTO research_pending_links (
               id, group_id, candidate_id, work_id, draft_id,
               intended_entity_type, intended_entity_id, relation_type, created_at
           ) SELECT id, group_id, candidate_id, work_id, draft_id,
                    intended_entity_type, intended_entity_id, relation_type, created_at
             FROM research_pending_links_before_shared_drafts"""
    )
    connection.execute("DROP TABLE research_pending_links_before_shared_drafts")
    connection.execute(
        """CREATE INDEX research_pending_links_group_idx
           ON research_pending_links (group_id)"""
    )


def _migrate_to_persist_research_analysis_input_context(
    connection: sqlite3.Connection,
) -> None:
    if not _column_exists(connection, "research_work_analyses", "input_context_json"):
        connection.execute(
            """ALTER TABLE research_work_analyses
               ADD COLUMN input_context_json TEXT NOT NULL DEFAULT '{}'"""
        )


def _migrate_to_research_run_ai_disabled_status(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE research_runs_with_ai_disabled_status (
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
               analyzed_count INTEGER NOT NULL DEFAULT 0,
               surfaced_count INTEGER NOT NULL DEFAULT 0,
               provider_summary_json TEXT NOT NULL,
               error_summary TEXT,
               started_at TEXT NOT NULL,
               finished_at TEXT
           )"""
    )
    connection.execute(
        """INSERT INTO research_runs_with_ai_disabled_status (
               id, profile_id, request_id, trigger, status, profile_content_hash,
               effective_config_json, fetched_count, new_work_count, duplicate_count,
               deterministic_filtered_count, analyzed_count, surfaced_count,
               provider_summary_json, error_summary, started_at, finished_at
           )
           SELECT id, profile_id, request_id, trigger, status, profile_content_hash,
                  effective_config_json, fetched_count, new_work_count, duplicate_count,
                  deterministic_filtered_count, analyzed_count, surfaced_count,
                  provider_summary_json, error_summary, started_at, finished_at
           FROM research_runs"""
    )
    connection.execute("DROP TABLE research_runs")
    connection.execute(
        "ALTER TABLE research_runs_with_ai_disabled_status RENAME TO research_runs"
    )
    connection.execute(
        """CREATE INDEX research_runs_profile_idx
           ON research_runs (profile_id, started_at DESC)"""
    )


def _migrate_to_collection_runtime(connection: sqlite3.Connection) -> None:
    if _table_exists(connection, "drafts"):
        # The old index follows the renamed table and keeps its global name, so
        # remove it before recreating the index for the upgraded table.
        connection.execute("DROP INDEX IF EXISTS drafts_target_updated_idx")
        connection.execute("ALTER TABLE drafts RENAME TO drafts_before_collection")
        _create_drafts_table(connection)
        connection.execute(
            """INSERT INTO drafts (
                   id, entity_type, entity_id, base_git_revision, base_content_hash,
                   content, revision, created_at, updated_at
               )
               SELECT id, entity_type, entity_id, base_git_revision, base_content_hash,
                      content, revision, created_at, updated_at
               FROM drafts_before_collection"""
        )
        connection.execute("DROP TABLE drafts_before_collection")
    else:
        _create_drafts_table(connection)
    connection.execute(
        """CREATE INDEX IF NOT EXISTS drafts_target_updated_idx
           ON drafts (entity_type, entity_id, updated_at DESC)"""
    )
    _create_collection_indexes(connection)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS collection_progress (
               collection_id TEXT NOT NULL,
               document_id TEXT NOT NULL,
               status TEXT NOT NULL CHECK (status IN ('reading', 'done')),
               updated_at TEXT NOT NULL,
               PRIMARY KEY (collection_id, document_id)
           )"""
    )


def _create_drafts_table(connection: sqlite3.Connection) -> None:
    connection.execute(
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
           )"""
    )


def _create_collection_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS collection_index (
               collection_id TEXT PRIMARY KEY,
               path TEXT NOT NULL UNIQUE,
               title TEXT NOT NULL,
               description TEXT,
               status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
               position INTEGER NOT NULL CHECK (position >= 0),
               content_hash TEXT NOT NULL
           )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS collection_node_index (
               collection_id TEXT NOT NULL,
               node_id TEXT NOT NULL,
               parent_node_id TEXT,
               kind TEXT NOT NULL CHECK (kind IN ('section', 'entity')),
               depth INTEGER NOT NULL CHECK (depth >= 0),
               ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
               section_title TEXT,
               entity_type TEXT CHECK (entity_type IN ('document', 'term', 'source')),
               entity_id TEXT,
               PRIMARY KEY (collection_id, node_id),
               FOREIGN KEY (collection_id) REFERENCES collection_index (collection_id) ON DELETE CASCADE,
               CHECK (
                   (kind = 'section' AND entity_type IS NULL AND entity_id IS NULL) OR
                   (kind = 'entity' AND entity_type IS NOT NULL AND entity_id IS NOT NULL)
               )
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS collection_node_parent_idx
           ON collection_node_index (collection_id, parent_node_id, ordinal)"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS collection_node_entity_idx
           ON collection_node_index (entity_type, entity_id)"""
    )


def _migrate_to_unique_draft_target(connection: sqlite3.Connection) -> None:
    duplicate_targets = connection.execute(
        """SELECT entity_type, entity_id
           FROM drafts
           GROUP BY entity_type, entity_id
           HAVING COUNT(*) > 1
           ORDER BY entity_type, entity_id"""
    ).fetchall()
    if duplicate_targets:
        details = []
        for entity_type, entity_id in duplicate_targets:
            draft_ids = connection.execute(
                """SELECT id FROM drafts
                   WHERE entity_type = ? AND entity_id = ?
                   ORDER BY updated_at DESC, created_at DESC, id DESC""",
                (entity_type, entity_id),
            ).fetchall()
            details.append(
                "{}:{} [{}]".format(
                    entity_type,
                    entity_id,
                    ", ".join(row[0] for row in draft_ids),
                )
            )
        raise RuntimeError(
            "Cannot migrate Runtime database: duplicate Draft targets prevent "
            "the unique constraint: {}".format("; ".join(details))
        )

    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS drafts_target_unique_idx
           ON drafts (entity_type, entity_id)"""
    )


def _migrate_to_current_proposal_lifecycle(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "proposals"):
        return

    connection.execute("DROP INDEX IF EXISTS proposals_target_status_idx")
    connection.execute("ALTER TABLE proposals RENAME TO proposals_before_current_lifecycle")
    connection.execute(
        """CREATE TABLE proposals (
               id TEXT PRIMARY KEY,
               target_type TEXT NOT NULL CHECK (target_type IN ('document', 'term', 'source', 'taxonomy')),
               target_id TEXT NOT NULL,
               kind TEXT NOT NULL CHECK (kind IN (
                   'metadata', 'link', 'new_term', 'term_revision',
                   'document_revision', 'taxonomy', 'evidence', 'format'
               )),
               status TEXT NOT NULL CHECK (
                   status IN ('proposed', 'drafted', 'merged', 'rejected', 'stale')
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
           )"""
    )
    connection.execute(
        """INSERT INTO proposals (
               id, target_type, target_id, kind, status, base_content_hash,
               payload_json, diff_text, created_by, provider, model,
               created_at, reviewed_at, review_note
           )
           SELECT id, target_type, target_id, kind,
                  CASE WHEN status = 'approved' THEN 'stale' ELSE status END,
                  base_content_hash, payload_json, diff_text, created_by, provider, model,
                  created_at, reviewed_at,
                  CASE WHEN status = 'approved'
                       THEN 'Legacy approved Proposal requires re-application under the current Draft workflow.'
                       ELSE review_note END
           FROM proposals_before_current_lifecycle"""
    )
    connection.execute("DROP TABLE proposals_before_current_lifecycle")
    connection.execute(
        """CREATE INDEX proposals_target_status_idx
           ON proposals (target_type, target_id, status, created_at DESC)"""
    )


def _migrate_to_research_runtime(connection: sqlite3.Connection) -> None:
    if _table_exists(connection, "drafts"):
        connection.execute("DROP INDEX IF EXISTS drafts_target_updated_idx")
        connection.execute("DROP INDEX IF EXISTS drafts_target_unique_idx")
        connection.execute("ALTER TABLE drafts RENAME TO drafts_before_research")
        _create_research_drafts_table(connection)
        connection.execute(
            """INSERT INTO drafts (
                   id, entity_type, entity_id, base_git_revision, base_content_hash,
                   content, revision, created_at, updated_at
               )
               SELECT id, entity_type, entity_id, base_git_revision, base_content_hash,
                      content, revision, created_at, updated_at
               FROM drafts_before_research"""
        )
        connection.execute("DROP TABLE drafts_before_research")
    else:
        _create_research_drafts_table(connection)

    connection.execute(
        """CREATE INDEX IF NOT EXISTS drafts_target_updated_idx
           ON drafts (entity_type, entity_id, updated_at DESC)"""
    )
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS drafts_target_unique_idx
           ON drafts (entity_type, entity_id)"""
    )
    _create_research_tables(connection)


def _create_research_drafts_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE drafts (
               id TEXT PRIMARY KEY,
               entity_type TEXT NOT NULL CHECK (
                   entity_type IN (
                       'document', 'term', 'source', 'taxonomy', 'collection',
                       'research_profile'
                   )
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


def _create_research_tables(connection: sqlite3.Connection) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS research_profile_state (
               profile_id TEXT PRIMARY KEY,
               paused_until TEXT,
               last_successful_scheduled_run_at TEXT,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )""",
        """CREATE TABLE IF NOT EXISTS research_control_events (
               id TEXT PRIMARY KEY,
               profile_id TEXT NOT NULL,
               event_type TEXT NOT NULL CHECK (
                   event_type IN ('pause', 'resume', 'watermark_skip')
               ),
               payload_json TEXT NOT NULL,
               created_at TEXT NOT NULL
           )""",
        """CREATE INDEX IF NOT EXISTS research_control_events_profile_idx
           ON research_control_events (profile_id, created_at DESC)""",
        """CREATE TABLE IF NOT EXISTS research_works (
               id TEXT PRIMARY KEY,
               canonical_key TEXT NOT NULL,
               title TEXT NOT NULL,
               normalized_title TEXT NOT NULL,
               abstract TEXT,
               authors_json TEXT NOT NULL,
               year INTEGER,
               published_at TEXT,
               venue TEXT,
               doi TEXT,
               arxiv_id TEXT,
               openalex_id TEXT,
               semantic_scholar_id TEXT,
               url TEXT,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )""",
        """CREATE UNIQUE INDEX IF NOT EXISTS research_works_doi_unique
           ON research_works (doi) WHERE doi IS NOT NULL""",
        """CREATE UNIQUE INDEX IF NOT EXISTS research_works_arxiv_unique
           ON research_works (arxiv_id) WHERE arxiv_id IS NOT NULL""",
        """CREATE UNIQUE INDEX IF NOT EXISTS research_works_openalex_unique
           ON research_works (openalex_id) WHERE openalex_id IS NOT NULL""",
        """CREATE UNIQUE INDEX IF NOT EXISTS research_works_semantic_scholar_unique
           ON research_works (semantic_scholar_id) WHERE semantic_scholar_id IS NOT NULL""",
        """CREATE INDEX IF NOT EXISTS research_works_normalized_title_idx
           ON research_works (normalized_title, year)""",
        """CREATE TABLE IF NOT EXISTS research_discoveries (
               id TEXT PRIMARY KEY,
               work_id TEXT NOT NULL,
               profile_id TEXT NOT NULL,
               lens_id TEXT NOT NULL,
               provider TEXT NOT NULL,
               provider_record_id TEXT NOT NULL,
               query_key TEXT NOT NULL,
               query_text TEXT NOT NULL,
               metadata_json TEXT NOT NULL,
               discovered_at TEXT NOT NULL,
               FOREIGN KEY (work_id) REFERENCES research_works(id) ON DELETE CASCADE,
               UNIQUE (profile_id, lens_id, provider, provider_record_id, query_key)
           )""",
        """CREATE INDEX IF NOT EXISTS research_discoveries_work_idx
           ON research_discoveries (work_id, discovered_at DESC)""",
        """CREATE INDEX IF NOT EXISTS research_discoveries_profile_idx
           ON research_discoveries (profile_id, discovered_at DESC)""",
        """CREATE TABLE IF NOT EXISTS research_work_analyses (
               id TEXT PRIMARY KEY,
               work_id TEXT NOT NULL,
               profile_id TEXT NOT NULL,
               input_hash TEXT NOT NULL,
               outcome TEXT NOT NULL CHECK (outcome IN ('surface', 'filtered')),
               analysis_json TEXT NOT NULL,
               provider TEXT NOT NULL,
               model TEXT NOT NULL,
               prompt_version TEXT NOT NULL,
               analysis_version INTEGER NOT NULL,
               context_entity_ids_json TEXT NOT NULL,
               analyzed_at TEXT NOT NULL,
               FOREIGN KEY (work_id) REFERENCES research_works(id) ON DELETE CASCADE,
               UNIQUE (work_id, profile_id, input_hash)
           )""",
        """CREATE INDEX IF NOT EXISTS research_work_analyses_profile_idx
           ON research_work_analyses (profile_id, analyzed_at DESC)""",
        """CREATE TABLE IF NOT EXISTS research_candidates (
               id TEXT PRIMARY KEY,
               work_id TEXT NOT NULL,
               profile_id TEXT NOT NULL,
               status TEXT NOT NULL CHECK (
                   status IN ('new', 'shortlisted', 'dismissed', 'saved_source', 'note_created')
               ),
               primary_lens_id TEXT,
               analysis_id TEXT NOT NULL,
               user_note TEXT,
               dismiss_reason TEXT,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL,
               first_viewed_at TEXT,
               last_viewed_at TEXT,
               decided_at TEXT,
               FOREIGN KEY (work_id) REFERENCES research_works(id) ON DELETE CASCADE,
               UNIQUE (work_id, profile_id)
           )""",
        """CREATE INDEX IF NOT EXISTS research_candidates_inbox_idx
           ON research_candidates (profile_id, status, created_at DESC)""",
        """CREATE TABLE IF NOT EXISTS research_search_state (
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
           )""",
        """CREATE TABLE IF NOT EXISTS research_runs (
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
           )""",
        """CREATE INDEX IF NOT EXISTS research_runs_profile_idx
           ON research_runs (profile_id, started_at DESC)""",
        """CREATE TABLE IF NOT EXISTS research_run_requests (
               id TEXT PRIMARY KEY,
               profile_id TEXT NOT NULL,
               trigger TEXT NOT NULL CHECK (trigger = 'manual'),
               override_json TEXT NOT NULL,
               status TEXT NOT NULL CHECK (
                   status IN ('pending', 'claimed', 'completed', 'failed')
               ),
               created_at TEXT NOT NULL,
               claimed_at TEXT,
               completed_at TEXT
           )""",
        """CREATE INDEX IF NOT EXISTS research_run_requests_pending_idx
           ON research_run_requests (status, created_at)""",
        """CREATE TABLE IF NOT EXISTS research_entity_links (
               id TEXT PRIMARY KEY,
               work_id TEXT NOT NULL,
               entity_type TEXT NOT NULL CHECK (entity_type IN ('source', 'document')),
               entity_id TEXT NOT NULL,
               relation_type TEXT NOT NULL CHECK (relation_type IN ('source', 'note')),
               created_at TEXT NOT NULL,
               UNIQUE (work_id, entity_type, entity_id, relation_type)
           )""",
        """CREATE INDEX IF NOT EXISTS research_entity_links_work_idx
           ON research_entity_links (work_id)""",
        """CREATE TABLE IF NOT EXISTS research_pending_links (
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
           )""",
        """CREATE INDEX IF NOT EXISTS research_pending_links_group_idx
           ON research_pending_links (group_id)""",
    )
    for statement in statements:
        connection.execute(statement)


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(
        row[1] == column
        for row in connection.execute("PRAGMA table_info({})".format(table))
    )
