"""Record small, privacy-conscious document usage events in Runtime SQLite."""

from datetime import datetime, timezone
from typing import List
import uuid

import sqlite3


_EVENTS = {"document_open", "search_result_click"}


class UsageService:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def record_document_open(self, document_id: str) -> dict:
        return self.record_event(document_id, "document_open")

    def record_search_result_click(self, document_id: str) -> dict:
        return self.record_event(document_id, "search_result_click")

    def record_event(self, document_id: str, event_type: str) -> dict:
        if not isinstance(document_id, str) or not document_id.strip():
            raise ValueError("document_id must be non-empty text")
        if event_type not in _EVENTS:
            raise ValueError("Unsupported usage event: {}".format(event_type))
        exists = self.connection.execute(
            "SELECT 1 FROM document_index WHERE entity_id = ?", (document_id,)
        ).fetchone()
        if exists is None:
            raise LookupError("Document '{}' is not in the canonical index".format(document_id))

        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        event_id = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                """INSERT INTO usage_events (
                       id, entity_type, entity_id, event_type, created_at
                   ) VALUES (?, 'document', ?, ?, ?)""",
                (event_id, document_id, event_type, created_at),
            )
            view_delta = 1 if event_type == "document_open" else 0
            click_delta = 1 if event_type == "search_result_click" else 0
            last_viewed = created_at if view_delta else None
            self.connection.execute(
                """INSERT INTO document_stats (
                       document_id, view_count, search_click_count, last_viewed_at
                   ) VALUES (?, ?, ?, ?)
                   ON CONFLICT(document_id) DO UPDATE SET
                       view_count = document_stats.view_count + excluded.view_count,
                       search_click_count = document_stats.search_click_count + excluded.search_click_count,
                       last_viewed_at = CASE
                           WHEN excluded.last_viewed_at IS NULL THEN document_stats.last_viewed_at
                           WHEN document_stats.last_viewed_at IS NULL OR
                                excluded.last_viewed_at > document_stats.last_viewed_at
                           THEN excluded.last_viewed_at
                           ELSE document_stats.last_viewed_at
                       END""",
                (document_id, view_delta, click_delta, last_viewed),
            )
        return {
            "id": event_id,
            "entity_type": "document",
            "entity_id": document_id,
            "event_type": event_type,
            "created_at": created_at,
        }

    def recently_viewed(self, limit: int = 10) -> List[dict]:
        _validate_limit(limit)
        rows = self.connection.execute(
            """SELECT d.entity_id, d.title, d.path, s.view_count,
                      s.search_click_count, s.last_viewed_at
               FROM document_stats s
               JOIN document_index d ON d.entity_id = s.document_id
               WHERE s.last_viewed_at IS NOT NULL
               ORDER BY s.last_viewed_at DESC, d.entity_id
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def frequently_viewed(self, limit: int = 10) -> List[dict]:
        _validate_limit(limit)
        rows = self.connection.execute(
            """SELECT d.entity_id, d.title, d.path, s.view_count,
                      s.search_click_count, s.last_viewed_at
               FROM document_stats s
               JOIN document_index d ON d.entity_id = s.document_id
               WHERE s.view_count > 0
               ORDER BY s.view_count DESC, s.last_viewed_at DESC, d.entity_id
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def _validate_limit(limit: int) -> None:
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
