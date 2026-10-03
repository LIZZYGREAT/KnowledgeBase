"""Runtime audit records for Research Profile controls."""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Literal, Optional
import uuid

from backend.app.repositories.research_repository import ResearchRepository


ResearchControlEventType = Literal["pause", "resume", "watermark_skip"]


class ResearchControlEventRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.transactions = ResearchRepository(connection)

    def create(
        self,
        profile_id: str,
        event_type: ResearchControlEventType,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "profile_id": profile_id,
            "event_type": event_type,
            "payload": dict(payload),
            "created_at": _timestamp(created_at),
        }
        serialized = json.dumps(
            event["payload"], ensure_ascii=False, sort_keys=True, allow_nan=False
        )
        with self.transactions.write_transaction():
            self.connection.execute(
                """INSERT INTO research_control_events (
                       id, profile_id, event_type, payload_json, created_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    event["id"],
                    profile_id,
                    event_type,
                    serialized,
                    event["created_at"],
                ),
            )
        return event

    def latest_resume(self, profile_id: str) -> Optional[dict[str, Any]]:
        row = self.connection.execute(
            """SELECT * FROM research_control_events
               WHERE profile_id = ? AND event_type = 'resume'
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (profile_id,),
        ).fetchone()
        return _event_from_row(row) if row else None

    def list_for_profile(
        self, profile_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Research Control Event list limit must be between 1 and 500")
        rows = self.connection.execute(
            """SELECT * FROM research_control_events WHERE profile_id = ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (profile_id, limit),
        ).fetchall()
        return [_event_from_row(row) for row in rows]


def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "event_type": row["event_type"],
        "payload": json.loads(row["payload_json"]),
        "created_at": row["created_at"],
    }


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Research Control Event timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()
