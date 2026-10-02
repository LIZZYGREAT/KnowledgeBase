"""Versioned upgrades for disposable Runtime SQLite state."""

import sqlite3


CURRENT_SCHEMA_VERSION = 1


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


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None
