"""Versioned upgrades for disposable Runtime SQLite state."""

import sqlite3


CURRENT_SCHEMA_VERSION = 3


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


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None
