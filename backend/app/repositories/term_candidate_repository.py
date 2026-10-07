"""SQLite persistence for Term Candidates, Evidence, relations, and Reject Memory."""

import sqlite3
import json
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
            """SELECT e.*,
                      COALESCE(e.origin_title, d.title, s.title, rw.title) AS origin_title,
                      EXISTS (
                          SELECT 1 FROM rejected_candidates r
                          JOIN term_candidates c ON c.id = e.candidate_id
                          WHERE r.candidate_type = 'term'
                            AND r.normalized_value = c.normalized_name
                            AND r.scope IN (
                                'global',
                                'origin:' || e.origin_type || ':' || e.origin_id
                            )
                      ) AS origin_rejected
               FROM term_candidate_evidence e
               LEFT JOIN document_index d
                 ON e.origin_type = 'document' AND d.entity_id = e.origin_id
               LEFT JOIN source_index s
                 ON e.origin_type = 'source' AND s.entity_id = e.origin_id
               LEFT JOIN research_works rw
                 ON e.origin_type = 'research_work' AND rw.id = e.origin_id
               WHERE e.candidate_id = ?
               ORDER BY e.discovered_at, e.id""",
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
                       created_at, updated_at, reviewed_at, recommendation_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        discovery_assessment=None,
    ) -> TermCandidateRecord:
        with self.connection:
            self._insert_evidence(candidate_id, evidence, updated_at)
            self.connection.execute(
                """UPDATE term_candidates
                   SET updated_at = ?,
                       suggested_term_id = COALESCE(suggested_term_id, ?),
                       recommendation_json = COALESCE(recommendation_json, ?)
                   WHERE id = ?""",
                (
                    updated_at,
                    suggested_term_id,
                    _assessment_json(discovery_assessment),
                    candidate_id,
                ),
            )
        return self.get_candidate(candidate_id)

    def is_rejected(self, normalized_name: str, scope: str = "global") -> bool:
        row = self.connection.execute(
            """SELECT 1 FROM rejected_candidates
               WHERE candidate_type = 'term' AND normalized_value = ? AND scope = ?""",
            (normalized_name, scope),
        ).fetchone()
        return row is not None

    def rejected_names(self, scopes: list[str]) -> list[str]:
        if not scopes:
            return []
        placeholders = ", ".join("?" for _ in scopes)
        rows = self.connection.execute(
            """SELECT DISTINCT normalized_value FROM rejected_candidates
               WHERE candidate_type = 'term' AND scope IN ({})
               ORDER BY normalized_value""".format(placeholders),
            scopes,
        ).fetchall()
        return [row["normalized_value"] for row in rows]

    def has_relation(self, entity_type: str, entity_id: str, term_id: str) -> bool:
        return self.connection.execute(
            """SELECT 1 FROM term_entity_relations
               WHERE entity_type = ? AND entity_id = ? AND term_id = ?""",
            (entity_type, entity_id, term_id),
        ).fetchone() is not None

    def has_accepted_candidate_evidence(
        self, normalized_name: str, origin_type: str, origin_id: str
    ) -> bool:
        return self.connection.execute(
            """SELECT 1
               FROM term_candidates c
               JOIN term_candidate_evidence e ON e.candidate_id = c.id
               WHERE c.normalized_name = ? AND c.status = 'accepted'
                 AND e.origin_type = ? AND e.origin_id = ?
               LIMIT 1""",
            (normalized_name, origin_type, origin_id),
        ).fetchone() is not None

    def count_for_research_works(self, work_ids: list[str]) -> dict[str, int]:
        unique_ids = list(dict.fromkeys(work_ids))
        if not unique_ids:
            return {}
        placeholders = ", ".join("?" for _ in unique_ids)
        rows = self.connection.execute(
            """SELECT e.origin_id, COUNT(DISTINCT e.candidate_id) AS count
               FROM term_candidate_evidence e
               WHERE e.origin_type = 'research_work'
                 AND e.origin_id IN ({})
               GROUP BY e.origin_id""".format(placeholders),
            tuple(unique_ids),
        ).fetchall()
        return {row["origin_id"]: int(row["count"]) for row in rows}

    def get_document_analysis_state(self, document_id: str) -> Optional[dict]:
        row = self.connection.execute(
            "SELECT * FROM document_term_analysis_state WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def save_document_analysis_state(self, state: dict) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO document_term_analysis_state (
                       document_id, analyzed_content_hash, prompt_version,
                       provider, model, analyzed_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(document_id) DO UPDATE SET
                       analyzed_content_hash = excluded.analyzed_content_hash,
                       prompt_version = excluded.prompt_version,
                       provider = excluded.provider,
                       model = excluded.model,
                       analyzed_at = excluded.analyzed_at""",
                (
                    state["document_id"],
                    state["analyzed_content_hash"],
                    state["prompt_version"],
                    state["provider"],
                    state["model"],
                    state["analyzed_at"],
                ),
            )

    def mark_candidate_drafting(
        self, candidate_id: str, draft_id: str, updated_at: str
    ) -> TermCandidateRecord:
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE term_candidates
                   SET status = 'drafting', draft_id = ?, updated_at = ?
                   WHERE id = ? AND status IN ('pending', 'drafting')""",
                (draft_id, updated_at, candidate_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Only an open Term Candidate can enter drafting")
        return self.get_candidate(candidate_id)

    def reset_candidate_draft(self, draft_id: str, updated_at: str) -> Optional[TermCandidateRecord]:
        row = self.connection.execute(
            "SELECT id FROM term_candidates WHERE draft_id = ? AND status = 'drafting'",
            (draft_id,),
        ).fetchone()
        if row is None:
            return None
        candidate_id = row["id"]
        with self.connection:
            self.connection.execute(
                """UPDATE term_candidates
                   SET status = 'pending', draft_id = NULL, updated_at = ?, reviewed_at = NULL
                   WHERE id = ? AND draft_id = ? AND status = 'drafting'""",
                (updated_at, candidate_id, draft_id),
            )
        return self.get_candidate(candidate_id)

    def list_candidates_for_draft(self, draft_id: str) -> list[TermCandidateRecord]:
        rows = self.connection.execute(
            """SELECT * FROM term_candidates
               WHERE draft_id = ? AND status = 'drafting'
               ORDER BY created_at, id""",
            (draft_id,),
        ).fetchall()
        return [_candidate_from_row(row) for row in rows]

    def finalize_candidate_draft(
        self,
        candidate_id: str,
        draft_id: str,
        term_id: str,
        relations: list[TermEntityRelation],
        reviewed_at: str,
    ) -> Optional[TermCandidateRecord]:
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE term_candidates
                   SET status = 'accepted', suggested_term_id = ?, accepted_term_id = ?,
                       updated_at = ?, reviewed_at = ?
                   WHERE id = ? AND draft_id = ? AND status = 'drafting'""",
                (term_id, term_id, reviewed_at, reviewed_at, candidate_id, draft_id),
            )
            if cursor.rowcount != 1:
                return None
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
        return self.get_candidate(candidate_id)

    def reject_candidate(
        self,
        candidate_id: str,
        scopes: list[str],
        reason: Optional[str],
        reviewed_at: str,
        close_candidate: bool = True,
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
                   SET status = ?, updated_at = ?, reviewed_at = ?
                   WHERE id = ?""",
                (
                    "rejected" if close_candidate else "pending",
                    reviewed_at,
                    reviewed_at,
                    candidate_id,
                ),
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
                       origin_title, context_excerpt, confidence, rationale, discovered_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(candidate_id, origin_type, origin_id, mention)
                   DO UPDATE SET origin_title = COALESCE(
                                     excluded.origin_title, term_candidate_evidence.origin_title
                                 ),
                                 context_excerpt = excluded.context_excerpt,
                                 confidence = excluded.confidence,
                                 rationale = excluded.rationale,
                                 discovered_at = excluded.discovered_at""",
                (
                    uuid.uuid4().hex,
                    candidate_id,
                    item.origin_type,
                    item.origin_id,
                    item.mention,
                    item.origin_title,
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
        _assessment_json(candidate.discovery_assessment),
    )


def _candidate_from_row(row: sqlite3.Row) -> TermCandidateRecord:
    data = dict(row)
    encoded_assessment = data.pop("recommendation_json", None)
    data["discovery_assessment"] = (
        json.loads(encoded_assessment) if encoded_assessment else None
    )
    return TermCandidateRecord.model_validate(data)


def _assessment_json(assessment) -> Optional[str]:
    if assessment is None:
        return None
    value = assessment.model_dump(mode="json") if hasattr(assessment, "model_dump") else assessment
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _evidence_from_row(row: sqlite3.Row) -> TermCandidateEvidence:
    data = dict(row)
    if "origin_rejected" in data:
        data["origin_rejected"] = bool(data["origin_rejected"])
    return TermCandidateEvidence.model_validate(data)
