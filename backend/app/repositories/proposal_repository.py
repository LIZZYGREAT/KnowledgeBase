"""SQLite persistence for Proposals and rejected candidates."""

import json
import sqlite3
from typing import Any, Dict, Optional, Sequence, Tuple
import uuid

from backend.app.domain.runtime import CandidateType, Proposal, ProposalStatus, RejectedCandidate


class ProposalNotFoundError(LookupError):
    pass


class ProposalTransitionError(RuntimeError):
    pass


class ProposalRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create(self, proposal: Proposal) -> Proposal:
        payload_json = json.dumps(
            proposal.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self.connection:
            self.connection.execute(
                """INSERT INTO proposals (
                    id, target_type, target_id, kind, status, base_revision,
                    payload_json, diff_text, created_by, provider, model,
                    created_at, reviewed_at, review_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal.id,
                    proposal.target_type,
                    proposal.target_id,
                    proposal.kind,
                    proposal.status,
                    proposal.base_revision,
                    payload_json,
                    proposal.diff_text,
                    proposal.created_by,
                    proposal.provider,
                    proposal.model,
                    proposal.created_at,
                    proposal.reviewed_at,
                    proposal.review_note,
                ),
            )
        return self.get(proposal.id)

    def get(self, proposal_id: str) -> Optional[Proposal]:
        row = self.connection.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        return _proposal_from_row(row) if row else None

    def update_draft(
        self, proposal_id: str, payload: Dict[str, Any], diff_text: Optional[str]
    ) -> Proposal:
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE proposals
                   SET status = 'drafted', payload_json = ?, diff_text = ?
                   WHERE id = ? AND status IN ('proposed', 'drafted')""",
                (payload_json, diff_text, proposal_id),
            )
        if cursor.rowcount != 1:
            proposal = self.get(proposal_id)
            if proposal is None:
                raise ProposalNotFoundError("Proposal '{}' does not exist".format(proposal_id))
            raise ProposalTransitionError(
                "Cannot draft a Proposal in '{}' status".format(proposal.status)
            )
        return self.get(proposal_id)

    def transition(
        self,
        proposal_id: str,
        allowed_statuses: Sequence[ProposalStatus],
        status: ProposalStatus,
        reviewed_at: str,
        review_note: Optional[str] = None,
        rejected_candidate: Optional[Tuple[CandidateType, str, str]] = None,
    ) -> Proposal:
        placeholders = ", ".join("?" for _ in allowed_statuses)
        parameters = [status, reviewed_at, review_note, proposal_id, *allowed_statuses]
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE proposals
                   SET status = ?, reviewed_at = ?, review_note = ?
                   WHERE id = ? AND status IN ({})""".format(placeholders),
                parameters,
            )
            if cursor.rowcount != 1:
                proposal = self.get(proposal_id)
                if proposal is None:
                    raise ProposalNotFoundError(
                        "Proposal '{}' does not exist".format(proposal_id)
                    )
                raise ProposalTransitionError(
                    "Cannot change Proposal from '{}' to '{}'".format(
                        proposal.status, status
                    )
                )
            if rejected_candidate is not None:
                candidate_type, normalized_value, scope = rejected_candidate
                self._upsert_rejected_candidate(
                    candidate_type,
                    normalized_value,
                    review_note,
                    scope,
                    reviewed_at,
                )
        return self.get(proposal_id)

    def record_rejected_candidate(
        self,
        candidate_type: CandidateType,
        normalized_value: str,
        reason: str,
        scope: str,
        created_at: str,
    ) -> RejectedCandidate:
        with self.connection:
            self._upsert_rejected_candidate(
                candidate_type, normalized_value, reason, scope, created_at
            )
        row = self.connection.execute(
            """SELECT * FROM rejected_candidates
               WHERE candidate_type = ? AND normalized_value = ? AND scope = ?""",
            (candidate_type, normalized_value, scope),
        ).fetchone()
        return _rejected_candidate_from_row(row)

    def is_rejected_candidate(
        self, candidate_type: CandidateType, normalized_value: str, scope: str
    ) -> bool:
        row = self.connection.execute(
            """SELECT 1 FROM rejected_candidates
               WHERE candidate_type = ? AND normalized_value = ? AND scope = ?""",
            (candidate_type, normalized_value, scope),
        ).fetchone()
        return row is not None

    def _upsert_rejected_candidate(
        self,
        candidate_type: CandidateType,
        normalized_value: str,
        reason: Optional[str],
        scope: str,
        created_at: str,
    ) -> None:
        self.connection.execute(
            """INSERT INTO rejected_candidates (
                   id, candidate_type, normalized_value, reason, scope, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(candidate_type, normalized_value, scope)
               DO UPDATE SET reason = excluded.reason""",
            (
                uuid.uuid4().hex,
                candidate_type,
                normalized_value,
                reason or "Rejected",
                scope,
                created_at,
            ),
        )


def _proposal_from_row(row: sqlite3.Row) -> Proposal:
    return Proposal(
        id=row["id"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        kind=row["kind"],
        status=row["status"],
        base_revision=row["base_revision"],
        payload=json.loads(row["payload_json"]),
        diff_text=row["diff_text"],
        created_by=row["created_by"],
        provider=row["provider"],
        model=row["model"],
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
        review_note=row["review_note"],
    )


def _rejected_candidate_from_row(row: sqlite3.Row) -> RejectedCandidate:
    return RejectedCandidate(
        id=row["id"],
        candidate_type=row["candidate_type"],
        normalized_value=row["normalized_value"],
        reason=row["reason"],
        scope=row["scope"],
        created_at=row["created_at"],
    )
