"""SQLite persistence for Term Candidates, Evidence, relations, and Reject Memory."""

import sqlite3
import uuid
from typing import Optional

from backend.app.domain.term_runtime import (
    TermCandidateEvidence,
    TermCandidateEvidenceInput,
    TermCandidateRecord,
    TermEntityRelation,
)


class TermCandidateRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def list_candidates(self, status: Optional[str] = None) -> list[TermCandidateRecord]:
        if status is None:
            rows = self.connection.execute(
                "SELECT * FROM term_candidates ORDER BY updated_at DESC, id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM term_candidates WHERE status = ? "
                "ORDER BY updated_at DESC, id",
                (status,),
            ).fetchall()
        return [_candidate_from_row(row) for row in rows]

    def get_candidate(self, candidate_id: str) -> Optional[TermCandidateRecord]:
        row = self.connection.execute(
            "SELECT * FROM term_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        return _candidate_from_row(row) if row is not None else None

    def get_evidence(self, candidate_id: str) -> list[TermCandidateEvidence]:
        rows = self.connection.execute(
            "SELECT * FROM term_candidate_evidence WHERE candidate_id = ? "
            "ORDER BY discovered_at, id",
            (candidate_id,),
        ).fetchall()
        return [_evidence_from_row(row) for row in rows]

    def find_open_candidate(self, normalized_name: str) -> Optional[TermCandidateRecord]:
        row = self.connection.execute(
            """SELECT * FROM term_candidates
               WHERE normalized_name = ? AND status IN ('pending', 'drafting')
               ORDER BY created_at, id LIMIT 1""",
            (normalized_name,),
        ).fetchone()
        return _candidate_from_row(row) if row is not None else None

    def create_candidate(
        self, candidate: TermCandidateRecord, evidence: list[TermCandidateEvidenceInput]
    ) -> TermCandidateRecord:
        with self.connection:
            self.connection.execute(
                """INSERT INTO term_candidates (
                       id, normalized_name, display_name, suggested_type,
                       suggested_term_id, status, draft_id, accepted_term_id,
                       created_at, updated_at, reviewed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _candidate_values(candidate),
            )
            self._insert_evidence(candidate.id, evidence, candidate.created_at)
        return self.get_candidate(candidate.id)

    def add_evidence(
        self,
        candidate_id: str,
        evidence: list[TermCandidateEvidenceInput],
        updated_at: str,
        suggested_term_id: Optional[str] = None,
    ) -> TermCandidateRecord:
        with self.connection:
            self._insert_evidence(candidate_id, evidence, updated_at)
            self.connection.execute(
                """UPDATE term_candidates
                   SET updated_at = ?,
                       suggested_term_id = COALESCE(suggested_term_id, ?)
                   WHERE id = ?""",
                (updated_at, suggested_term_id, candidate_id),
            )
        return self.get_candidate(candidate_id)

    def is_rejected(self, normalized_name: str, scope: str = "global") -> bool:
        row = self.connection.execute(
            """SELECT 1 FROM rejected_candidates
               WHERE candidate_type = 'term' AND normalized_value = ? AND scope = ?""",
            (normalized_name, scope),
        ).fetchone()
        return row is not None

    def reject_candidate(
        self,
        candidate_id: str,
        scopes: list[str],
        reason: Optional[str],
        reviewed_at: str,
    ) -> TermCandidateRecord:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Term Candidate '{}' does not exist".format(candidate_id))
        if candidate.status not in {"pending", "drafting"}:
            raise ValueError("Only open Term Candidates can be rejected")
        if not scopes:
            raise ValueError("A local rejection requires at least one Candidate origin")

        with self.connection:
            for scope in scopes:
                self.connection.execute(
                    """INSERT INTO rejected_candidates (
                           id, candidate_type, normalized_value, reason, scope, created_at
                       ) VALUES (?, 'term', ?, ?, ?, ?)
                       ON CONFLICT(candidate_type, normalized_value, scope)
                       DO UPDATE SET reason = excluded.reason""",
                    (
                        uuid.uuid4().hex,
                        candidate.normalized_name,
                        reason or "Rejected",
                        scope,
                        reviewed_at,
                    ),
                )
            self.connection.execute(
                """UPDATE term_candidates
                   SET status = 'rejected', updated_at = ?, reviewed_at = ?
                   WHERE id = ?""",
                (reviewed_at, reviewed_at, candidate_id),
            )
        return self.get_candidate(candidate_id)

    def accept_existing(
        self,
        candidate_id: str,
        term_id: str,
        relations: list[TermEntityRelation],
        reviewed_at: str,
    ) -> TermCandidateRecord:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Term Candidate '{}' does not exist".format(candidate_id))
        if candidate.status not in {"pending", "drafting"}:
            raise ValueError("Only open Term Candidates can be accepted")

        with self.connection:
            for relation in relations:
                self.connection.execute(
                    """INSERT INTO term_entity_relations (
                           id, entity_type, entity_id, term_id,
                           created_from_candidate_id, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(entity_type, entity_id, term_id) DO NOTHING""",
                    (
                        relation.id,
                        relation.entity_type,
                        relation.entity_id,
                        term_id,
                        candidate_id,
                        relation.created_at,
                    ),
                )
            self.connection.execute(
                """UPDATE term_candidates
                   SET suggested_term_id = ?, accepted_term_id = ?, status = 'accepted',
                       updated_at = ?, reviewed_at = ?
                   WHERE id = ?""",
                (term_id, term_id, reviewed_at, reviewed_at, candidate_id),
            )
        return self.get_candidate(candidate_id)

    def migrate_merged_terms(
        self, loser_term_ids: list[str], survivor_term_id: str, merged_at: str
    ) -> None:
        """Move every Runtime reference in the caller's open SQLite transaction."""
        placeholders = ", ".join("?" for _ in loser_term_ids)
        parameters = tuple(loser_term_ids)
        rows = self.connection.execute(
            """SELECT entity_type, entity_id, term_id,
                      created_from_candidate_id, created_at
               FROM term_entity_relations
               WHERE term_id IN ({})""".format(placeholders),
            parameters,
        ).fetchall()
        for row in rows:
            self.connection.execute(
                """INSERT INTO term_entity_relations (
                       id, entity_type, entity_id, term_id,
                       created_from_candidate_id, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(entity_type, entity_id, term_id) DO NOTHING""",
                (
                    uuid.uuid4().hex,
                    row["entity_type"],
                    row["entity_id"],
                    survivor_term_id,
                    row["created_from_candidate_id"],
                    row["created_at"],
                ),
            )
        self.connection.execute(
            "DELETE FROM term_entity_relations WHERE term_id IN ({})".format(
                placeholders
            ),
            parameters,
        )
        self.connection.execute(
            """UPDATE term_candidates
               SET suggested_term_id = ?
               WHERE suggested_term_id IN ({})""".format(placeholders),
            (survivor_term_id,) + parameters,
        )
        self.connection.execute(
            """UPDATE term_candidates
               SET accepted_term_id = ?
               WHERE accepted_term_id IN ({})""".format(placeholders),
            (survivor_term_id,) + parameters,
        )
        for loser_term_id in loser_term_ids:
            self.connection.execute(
                """INSERT INTO term_merge_history (
                       id, loser_term_id, survivor_term_id, merged_at
                   ) VALUES (?, ?, ?, ?)""",
                (uuid.uuid4().hex, loser_term_id, survivor_term_id, merged_at),
            )

    def _insert_evidence(
        self,
        candidate_id: str,
        evidence: list[TermCandidateEvidenceInput],
        discovered_at: str,
    ) -> None:
        for item in evidence:
            self.connection.execute(
                """INSERT INTO term_candidate_evidence (
                       id, candidate_id, origin_type, origin_id, mention,
                       context_excerpt, confidence, rationale, discovered_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(candidate_id, origin_type, origin_id, mention) DO NOTHING""",
                (
                    uuid.uuid4().hex,
                    candidate_id,
                    item.origin_type,
                    item.origin_id,
                    item.mention,
                    item.context_excerpt,
                    item.confidence,
                    item.rationale,
                    discovered_at,
                ),
            )


def _candidate_values(candidate: TermCandidateRecord) -> tuple:
    return (
        candidate.id,
        candidate.normalized_name,
        candidate.display_name,
        candidate.suggested_type,
        candidate.suggested_term_id,
        candidate.status,
        candidate.draft_id,
        candidate.accepted_term_id,
        candidate.created_at,
        candidate.updated_at,
        candidate.reviewed_at,
    )


def _candidate_from_row(row: sqlite3.Row) -> TermCandidateRecord:
    return TermCandidateRecord.model_validate(dict(row))


def _evidence_from_row(row: sqlite3.Row) -> TermCandidateEvidence:
    return TermCandidateEvidence.model_validate(dict(row))
