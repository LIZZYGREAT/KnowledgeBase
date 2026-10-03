"""Small-transaction persistence for Research Runs and profile runtime state."""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Optional
import uuid

from backend.app.domain.research_runtime import (
    ResearchProfileStateRecord,
    ResearchRunRecord,
    ResearchRunStatus,
)
from backend.app.repositories.research_repository import ResearchRepository


_COUNTERS = {
    "fetched_count",
    "new_work_count",
    "duplicate_count",
    "deterministic_filtered_count",
    "analyzed_count",
    "surfaced_count",
}


class ResearchRunRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.transactions = ResearchRepository(connection)

    def create(self, run: ResearchRunRecord) -> ResearchRunRecord:
        with self.transactions.write_transaction():
            self.connection.execute(
                """INSERT INTO research_runs (
                       id, profile_id, request_id, trigger, status,
                       profile_content_hash, effective_config_json, fetched_count,
                       new_work_count, duplicate_count, deterministic_filtered_count,
                       analyzed_count, surfaced_count, provider_summary_json,
                       error_summary, started_at, finished_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _run_values(run),
            )
        return run

    def get(self, run_id: str) -> Optional[ResearchRunRecord]:
        row = self.connection.execute(
            "SELECT * FROM research_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _run_from_row(row) if row else None

    def list_for_profile(self, profile_id: str, limit: int = 50) -> list[ResearchRunRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Research Run list limit must be between 1 and 500")
        rows = self.connection.execute(
            """SELECT * FROM research_runs WHERE profile_id = ?
               ORDER BY started_at DESC, id DESC LIMIT ?""",
            (profile_id, limit),
        ).fetchall()
        return [_run_from_row(row) for row in rows]

    def list_recent(
        self,
        limit: int = 50,
        offset: int = 0,
        profile_id: Optional[str] = None,
    ) -> list[ResearchRunRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Research Run list limit must be between 1 and 500")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("Research Run offset must be non-negative")
        if profile_id is None:
            rows = self.connection.execute(
                """SELECT * FROM research_runs
                   ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """SELECT * FROM research_runs WHERE profile_id = ?
                   ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?""",
                (profile_id, limit, offset),
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def count_recent(self, profile_id: Optional[str] = None) -> int:
        if profile_id is None:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM research_runs"
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM research_runs WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return int(row["count"])

    def update_progress(self, run_id: str, **increments: int) -> ResearchRunRecord:
        if not increments or set(increments) - _COUNTERS:
            raise ValueError("Research Run progress contains unsupported counters")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in increments.values()
        ):
            raise ValueError("Research Run progress increments must be non-negative integers")
        assignments = ", ".join(
            "{} = {} + ?".format(key, key) for key in sorted(increments)
        )
        with self.transactions.write_transaction():
            cursor = self.connection.execute(
                "UPDATE research_runs SET {} WHERE id = ? AND status = 'running'".format(
                    assignments
                ),
                tuple(increments[key] for key in sorted(increments)) + (run_id,),
            )
            if cursor.rowcount != 1:
                raise LookupError("Running Research Run '{}' does not exist".format(run_id))
            updated = self.get(run_id)
        if updated is None:
            raise RuntimeError("Research Run disappeared while recording progress")
        return updated

    def finish(
        self,
        run_id: str,
        status: ResearchRunStatus,
        provider_summary: dict,
        error_summary: Optional[str],
        finished_at: datetime,
    ) -> ResearchRunRecord:
        if status == "running":
            raise ValueError("A finished Research Run cannot remain running")
        timestamp = _timestamp(finished_at)
        serialized_summary = json.dumps(
            provider_summary,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        with self.transactions.write_transaction():
            cursor = self.connection.execute(
                """UPDATE research_runs SET status = ?, provider_summary_json = ?,
                       error_summary = ?, finished_at = ?
                   WHERE id = ? AND status = 'running'""",
                (status, serialized_summary, error_summary, timestamp, run_id),
            )
            if cursor.rowcount != 1:
                existing = self.get(run_id)
                if existing is None:
                    raise LookupError("Research Run '{}' does not exist".format(run_id))
                if existing.status != status:
                    raise ValueError("Research Run has already finished as '{}'".format(existing.status))
                return existing
            updated = self.get(run_id)
        if updated is None:
            raise RuntimeError("Research Run disappeared while finishing")
        return updated

    def mark_stale_interrupted(
        self, stale_before: datetime, interrupted_at: datetime
    ) -> tuple[ResearchRunRecord, ...]:
        cutoff = _timestamp(stale_before)
        finished = _timestamp(interrupted_at)
        with self.transactions.write_transaction():
            rows = self.connection.execute(
                """SELECT id FROM research_runs
                   WHERE status = 'running' AND started_at <= ? ORDER BY started_at, id""",
                (cutoff,),
            ).fetchall()
            if rows:
                self.connection.executemany(
                    """UPDATE research_runs SET status = 'interrupted',
                           error_summary = 'Run was still active after the stale threshold',
                           finished_at = ? WHERE id = ? AND status = 'running'""",
                    [(finished, row["id"]) for row in rows],
                )
            recovered = tuple(self.get(row["id"]) for row in rows)
        return tuple(run for run in recovered if run is not None)

    def interrupt_for_request(
        self, request_id: str, interrupted_at: datetime
    ) -> tuple[ResearchRunRecord, ...]:
        finished = _timestamp(interrupted_at)
        with self.transactions.write_transaction():
            rows = self.connection.execute(
                """SELECT id FROM research_runs
                   WHERE request_id = ? AND status = 'running'
                   ORDER BY started_at, id""",
                (request_id,),
            ).fetchall()
            if rows:
                self.connection.executemany(
                    """UPDATE research_runs SET status = 'interrupted',
                           error_summary = 'Run was abandoned with its stale request',
                           finished_at = ? WHERE id = ? AND status = 'running'""",
                    [(finished, row["id"]) for row in rows],
                )
            recovered = tuple(self.get(row["id"]) for row in rows)
        return tuple(run for run in recovered if run is not None)


class ResearchProfileStateRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.transactions = ResearchRepository(connection)

    def get(self, profile_id: str) -> Optional[ResearchProfileStateRecord]:
        row = self.connection.execute(
            "SELECT * FROM research_profile_state WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        return _profile_state_from_row(row) if row else None

    def get_or_create(
        self, profile_id: str, now: datetime
    ) -> ResearchProfileStateRecord:
        timestamp = _timestamp(now)
        with self.transactions.write_transaction():
            self.connection.execute(
                """INSERT OR IGNORE INTO research_profile_state (
                       profile_id, paused_until, last_successful_scheduled_run_at,
                       created_at, updated_at
                   ) VALUES (?, NULL, NULL, ?, ?)""",
                (profile_id, timestamp, timestamp),
            )
            state = self.get(profile_id)
        if state is None:
            raise RuntimeError("Research Profile runtime state was not created")
        return state

    def pause_until(
        self, profile_id: str, paused_until: Optional[datetime], now: datetime
    ) -> ResearchProfileStateRecord:
        timestamp = _timestamp(now)
        paused = _timestamp(paused_until) if paused_until is not None else None
        with self.transactions.write_transaction():
            self.get_or_create(profile_id, now)
            self.connection.execute(
                """UPDATE research_profile_state SET paused_until = ?, updated_at = ?
                   WHERE profile_id = ?""",
                (paused, timestamp, profile_id),
            )
            state = self.get(profile_id)
        if state is None:
            raise RuntimeError("Research Profile runtime state disappeared")
        return state

    def record_successful_scheduled_run(
        self, profile_id: str, completed_at: datetime
    ) -> ResearchProfileStateRecord:
        timestamp = _timestamp(completed_at)
        with self.transactions.write_transaction():
            self.get_or_create(profile_id, completed_at)
            self.connection.execute(
                """UPDATE research_profile_state SET
                       last_successful_scheduled_run_at = ?, updated_at = ?
                   WHERE profile_id = ?""",
                (timestamp, timestamp, profile_id),
            )
            state = self.get(profile_id)
        if state is None:
            raise RuntimeError("Research Profile runtime state disappeared")
        return state


def _run_values(run: ResearchRunRecord) -> tuple:
    return (
        run.id,
        run.profile_id,
        run.request_id,
        run.trigger,
        run.status,
        run.profile_content_hash,
        json.dumps(run.effective_config, ensure_ascii=False, sort_keys=True, allow_nan=False),
        run.fetched_count,
        run.new_work_count,
        run.duplicate_count,
        run.deterministic_filtered_count,
        run.analyzed_count,
        run.surfaced_count,
        json.dumps(run.provider_summary, ensure_ascii=False, sort_keys=True, allow_nan=False),
        run.error_summary,
        run.started_at,
        run.finished_at,
    )


def _run_from_row(row: sqlite3.Row) -> ResearchRunRecord:
    return ResearchRunRecord(
        id=row["id"],
        profile_id=row["profile_id"],
        request_id=row["request_id"],
        trigger=row["trigger"],
        status=row["status"],
        profile_content_hash=row["profile_content_hash"],
        effective_config=json.loads(row["effective_config_json"]),
        fetched_count=row["fetched_count"],
        new_work_count=row["new_work_count"],
        duplicate_count=row["duplicate_count"],
        deterministic_filtered_count=row["deterministic_filtered_count"],
        analyzed_count=row["analyzed_count"],
        surfaced_count=row["surfaced_count"],
        provider_summary=json.loads(row["provider_summary_json"]),
        error_summary=row["error_summary"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _profile_state_from_row(row: sqlite3.Row) -> ResearchProfileStateRecord:
    return ResearchProfileStateRecord(
        profile_id=row["profile_id"],
        paused_until=row["paused_until"],
        last_successful_scheduled_run_at=row["last_successful_scheduled_run_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Research Run timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()
