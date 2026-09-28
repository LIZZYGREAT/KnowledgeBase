"""SQLite persistence for Drafts."""

import sqlite3
from typing import Optional

from backend.app.domain.runtime import Draft, EntityType


class DraftNotFoundError(LookupError):
    pass


class DraftRevisionConflict(RuntimeError):
    def __init__(self, expected_revision: int, actual_revision: int):
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            "Draft revision changed: expected {}, found {}".format(
                expected_revision, actual_revision
            )
        )


class DraftRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, draft: Draft) -> Draft:
        with self.connection:
            self.connection.execute(
                """INSERT INTO drafts (
                    id, entity_type, entity_id, base_git_revision,
                    base_content_hash, content, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    draft.id,
                    draft.entity_type,
                    draft.entity_id,
                    draft.base_git_revision,
                    draft.base_content_hash,
                    draft.content,
                    draft.revision,
                    draft.created_at,
                    draft.updated_at,
                ),
            )
        return self.get(draft.id)

    def get(self, draft_id: str) -> Optional[Draft]:
        row = self.connection.execute(
            "SELECT * FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        return _draft_from_row(row) if row else None

    def save_content(
        self, draft_id: str, content: str, expected_revision: int, updated_at: str
    ) -> Draft:
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE drafts
                   SET content = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND revision = ?""",
                (content, updated_at, draft_id, expected_revision),
            )
        if cursor.rowcount != 1:
            current = self.get(draft_id)
            if current is None:
                raise DraftNotFoundError("Draft '{}' does not exist".format(draft_id))
            raise DraftRevisionConflict(expected_revision, current.revision)
        return self.get(draft_id)


def _draft_from_row(row: sqlite3.Row) -> Draft:
    return Draft(
        id=row["id"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        base_git_revision=row["base_git_revision"],
        base_content_hash=row["base_content_hash"],
        content=row["content"],
        revision=row["revision"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
