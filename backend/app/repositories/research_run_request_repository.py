"""Atomic persistence and claiming for queued manual Research Runs."""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Mapping, Optional
import uuid

from backend.app.domain.research_runtime import ResearchRunRequestRecord
from backend.app.repositories.research_repository import ResearchRepository


class ResearchRunRequestRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.transactions = ResearchRepository(connection)

    def enqueue(
        self,
        profile_id: str,
        override: Mapping[str, Any],
        created_at: datetime,
        request_id: Optional[str] = None,
    ) -> ResearchRunRequestRecord:
        timestamp = _timestamp(created_at)
        serialized = json.dumps(
            dict(override), ensure_ascii=False, sort_keys=True, allow_nan=False
        )
        request = ResearchRunRequestRecord(
            id=request_id or str(uuid.uuid4()),
            profile_id=profile_id,
            override=json.loads(serialized),
            status="pending",
            created_at=timestamp,
        )
        with self.transactions.write_transaction():
            self.connection.execute(
                """INSERT INTO research_run_requests (
                       id, profile_id, trigger, override_json, status,
                       created_at, claimed_at, completed_at
                   ) VALUES (?, ?, 'manual', ?, 'pending', ?, NULL, NULL)""",
                (request.id, request.profile_id, serialized, timestamp),
            )
        return request

    def get(self, request_id: str) -> Optional[ResearchRunRequestRecord]:
        row = self.connection.execute(
            "SELECT * FROM research_run_requests WHERE id = ?", (request_id,)
        ).fetchone()
        return _request_from_row(row) if row else None

    def list_for_profile(
        self, profile_id: str, limit: int = 50
    ) -> list[ResearchRunRequestRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Research Run Request list limit must be between 1 and 500")
        rows = self.connection.execute(
            """SELECT * FROM research_run_requests WHERE profile_id = ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (profile_id, limit),
        ).fetchall()
        return [_request_from_row(row) for row in rows]

    def claim_next(self, claimed_at: datetime) -> Optional[ResearchRunRequestRecord]:
        timestamp = _timestamp(claimed_at)
        with self.transactions.write_transaction():
            row = self.connection.execute(
                """SELECT id FROM research_run_requests
                   WHERE status = 'pending'
                   ORDER BY created_at, id LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            cursor = self.connection.execute(
                """UPDATE research_run_requests
                   SET status = 'claimed', claimed_at = ?, completed_at = NULL
                   WHERE id = ? AND status = 'pending'""",
                (timestamp, row["id"]),
            )
            if cursor.rowcount != 1:
                return None
            request = self.get(row["id"])
        if request is None:
            raise RuntimeError("Claimed Research Run Request disappeared")
        return request

    def finish(
        self,
        request_id: str,
        status: str,
        completed_at: datetime,
    ) -> ResearchRunRequestRecord:
        if status not in {"completed", "failed"}:
            raise ValueError("Research Run Request can only finish as completed or failed")
        timestamp = _timestamp(completed_at)
        with self.transactions.write_transaction():
            cursor = self.connection.execute(
                """UPDATE research_run_requests
                   SET status = ?, completed_at = ?
                   WHERE id = ? AND status = 'claimed'""",
                (status, timestamp, request_id),
            )
            if cursor.rowcount != 1:
                existing = self.get(request_id)
                if existing is None:
                    raise LookupError("Research Run Request '{}' does not exist".format(request_id))
                if existing.status != status:
                    raise ValueError("Research Run Request has already finished")
                return existing
            request = self.get(request_id)
        if request is None:
            raise RuntimeError("Finished Research Run Request disappeared")
        return request

    def recover_stale_claims(
        self, stale_before: datetime
    ) -> tuple[ResearchRunRequestRecord, ...]:
        cutoff = _timestamp(stale_before)
        with self.transactions.write_transaction():
            rows = self._stale_rows(cutoff)
            if rows:
                self.connection.executemany(
                    """UPDATE research_run_requests
                       SET status = 'pending', claimed_at = NULL, completed_at = NULL
                       WHERE id = ? AND status = 'claimed'""",
                    [(row["id"],) for row in rows],
                )
            recovered = tuple(self.get(row["id"]) for row in rows)
        return tuple(request for request in recovered if request is not None)

    def list_stale_claims(
        self, stale_before: datetime
    ) -> tuple[ResearchRunRequestRecord, ...]:
        cutoff = _timestamp(stale_before)
        rows = self._stale_rows(cutoff)
        return tuple(_request_from_row(row) for row in rows)

    def _stale_rows(self, cutoff: str):
        return self.connection.execute(
            """SELECT * FROM research_run_requests
               WHERE status = 'claimed' AND claimed_at <= ?
               ORDER BY claimed_at, id""",
            (cutoff,),
        ).fetchall()


def _request_from_row(row: sqlite3.Row) -> ResearchRunRequestRecord:
    return ResearchRunRequestRecord(
        id=row["id"],
        profile_id=row["profile_id"],
        trigger=row["trigger"],
        override=json.loads(row["override_json"]),
        status=row["status"],
        created_at=row["created_at"],
        claimed_at=row["claimed_at"],
        completed_at=row["completed_at"],
    )


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Research Run Request timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()
