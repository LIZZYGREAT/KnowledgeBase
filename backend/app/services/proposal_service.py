"""Proposal lifecycle, stale detection, and rejected candidate tracking."""

from datetime import datetime, timezone
from difflib import unified_diff
from typing import Any, Dict, Optional
import hashlib
import re
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
        base_content_hash: str,
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
        _require_content_hash(base_content_hash)
        _require_text(created_by, "created_by")
        if not isinstance(payload, dict):
            raise ValueError("Proposal payload must be a JSON object")
        if diff_text is not None and (base_content is not None or proposed_content is not None):
            raise ValueError("Provide diff_text or content pair, not both")
        if (base_content is None) != (proposed_content is None):
            raise ValueError("Both base_content and proposed_content are required for a diff")
        if base_content is not None:
            calculated_hash = hashlib.sha256(base_content.encode("utf-8")).hexdigest()
            if base_content_hash != calculated_hash:
                raise ValueError("base_content_hash does not match base_content")
            diff_text = build_unified_diff(base_content, proposed_content)

        proposal = Proposal(
            id=uuid.uuid4().hex,
            target_type=target_type,
            target_id=target_id,
            kind=kind,
            status="proposed",
            base_content_hash=base_content_hash,
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

    def list(
        self,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Proposal]:
        if target_type is not None and target_type not in _ENTITY_TYPES:
            raise ValueError("Unsupported Proposal target type: {}".format(target_type))
        if kind is not None and kind not in _PROPOSAL_KINDS:
            raise ValueError("Unsupported Proposal kind: {}".format(kind))
        if status is not None and status not in {
            "proposed", "drafted", "approved", "merged", "rejected", "stale"
        }:
            raise ValueError("Unsupported Proposal status: {}".format(status))
        if target_id is not None:
            _require_text(target_id, "target_id")
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be zero or greater")
        return self.repository.list(target_type, target_id, kind, status, limit, offset)

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
        current_content_hash: str,
        review_note: Optional[str] = None,
    ) -> Proposal:
        proposal = self._require_current_base(proposal_id, current_content_hash)
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

    def merge(self, proposal_id: str, current_content_hash: str) -> Proposal:
        proposal = self._require_current_base(proposal_id, current_content_hash)
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

    def detect_stale(self, proposal_id: str, current_content_hash: str) -> Proposal:
        _require_content_hash(current_content_hash)
        proposal = self.get(proposal_id)
        if (
            proposal.status in _ACTIVE_STATUSES
            and proposal.base_content_hash != current_content_hash
        ):
            note = "Base content changed from '{}' to '{}'".format(
                proposal.base_content_hash, current_content_hash
            )
            return self.repository.transition(
                proposal_id,
                (proposal.status,),
                "stale",
                _utc_now(),
                note,
            )
        return proposal

    def assert_applicable(self, proposal_id: str, current_content_hash: str) -> Proposal:
        proposal = self._require_current_base(proposal_id, current_content_hash)
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

    def _require_current_base(self, proposal_id: str, current_content_hash: str) -> Proposal:
        _require_content_hash(current_content_hash)
        proposal = self.detect_stale(proposal_id, current_content_hash)
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


def _require_content_hash(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("base_content_hash must be a lowercase SHA-256 hash")


def _optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip() or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
