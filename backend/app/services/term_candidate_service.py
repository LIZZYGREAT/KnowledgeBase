"""Human-reviewed Term Candidate resolution and lifecycle operations."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import uuid
from typing import Optional

import yaml

from backend.app.domain.term_runtime import (
    TermCandidateDetail,
    TermCandidateEvidence,
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
        draft_service=None,
        git_manager=None,
        canonical_target_resolver=None,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.repository = repository
        self.draft_service = draft_service
        self.git_manager = git_manager
        self.canonical_target_resolver = canonical_target_resolver

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

    def list_candidate_details(
        self, status: Optional[str] = None
    ) -> list[TermCandidateDetail]:
        return [self.get_candidate(item.id) for item in self.list_candidates(status)]

    def create_candidate(
        self,
        display_name: str,
        suggested_type: TermType,
        evidence: list[TermCandidateEvidenceInput],
        preferred_term_id: Optional[str] = None,
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

        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        registry_match = TermResolver(registry).resolve(clean_name)
        preferred_term = registry.get(preferred_term_id) if preferred_term_id else None
        if preferred_term_id and preferred_term is None:
            raise ValueError("Preferred Term id must exist in the Canonical Term Registry")
        if (
            preferred_term is not None
            and registry_match.status == "resolved"
            and registry_match.entity_id != preferred_term.id
        ):
            raise TermCandidateConflict(
                "Preferred Term conflicts with deterministic Term resolution"
            )
        suggested_term_id = (
            registry_match.entity_id
            if registry_match.status == "resolved"
            else preferred_term.id
            if preferred_term is not None
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
            if (
                existing.suggested_term_id
                and suggested_term_id
                and existing.suggested_term_id != suggested_term_id
            ):
                raise TermCandidateConflict(
                    "Candidate has a conflicting Existing Term suggestion"
                )
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
        self,
        candidate_id: str,
        scope: str,
        reason: Optional[str] = None,
        origin_type: Optional[str] = None,
        origin_id: Optional[str] = None,
    ) -> TermCandidateRecord:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Term Candidate '{}' does not exist".format(candidate_id))
        if candidate.status != "pending":
            raise TermCandidateConflict(
                "Only pending Term Candidates can be rejected; discard the linked Draft first"
            )
        if scope not in {"local", "global"}:
            raise ValueError("Rejection scope must be local or global")
        if reason is not None and not reason.strip():
            reason = None
        if scope == "global":
            if origin_type is not None or origin_id is not None:
                raise ValueError("Global rejection does not take an origin")
            scopes = ["global"]
            close_candidate = True
        else:
            evidence = self.repository.get_evidence(candidate_id)
            origins = {
                (item.origin_type, item.origin_id)
                for item in evidence
            }
            if not origins:
                raise ValueError("A local rejection requires Candidate Evidence")
            if (origin_type is None) != (origin_id is None):
                raise ValueError("Local rejection origin_type and origin_id must be provided together")
            if origin_type is None:
                if len(origins) != 1:
                    raise ValueError("Select one Candidate origin for a local rejection")
                origin_type, origin_id = next(iter(origins))
            elif (origin_type, origin_id) not in origins:
                raise ValueError("The selected origin is not part of this Candidate")
            scopes = [_origin_scope(origin_type, origin_id)]
            close_candidate = not any(
                _origin_scope(item.origin_type, item.origin_id) != scopes[0]
                and not self.repository.is_rejected(
                    candidate.normalized_name,
                    _origin_scope(item.origin_type, item.origin_id),
                )
                for item in evidence
            )
        return self.repository.reject_candidate(
            candidate_id, scopes, reason, _utc_now(), close_candidate
        )

    def create_term_draft(self, candidate_id: str) -> dict:
        self._require_draft_dependencies()
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Term Candidate '{}' does not exist".format(candidate_id))
        if candidate.status == "drafting" and candidate.draft_id:
            try:
                draft = self.draft_service.get(candidate.draft_id)
                return {"candidate": candidate, "draft": draft, "created": False}
            except LookupError:
                self.repository.reset_candidate_draft(candidate.draft_id, _utc_now())
                candidate = self.repository.get_candidate(candidate_id)
        if candidate.status != "pending":
            raise TermCandidateConflict("Only pending Term Candidates can create a Term Draft")

        evidence = self.active_term_draft_evidence(candidate_id)
        if not evidence:
            raise TermCandidateConflict(
                "A new Term Draft requires at least one active Candidate Evidence origin"
            )
        resolution = self.resolve_against_registry(candidate)
        if resolution.status == "existing_term":
            raise TermCandidateConflict(
                "This Candidate now resolves to an existing Term; accept or choose an Existing Term"
            )
        if resolution.status != "new_term":
            raise TermCandidateConflict("This Candidate is no longer available for a new Term Draft")

        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        term_id = self._candidate_term_id(candidate, registry)
        content = self._term_draft_content(candidate, term_id)
        target = self.canonical_target_resolver.resolve_target("term", term_id, content)
        active_drafts = self.draft_service.list_for_target("term", term_id)
        if active_drafts:
            raise TermCandidateConflict(
                "A Term Draft already exists for '{}'; choose another Candidate or finish that Draft".format(
                    term_id
                )
            )
        acquire = self.draft_service.create_or_get(
            "term",
            term_id,
            content,
            self.git_manager.current_revision(),
            self.git_manager.content_hash(target.path),
        )
        if not acquire.created:
            raise TermCandidateConflict(
                "A Term Draft already exists for '{}'; it is not linked to this Candidate".format(
                    term_id
                )
            )
        updated = self.repository.mark_candidate_drafting(
            candidate_id, acquire.draft.id, _utc_now()
        )
        return {"candidate": updated, "draft": acquire.draft, "created": True}

    def active_term_draft_evidence(
        self, candidate_id: str
    ) -> list[TermCandidateEvidence]:
        """Return un-rejected evidence with a live origin and usable external context."""
        evidence = self.repository.get_evidence(candidate_id)
        return [
            item
            for item in evidence
            if not item.origin_rejected and self._evidence_origin_available(item)
        ]

    def discard_term_draft(self, draft_id: str) -> Optional[TermCandidateRecord]:
        return self.repository.reset_candidate_draft(draft_id, _utc_now())

    def finalize_published_drafts(self, drafts) -> None:
        """Accept Candidates and link their Document origins after Term Publish."""
        for draft in drafts:
            if draft.entity_type != "term":
                continue
            for candidate in self.repository.list_candidates_for_draft(draft.id):
                now = _utc_now()
                relations = []
                for item in self.repository.get_evidence(candidate.id):
                    if item.origin_type not in {"document", "source", "research_work"}:
                        continue
                    if not self._evidence_origin_available(item):
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
                            term_id=draft.entity_id,
                            created_from_candidate_id=candidate.id,
                            created_at=now,
                        )
                    )
                self.repository.finalize_candidate_draft(
                    candidate.id, draft.id, draft.entity_id, relations, now
                )

    def accept_existing(
        self, candidate_id: str, term_query: str
    ) -> TermCandidateRecord:
        candidate = self.repository.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("Term Candidate '{}' does not exist".format(candidate_id))
        if candidate.status != "pending":
            raise TermCandidateConflict(
                "Only pending Term Candidates can be linked to an Existing Term; discard the linked Draft first"
            )
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

    def _require_draft_dependencies(self) -> None:
        if (
            self.draft_service is None
            or self.git_manager is None
            or self.canonical_target_resolver is None
        ):
            raise RuntimeError("Term Candidate Draft workflow is not configured")

    def _evidence_origin_available(self, item: TermCandidateEvidence) -> bool:
        if item.origin_type in {"document", "source"}:
            try:
                return (
                    self.canonical_target_resolver.resolve_existing_target_path(
                        item.origin_type, item.origin_id
                    )
                    is not None
                )
            except ValueError:
                return False
        if item.origin_type == "research_work":
            return self.repository.connection.execute(
                "SELECT 1 FROM research_works WHERE id = ?", (item.origin_id,)
            ).fetchone() is not None
        if item.origin_type == "external":
            return bool((item.context_excerpt or "").strip() or (item.rationale or "").strip())
        return False

    def _candidate_term_id(self, candidate, registry: TermRegistry) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", normalize_key(candidate.display_name)).strip("-")
        if not base:
            base = "term-{}".format(candidate.id[:12])
        base = base[:64].strip("-") or "term-{}".format(candidate.id[:12])
        if (
            registry.get(base) is None
            and self.canonical_target_resolver.resolve_existing_target_path("term", base) is None
            and not self.draft_service.list_for_target("term", base)
        ):
            return base
        suffix = candidate.id[:10]
        return "{}-{}".format(base[: 64 - len(suffix) - 1].rstrip("-"), suffix)

    @staticmethod
    def _term_draft_content(candidate, term_id: str) -> str:
        metadata = {
            "schema_version": 1,
            "id": term_id,
            "title": candidate.display_name,
            "type": candidate.suggested_type,
            "depth": "stub",
            "aliases": [],
            "domains": [],
            "topics": [],
            "tags": [],
            "sources": [],
        }
        frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
        return "---\n{}\n---\n\n".format(frontmatter)


def _origin_scope(origin_type: str, origin_id: str) -> str:
    return "origin:{}:{}".format(origin_type, origin_id)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
