"""Human-reviewed Term Candidate resolution and lifecycle operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import uuid
from typing import Optional

from backend.app.domain.term_runtime import (
    TermCandidateDetail,
    TermCandidateEvidenceInput,
    TermCandidateRecord,
    TermEntityRelation,
    TermType,
)
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.services.resolution import Resolution, normalize_key
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver


class TermCandidateConflict(RuntimeError):
    """Raised when a Candidate cannot make the requested lifecycle transition."""


@dataclass(frozen=True)
class CandidateResolution:
    status: str
    normalized_name: str
    term_id: Optional[str] = None
    candidate_id: Optional[str] = None
    matched_by: Optional[str] = None


class TermCandidateService:
    def __init__(
        self,
        repository_root: Path,
        repository: TermCandidateRepository,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.repository = repository

    def list_candidates(self, status: Optional[str] = None) -> list[TermCandidateRecord]:
        if status is not None and status not in {"pending", "drafting", "accepted", "rejected"}:
            raise ValueError("Unsupported Term Candidate status")
        return self.repository.list_candidates(status)

    def get_candidate(self, candidate_id: str) -> TermCandidateDetail:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Term Candidate '{}' does not exist".format(candidate_id))
        return TermCandidateDetail(
            **candidate.model_dump(), evidence=self.repository.get_evidence(candidate_id)
        )

    def create_candidate(
        self,
        display_name: str,
        suggested_type: TermType,
        evidence: list[TermCandidateEvidenceInput],
    ) -> TermCandidateRecord:
        """Create or enrich a Candidate after applying the current registry and rejects."""
        normalized_name = normalize_key(display_name)
        if not normalized_name:
            raise ValueError("Term Candidate names must contain searchable text")
        clean_name = display_name.strip()
        now = _utc_now()
        evidence = [
            item
            if isinstance(item, TermCandidateEvidenceInput)
            else TermCandidateEvidenceInput.model_validate(item)
            for item in evidence
        ]
        if not evidence:
            raise ValueError("Term Candidates require at least one Evidence origin")
        if self.repository.is_rejected(normalized_name, "global"):
            raise TermCandidateConflict("This Term Candidate was rejected globally")

        registry_match = self._resolve_name(clean_name)
        suggested_term_id = (
            registry_match.entity_id
            if registry_match.status == "resolved"
            else None
        )
        eligible_evidence = [
            item
            for item in evidence
            if not self.repository.is_rejected(
                normalized_name, _origin_scope(item.origin_type, item.origin_id)
            )
        ]
        if not eligible_evidence:
            raise TermCandidateConflict(
                "Every origin for this Term Candidate has a local rejection"
            )

        existing = self.repository.find_open_candidate(normalized_name)
        if existing is not None:
            self.repository.add_evidence(
                existing.id, eligible_evidence, now, suggested_term_id
            )
            return self.repository.get_candidate(existing.id)

        candidate = TermCandidateRecord(
            id=uuid.uuid4().hex,
            normalized_name=normalized_name,
            display_name=clean_name,
            suggested_type=suggested_type,
            suggested_term_id=suggested_term_id,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        return self.repository.create_candidate(candidate, eligible_evidence)

    def resolve_against_registry(
        self, candidate: TermCandidateRecord
    ) -> CandidateResolution:
        normalized_name = normalize_key(candidate.display_name)
        if not normalized_name:
            raise ValueError("Term Candidate names must contain searchable text")

        registry_match = self._resolve_name(candidate.display_name)
        if registry_match.status == "resolved":
            return CandidateResolution(
                "existing_term",
                normalized_name,
                term_id=registry_match.entity_id,
                matched_by=registry_match.matched_by,
            )

        pending = self.repository.find_open_candidate(normalized_name)
        if pending is not None and pending.id != candidate.id:
            return CandidateResolution(
                "open_candidate", normalized_name, candidate_id=pending.id
            )

        if self.repository.is_rejected(normalized_name, "global"):
            return CandidateResolution("rejected", normalized_name)
        evidence = self.repository.get_evidence(candidate.id)
        if evidence and all(
            self.repository.is_rejected(
                normalized_name, _origin_scope(item.origin_type, item.origin_id)
            )
            for item in evidence
        ):
            return CandidateResolution("rejected", normalized_name)
        return CandidateResolution("new_term", normalized_name)

    def reject_candidate(
        self, candidate_id: str, scope: str, reason: Optional[str] = None
    ) -> TermCandidateRecord:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Term Candidate '{}' does not exist".format(candidate_id))
        if scope not in {"local", "global"}:
            raise ValueError("Rejection scope must be local or global")
        if reason is not None and not reason.strip():
            reason = None
        if scope == "global":
            scopes = ["global"]
        else:
            evidence = self.repository.get_evidence(candidate_id)
            scopes = sorted(
                {
                    _origin_scope(item.origin_type, item.origin_id)
                    for item in evidence
                }
            )
            if not scopes:
                raise ValueError("A local rejection requires Candidate Evidence")
        return self.repository.reject_candidate(
            candidate_id, scopes, reason, _utc_now()
        )

    def accept_existing(
        self, candidate_id: str, term_query: str
    ) -> TermCandidateRecord:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Term Candidate '{}' does not exist".format(candidate_id))
        if candidate.status not in {"pending", "drafting"}:
            raise TermCandidateConflict("Only open Term Candidates can be accepted")
        if self.repository.is_rejected(candidate.normalized_name, "global"):
            raise TermCandidateConflict("This Term Candidate was rejected globally")

        resolution = self._resolve_name(term_query)
        if resolution.status != "resolved" or not resolution.entity_id:
            raise ValueError("The selected value does not resolve to a canonical Term")

        now = _utc_now()
        evidence = self.repository.get_evidence(candidate_id)
        relations = []
        for item in evidence:
            if item.origin_type not in {"document", "source", "research_work"}:
                continue
            if self.repository.is_rejected(
                candidate.normalized_name,
                _origin_scope(item.origin_type, item.origin_id),
            ):
                continue
            relations.append(
                TermEntityRelation(
                    id=uuid.uuid4().hex,
                    entity_type=item.origin_type,
                    entity_id=item.origin_id,
                    term_id=resolution.entity_id,
                    created_from_candidate_id=candidate_id,
                    created_at=now,
                )
            )
        return self.repository.accept_existing(
            candidate_id, resolution.entity_id, relations, now
        )

    def _resolve_name(self, query: str) -> Resolution:
        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        return TermResolver(registry).resolve(query)


def _origin_scope(origin_type: str, origin_id: str) -> str:
    return "origin:{}:{}".format(origin_type, origin_id)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
