"""SQLite persistence for Proposals and rejected candidates."""

import hashlib
import json
import sqlite3
from typing import Any, List, Optional, Sequence, Tuple
import uuid

from backend.app.domain.runtime import CandidateType, Draft, Proposal, ProposalStatus, RejectedCandidate
from backend.app.repositories.draft_repository import DraftNotFoundError, DraftRevisionConflict


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
                    id, target_type, target_id, kind, status, base_content_hash,
                    payload_json, diff_text, created_by, provider, model,
                    created_at, reviewed_at, review_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal.id,
                    proposal.target_type,
                    proposal.target_id,
                    proposal.kind,
                    proposal.status,
                    proposal.base_content_hash,
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

    def list(
        self,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Proposal]:
        filters = {
            "target_type": target_type,
            "target_id": target_id,
            "kind": kind,
            "status": status,
        }
        clauses = []
        parameters = []
        for field, value in filters.items():
            if value is not None:
                clauses.append("{} = ?".format(field))
                parameters.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.extend((limit, offset))
        rows = self.connection.execute(
            "SELECT * FROM proposals{} ORDER BY created_at DESC, id LIMIT ? OFFSET ?".format(where),
            parameters,
        ).fetchall()
        return [_proposal_from_row(row) for row in rows]

    def apply_to_draft(
        self,
        proposal_id: str,
        draft_id: str,
        expected_revision: int,
        content: str,
        applied_content_hash: str,
        updated_at: str,
    ) -> tuple[Proposal, Draft]:
        """Update a Draft and its Proposal state as one Runtime transaction."""
        with self.connection:
            draft_row = self.connection.execute(
                "SELECT * FROM drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            if draft_row is None:
                raise DraftNotFoundError("Draft '{}' does not exist".format(draft_id))

            proposal_row = self.connection.execute(
                "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if proposal_row is None:
                raise ProposalNotFoundError(
                    "Proposal '{}' does not exist".format(proposal_id)
                )
            proposal = _proposal_from_row(proposal_row)
            if (
                proposal.target_type != draft_row["entity_type"]
                or proposal.target_id != draft_row["entity_id"]
                or proposal.payload.get("draft_id") != draft_id
            ):
                raise ValueError("Proposal target does not match its Draft")
            if proposal.status not in {"proposed", "drafted"}:
                raise ProposalTransitionError(
                    "Cannot apply a Proposal in '{}' status".format(proposal.status)
                )
            if draft_row["revision"] != expected_revision:
                raise DraftRevisionConflict(expected_revision, draft_row["revision"])

            cursor = self.connection.execute(
                """UPDATE drafts
                   SET content = ?, revision = revision + 1, updated_at = ?
                   WHERE id = ? AND revision = ?""",
                (content, updated_at, draft_id, expected_revision),
            )
            if cursor.rowcount != 1:
                current = self.connection.execute(
                    "SELECT revision FROM drafts WHERE id = ?", (draft_id,)
                ).fetchone()
                if current is None:
                    raise DraftNotFoundError("Draft '{}' does not exist".format(draft_id))
                raise DraftRevisionConflict(expected_revision, current["revision"])

            payload = dict(proposal.payload)
            payload["applied_content_hash"] = applied_content_hash
            payload_json = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            expected_payload_json = json.dumps(
                proposal.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            cursor = self.connection.execute(
                """UPDATE proposals
                   SET status = 'drafted', payload_json = ?, reviewed_at = ?,
                       review_note = ?
                   WHERE id = ? AND status = ? AND payload_json = ?""",
                (
                    payload_json,
                    updated_at,
                    "Applied to Draft",
                    proposal_id,
                    proposal.status,
                    expected_payload_json,
                ),
            )
            if cursor.rowcount != 1:
                raise ProposalTransitionError(
                    "Proposal changed while it was being applied"
                )

            updated_draft_row = self.connection.execute(
                "SELECT * FROM drafts WHERE id = ?", (draft_id,)
            ).fetchone()
            updated_proposal_row = self.connection.execute(
                "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        return _proposal_from_row(updated_proposal_row), _draft_from_row(updated_draft_row)

    def finalize_draft_publish(
        self,
        draft_id: str,
        entity_type: str,
        entity_id: str,
        published_content_hash: str,
        reviewed_at: str,
    ) -> List[Proposal]:
        """Close active proposals tied to a Draft after its canonical publish."""
        active_statuses = ("proposed", "drafted")
        placeholders = ", ".join("?" for _ in active_statuses)
        finalized = []
        with self.connection:
            rows = self.connection.execute(
                """SELECT * FROM proposals
                   WHERE target_type = ? AND target_id = ?
                     AND status IN ({})""".format(placeholders),
                [entity_type, entity_id, *active_statuses],
            ).fetchall()
            for row in rows:
                proposal = _proposal_from_row(row)
                if proposal.payload.get("draft_id") != draft_id:
                    continue
                candidate_hash = proposal.payload.get("applied_content_hash")
                candidate_content = proposal.payload.get("content")
                if (
                    candidate_hash != published_content_hash
                    and isinstance(candidate_content, str)
                ):
                    candidate_hash = hashlib.sha256(
                        candidate_content.encode("utf-8")
                    ).hexdigest()
                status: ProposalStatus = (
                    "merged" if candidate_hash == published_content_hash else "stale"
                )
                note = (
                    "Proposal candidate was published."
                    if status == "merged"
                    else "Draft was published with content different from this Proposal candidate."
                )
                cursor = self.connection.execute(
                    """UPDATE proposals
                       SET status = ?, reviewed_at = ?, review_note = ?
                       WHERE id = ? AND status = ? AND payload_json = ?""",
                    (
                        status,
                        reviewed_at,
                        note,
                        proposal.id,
                        proposal.status,
                        row["payload_json"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise ProposalTransitionError(
                        "Proposal changed while Draft publish was being finalized"
                    )
                updated = self.connection.execute(
                    "SELECT * FROM proposals WHERE id = ?", (proposal.id,)
                ).fetchone()
                finalized.append(_proposal_from_row(updated))
        return finalized

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
        base_content_hash=row["base_content_hash"],
        payload=json.loads(row["payload_json"]),
        diff_text=row["diff_text"],
        created_by=row["created_by"],
        provider=row["provider"],
        model=row["model"],
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
        review_note=row["review_note"],
    )


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


def _rejected_candidate_from_row(row: sqlite3.Row) -> RejectedCandidate:
    return RejectedCandidate(
        id=row["id"],
        candidate_type=row["candidate_type"],
        normalized_value=row["normalized_value"],
        reason=row["reason"],
        scope=row["scope"],
        created_at=row["created_at"],
    )
