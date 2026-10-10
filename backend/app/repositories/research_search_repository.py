"""Persistence for Research search watermarks and control audit events."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from typing import Iterator, Optional

from backend.app.domain.research_runtime import ResearchSearchStateRecord


class ResearchSearchRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def history_checkpoint(self, profile_id, lens_id, provider, query_key):
        row = self.connection.execute(
            "SELECT history_checkpoint_json FROM research_search_state WHERE profile_id=? AND lens_id=? AND provider=? AND query_key=?",
            (profile_id, lens_id, provider, query_key),
        ).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def save_history_checkpoint(self, plan, window_start, cursor):
        with self.write_transaction():
            self.connection.execute(
                "UPDATE research_search_state SET history_checkpoint_json=? WHERE profile_id=? AND lens_id=? AND provider=? AND query_key=?",
                (json.dumps({"start": window_start.isoformat(), "cursor": cursor}) if window_start else None,
                 plan.profile_id, plan.lens_id, plan.provider, plan.query_key),
            )

    def get_state(
        self, profile_id: str, lens_id: str, provider: str, query_key: str
    ) -> Optional[ResearchSearchStateRecord]:
        row = self.connection.execute(
            """SELECT * FROM research_search_state
               WHERE profile_id = ? AND lens_id = ? AND provider = ? AND query_key = ?""",
            (profile_id, lens_id, provider, query_key),
        ).fetchone()
        return _state_from_row(row) if row else None

    def record_attempt(
        self,
        profile_id: str,
        lens_id: str,
        provider: str,
        query_key: str,
        query_text: str,
        attempted_at: str,
    ) -> ResearchSearchStateRecord:
        with self.write_transaction():
            self.connection.execute(
                """INSERT INTO research_search_state (
                       profile_id, lens_id, provider, query_key, query_text,
                       completed_through, last_attempt_at, last_success_at,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?)
                   ON CONFLICT(profile_id, lens_id, provider, query_key) DO UPDATE SET
                       query_text = excluded.query_text,
                       last_attempt_at = excluded.last_attempt_at,
                       updated_at = excluded.updated_at""",
                (
                    profile_id,
                    lens_id,
                    provider,
                    query_key,
                    query_text,
                    attempted_at,
                    attempted_at,
                    attempted_at,
                ),
            )
            state = self.get_state(profile_id, lens_id, provider, query_key)
            if state is None:
                raise RuntimeError("Research search state was not created")
            return state

    def complete_slice(
        self,
        profile_id: str,
        lens_id: str,
        provider: str,
        query_key: str,
        completed_through: str,
        completed_at: str,
    ) -> ResearchSearchStateRecord:
        with self.write_transaction():
            state = self.get_state(profile_id, lens_id, provider, query_key)
            if state is None:
                raise LookupError("Research search attempt must be recorded before completion")
            old_watermark = _parse_timestamp(state.completed_through)
            new_watermark = _parse_timestamp(completed_through)
            stored_watermark = (
                completed_through
                if old_watermark is None or new_watermark > old_watermark
                else state.completed_through
            )
            old_success = _parse_timestamp(state.last_success_at)
            new_success = _parse_timestamp(completed_at)
            stored_success = (
                completed_at
                if old_success is None or new_success >= old_success
                else state.last_success_at
            )
            stored_updated = (
                completed_at
                if _parse_timestamp(completed_at) >= _parse_timestamp(state.updated_at)
                else state.updated_at
            )
            self.connection.execute(
                """UPDATE research_search_state SET
                       completed_through = ?, last_success_at = ?, updated_at = ?
                   WHERE profile_id = ? AND lens_id = ? AND provider = ? AND query_key = ?""",
                (
                    stored_watermark,
                    stored_success,
                    stored_updated,
                    profile_id,
                    lens_id,
                    provider,
                    query_key,
                ),
            )
            updated = self.get_state(profile_id, lens_id, provider, query_key)
            if updated is None:
                raise RuntimeError("Research search state disappeared during completion")
            return updated

    def advance_streams_to_floor(
        self,
        profile_id: str,
        state_specs: tuple[tuple[str, str, str, str], ...],
        floor: str,
        audit_strategy: Optional[str] = None,
        recorded_at: Optional[str] = None,
    ) -> tuple[ResearchSearchStateRecord, ...]:
        """Advance only the selected search streams to a durable lower boundary."""
        with self.write_transaction():
            previous = []
            updated_states = []
            requested = _parse_timestamp(floor)
            if requested is None:
                raise ValueError("Research watermark floor must be a valid timestamp")
            recorded_timestamp = floor if recorded_at is None else recorded_at
            recorded = _parse_timestamp(recorded_timestamp)
            if recorded is None:
                raise ValueError("Research watermark update time must be a valid timestamp")
            for lens_id, provider, query_key, query_text in state_specs:
                state = self.get_state(profile_id, lens_id, provider, query_key)
                previous.append(
                    {
                        "lens_id": lens_id,
                        "provider": provider,
                        "query_key": query_key,
                        "completed_through": state.completed_through if state else None,
                    }
                )
                watermark = floor
                overlap_floor = floor
                if state is not None:
                    old_watermark = _parse_timestamp(state.completed_through)
                    if old_watermark is not None and old_watermark > requested:
                        watermark = state.completed_through
                    old_overlap_floor = _parse_timestamp(state.overlap_floor)
                    if old_overlap_floor is not None and old_overlap_floor > requested:
                        overlap_floor = state.overlap_floor
                    old_updated = _parse_timestamp(state.updated_at)
                    updated_at = (
                        state.updated_at
                        if old_updated is not None and old_updated > recorded
                        else recorded_timestamp
                    )
                    self.connection.execute(
                        """UPDATE research_search_state SET query_text = ?,
                               completed_through = ?, overlap_floor = ?, updated_at = ?
                           WHERE profile_id = ? AND lens_id = ? AND provider = ? AND query_key = ?""",
                        (
                            query_text,
                            watermark,
                            overlap_floor,
                            updated_at,
                            profile_id,
                            lens_id,
                            provider,
                            query_key,
                        ),
                    )
                else:
                    self.connection.execute(
                        """INSERT INTO research_search_state (
                               profile_id, lens_id, provider, query_key, query_text,
                               completed_through, overlap_floor, last_attempt_at, last_success_at,
                               created_at, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
                        (
                            profile_id,
                            lens_id,
                            provider,
                            query_key,
                            query_text,
                            watermark,
                            overlap_floor,
                            recorded_timestamp,
                            recorded_timestamp,
                        ),
                    )
                updated = self.get_state(profile_id, lens_id, provider, query_key)
                if updated is not None:
                    updated_states.append(updated)

            if audit_strategy is not None:
                payload = json.dumps(
                    {
                        "strategy": audit_strategy,
                        "previous_watermarks": previous,
                        "new_watermark": floor,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                self.connection.execute(
                    """INSERT INTO research_control_events (
                           id, profile_id, event_type, payload_json, created_at
                       ) VALUES (?, ?, 'watermark_skip', ?, ?)""",
                    (str(uuid.uuid4()), profile_id, payload, recorded_timestamp),
                )
            return tuple(updated_states)

    def list_control_events(self, profile_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT id, profile_id, event_type, payload_json, created_at
               FROM research_control_events WHERE profile_id = ?
               ORDER BY created_at, id""",
            (profile_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "profile_id": row["profile_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        if self.connection.in_transaction:
            savepoint = "research_search_{}".format(uuid.uuid4().hex)
            self.connection.execute("SAVEPOINT {}".format(savepoint))
            try:
                yield
            except BaseException:
                self.connection.execute("ROLLBACK TO SAVEPOINT {}".format(savepoint))
                self.connection.execute("RELEASE SAVEPOINT {}".format(savepoint))
                raise
            else:
                self.connection.execute("RELEASE SAVEPOINT {}".format(savepoint))
            return
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()


def _state_from_row(row: sqlite3.Row) -> ResearchSearchStateRecord:
    return ResearchSearchStateRecord(
        profile_id=row["profile_id"],
        lens_id=row["lens_id"],
        provider=row["provider"],
        query_key=row["query_key"],
        query_text=row["query_text"],
        completed_through=row["completed_through"],
        overlap_floor=row["overlap_floor"],
        last_attempt_at=row["last_attempt_at"],
        last_success_at=row["last_success_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Stored Research timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)
