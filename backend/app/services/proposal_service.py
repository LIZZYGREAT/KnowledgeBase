"""Proposal lifecycle, stale detection, and rejected candidate tracking."""

from datetime import datetime, timezone
from difflib import unified_diff
from typing import Any, Dict, Optional
import uuid

from backend.app.domain.runtime import (
    CandidateType,
    EntityType,
    Proposal,
    ProposalKind,
    ProposalStatus,
    RejectedCandidate,
)
from backend.app.repositories.proposal_repository import (
    ProposalNotFoundError,
    ProposalRepository,
    ProposalTransitionError,
)
from backend.app.services.resolution import normalize_key


_ENTITY_TYPES = {"document", "term", "source", "taxonomy"}
_PROPOSAL_KINDS = {
    "metadata",
    "link",
    "new_term",
    "term_revision",
    "document_revision",
    "taxonomy",
    "evidence",
    "format",
}
_ACTIVE_STATUSES = ("proposed", "drafted", "approved")
_CANDIDATE_TYPES = {"term", "taxonomy"}


class StaleProposalError(RuntimeError):
    pass


class ProposalService:
    def __init__(self, repository: ProposalRepository):
        self.repository = repository

    def create(
        self,
        target_type: EntityType,
        target_id: str,
        kind: ProposalKind,
        base_revision: str,
        payload: Dict[str, Any],
        created_by: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        diff_text: Optional[str] = None,
        base_content: Optional[str] = None,
        proposed_content: Optional[str] = None,
    ) -> Proposal:
        if target_type not in _ENTITY_TYPES:
            raise ValueError("Unsupported Proposal target type: {}".format(target_type))
        if kind not in _PROPOSAL_KINDS:
            raise ValueError("Unsupported Proposal kind: {}".format(kind))
        _require_text(target_id, "target_id")
        _require_text(base_revision, "base_revision")
        _require_text(created_by, "created_by")
        if not isinstance(payload, dict):
            raise ValueError("Proposal payload must be a JSON object")
        if diff_text is not None and (base_content is not None or proposed_content is not None):
            raise ValueError("Provide diff_text or content pair, not both")
        if (base_content is None) != (proposed_content is None):
            raise ValueError("Both base_content and proposed_content are required for a diff")
        if base_content is not None:
            diff_text = build_unified_diff(base_content, proposed_content)

        proposal = Proposal(
            id=uuid.uuid4().hex,
            target_type=target_type,
            target_id=target_id,
            kind=kind,
            status="proposed",
            base_revision=base_revision,
            payload=payload,
            diff_text=diff_text,
            created_by=created_by,
            provider=_optional_text(provider),
            model=_optional_text(model),
            created_at=_utc_now(),
            reviewed_at=None,
            review_note=None,
        )
        return self.repository.create(proposal)

    def get(self, proposal_id: str) -> Proposal:
        proposal = self.repository.get(proposal_id)
        if proposal is None:
            raise ProposalNotFoundError("Proposal '{}' does not exist".format(proposal_id))
        return proposal

    def draft(
        self,
        proposal_id: str,
        payload: Dict[str, Any],
        diff_text: Optional[str] = None,
    ) -> Proposal:
        if not isinstance(payload, dict):
            raise ValueError("Proposal payload must be a JSON object")
        return self.repository.update_draft(proposal_id, payload, diff_text)

    def approve(
        self,
        proposal_id: str,
        current_revision: str,
        review_note: Optional[str] = None,
    ) -> Proposal:
        proposal = self._require_current_base(proposal_id, current_revision)
        if proposal.status not in {"proposed", "drafted"}:
            raise ProposalTransitionError(
                "Cannot approve a Proposal in '{}' status".format(proposal.status)
            )
        return self.repository.transition(
            proposal_id,
            (proposal.status,),
            "approved",
            _utc_now(),
            _optional_text(review_note),
        )

    def reject(
        self,
        proposal_id: str,
        review_note: str,
        candidate_type: Optional[CandidateType] = None,
        candidate_value: Optional[str] = None,
        scope: str = "global",
    ) -> Proposal:
        _require_text(review_note, "review_note")
        candidate = None
        if candidate_type is not None or candidate_value is not None:
            if candidate_type not in _CANDIDATE_TYPES:
                raise ValueError("candidate_type must be 'term' or 'taxonomy'")
            _require_text(candidate_value, "candidate_value")
            normalized_value = normalize_key(candidate_value)
            if not normalized_value:
                raise ValueError("candidate_value must normalize to non-empty text")
            _require_text(scope, "scope")
            candidate = (candidate_type, normalized_value, scope.strip())

        proposal = self.get(proposal_id)
        if proposal.status not in {"proposed", "drafted", "approved", "stale"}:
            raise ProposalTransitionError(
                "Cannot reject a Proposal in '{}' status".format(proposal.status)
            )
        return self.repository.transition(
            proposal_id,
            (proposal.status,),
            "rejected",
            _utc_now(),
            review_note.strip(),
            rejected_candidate=candidate,
        )

    def merge(self, proposal_id: str, current_revision: str) -> Proposal:
        proposal = self._require_current_base(proposal_id, current_revision)
        if proposal.status != "approved":
            raise ProposalTransitionError(
                "Only an approved Proposal can be merged; current status is '{}'".format(
                    proposal.status
                )
            )
        return self.repository.transition(
            proposal_id,
            ("approved",),
            "merged",
            _utc_now(),
            proposal.review_note,
        )

    def detect_stale(self, proposal_id: str, current_revision: str) -> Proposal:
        _require_text(current_revision, "current_revision")
        proposal = self.get(proposal_id)
        if proposal.status in _ACTIVE_STATUSES and proposal.base_revision != current_revision:
            note = "Base revision changed from '{}' to '{}'".format(
                proposal.base_revision, current_revision
            )
            return self.repository.transition(
                proposal_id,
                (proposal.status,),
                "stale",
                _utc_now(),
                note,
            )
        return proposal

    def assert_applicable(self, proposal_id: str, current_revision: str) -> Proposal:
        proposal = self._require_current_base(proposal_id, current_revision)
        if proposal.status != "approved":
            raise ProposalTransitionError(
                "Only an approved Proposal can be applied; current status is '{}'".format(
                    proposal.status
                )
            )
        return proposal

    def record_rejected_candidate(
        self,
        candidate_type: CandidateType,
        value: str,
        reason: str,
        scope: str = "global",
    ) -> RejectedCandidate:
        if candidate_type not in _CANDIDATE_TYPES:
            raise ValueError("candidate_type must be 'term' or 'taxonomy'")
        _require_text(value, "value")
        normalized_value = normalize_key(value)
        if not normalized_value:
            raise ValueError("value must normalize to non-empty text")
        _require_text(reason, "reason")
        _require_text(scope, "scope")
        return self.repository.record_rejected_candidate(
            candidate_type,
            normalized_value,
            reason.strip(),
            scope.strip(),
            _utc_now(),
        )

    def is_rejected_candidate(
        self, candidate_type: CandidateType, value: str, scope: str = "global"
    ) -> bool:
        if candidate_type not in _CANDIDATE_TYPES:
            raise ValueError("candidate_type must be 'term' or 'taxonomy'")
        _require_text(value, "value")
        normalized_value = normalize_key(value)
        if not normalized_value:
            return False
        return self.repository.is_rejected_candidate(
            candidate_type, normalized_value, scope.strip()
        )

    def _require_current_base(self, proposal_id: str, current_revision: str) -> Proposal:
        _require_text(current_revision, "current_revision")
        proposal = self.detect_stale(proposal_id, current_revision)
        if proposal.status == "stale":
            raise StaleProposalError(
                "Proposal '{}' is stale and cannot be applied".format(proposal_id)
            )
        return proposal


def build_unified_diff(before: str, after: str) -> str:
    return "".join(
        unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="base",
            tofile="proposal",
        )
    )


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be non-empty text".format(field))


def _optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip() or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
