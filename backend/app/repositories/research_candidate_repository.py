"""Runtime persistence and capacity-safe transitions for Research Candidates."""

from datetime import datetime
import sqlite3
from typing import Optional

from backend.app.domain.research_runtime import (
    ResearchCandidateRecord,
    ResearchCandidateStatus,
    ResearchDismissReason,
)
from backend.app.repositories.research_repository import ResearchRepository


class ResearchCandidateRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.transactions = ResearchRepository(connection)

    def get(self, candidate_id: str) -> Optional[ResearchCandidateRecord]:
        row = self.connection.execute(
            "SELECT * FROM research_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        return _candidate_from_row(row) if row else None

    def get_for_work(
        self, work_id: str, profile_id: str
    ) -> Optional[ResearchCandidateRecord]:
        row = self.connection.execute(
            """SELECT * FROM research_candidates
               WHERE work_id = ? AND profile_id = ?""",
            (work_id, profile_id),
        ).fetchone()
        return _candidate_from_row(row) if row else None

    def list_for_profile(
        self,
        profile_id: str,
        status: Optional[ResearchCandidateStatus] = None,
        limit: int = 100,
    ) -> list[ResearchCandidateRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Candidate list limit must be between 1 and 500")
        if status is None:
            rows = self.connection.execute(
                """SELECT * FROM research_candidates WHERE profile_id = ?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (profile_id, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """SELECT * FROM research_candidates WHERE profile_id = ? AND status = ?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (profile_id, status, limit),
            ).fetchall()
        return [_candidate_from_row(row) for row in rows]

    def count_new(self, profile_id: str) -> int:
        row = self.connection.execute(
            """SELECT COUNT(*) AS count FROM research_candidates
               WHERE profile_id = ? AND status = 'new'""",
            (profile_id,),
        ).fetchone()
        return int(row["count"])

    def create_if_capacity(
        self, candidate: ResearchCandidateRecord, max_new_candidates: int
    ) -> tuple[Optional[ResearchCandidateRecord], bool, bool]:
        with self.transactions.write_transaction():
            existing = self.get_for_work(candidate.work_id, candidate.profile_id)
            if existing is not None:
                return existing, False, False
            if self.count_new(candidate.profile_id) >= max_new_candidates:
                return None, False, True
            self.connection.execute(
                """INSERT INTO research_candidates (
                       id, work_id, profile_id, status, primary_lens_id, analysis_id,
                       user_note, dismiss_reason, created_at, updated_at,
                       first_viewed_at, last_viewed_at, decided_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _candidate_values(candidate),
            )
            return candidate, True, False

    def transition(
        self,
        candidate_id: str,
        allowed_statuses: tuple[ResearchCandidateStatus, ...],
        status: ResearchCandidateStatus,
        now: datetime,
        dismiss_reason: Optional[ResearchDismissReason] = None,
        user_note: Optional[str] = None,
        update_user_note: bool = False,
        decided_at: Optional[datetime] = None,
    ) -> ResearchCandidateRecord:
        with self.transactions.write_transaction():
            candidate = self.get(candidate_id)
            if candidate is None:
                raise LookupError("Research Candidate '{}' does not exist".format(candidate_id))
            if candidate.status not in allowed_statuses:
                raise ValueError(
                    "Cannot move Research Candidate from '{}' to '{}'".format(
                        candidate.status, status
                    )
                )
            next_note = user_note if update_user_note else candidate.user_note
            decision_text = decided_at.isoformat() if decided_at else None
            self.connection.execute(
                """UPDATE research_candidates SET status = ?, user_note = ?,
                       dismiss_reason = ?, updated_at = ?, decided_at = ?
                   WHERE id = ?""",
                (
                    status,
                    next_note,
                    dismiss_reason,
                    now.isoformat(),
                    decision_text,
                    candidate_id,
                ),
            )
            updated = self.get(candidate_id)
        if updated is None:
            raise RuntimeError("Research Candidate disappeared during transition")
        return updated

    def update_user_note(
        self, candidate_id: str, user_note: Optional[str], now: datetime
    ) -> ResearchCandidateRecord:
        with self.transactions.write_transaction():
            candidate = self.get(candidate_id)
            if candidate is None:
                raise LookupError("Research Candidate '{}' does not exist".format(candidate_id))
            self.connection.execute(
                "UPDATE research_candidates SET user_note = ?, updated_at = ? WHERE id = ?",
                (user_note, now.isoformat(), candidate_id),
            )
            updated = self.get(candidate_id)
        if updated is None:
            raise RuntimeError("Research Candidate disappeared while updating its note")
        return updated

    def mark_viewed(self, candidate_id: str, now: datetime) -> ResearchCandidateRecord:
        timestamp = now.isoformat()
        with self.transactions.write_transaction():
            candidate = self.get(candidate_id)
            if candidate is None:
                raise LookupError("Research Candidate '{}' does not exist".format(candidate_id))
            self.connection.execute(
                """UPDATE research_candidates SET
                       first_viewed_at = COALESCE(first_viewed_at, ?),
                       last_viewed_at = ?, updated_at = ? WHERE id = ?""",
                (timestamp, timestamp, timestamp, candidate_id),
            )
            updated = self.get(candidate_id)
        if updated is None:
            raise RuntimeError("Research Candidate disappeared while recording its view")
        return updated


def _candidate_values(candidate: ResearchCandidateRecord) -> tuple:
    return (
        candidate.id,
        candidate.work_id,
        candidate.profile_id,
        candidate.status,
        candidate.primary_lens_id,
        candidate.analysis_id,
        candidate.user_note,
        candidate.dismiss_reason,
        candidate.created_at,
        candidate.updated_at,
        candidate.first_viewed_at,
        candidate.last_viewed_at,
        candidate.decided_at,
    )


def _candidate_from_row(row: sqlite3.Row) -> ResearchCandidateRecord:
    return ResearchCandidateRecord(
        id=row["id"],
        work_id=row["work_id"],
        profile_id=row["profile_id"],
        status=row["status"],
        primary_lens_id=row["primary_lens_id"],
        analysis_id=row["analysis_id"],
        user_note=row["user_note"],
        dismiss_reason=row["dismiss_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        first_viewed_at=row["first_viewed_at"],
        last_viewed_at=row["last_viewed_at"],
        decided_at=row["decided_at"],
    )
