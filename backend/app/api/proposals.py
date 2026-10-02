"""Proposal API routes."""

from dataclasses import asdict
from typing import Literal, Optional

from fastapi import APIRouter, Query, Request

from backend.app.api.schemas import (
    ProposalApplyRequest,
    ProposalApplyView,
    ProposalRejectRequest,
    ProposalView,
)

router = APIRouter(prefix="/api", tags=["Runtime"])


@router.get("/proposals", response_model=list[ProposalView])
async def list_proposals(
    request: Request,
    target_type: Optional[Literal["document", "term", "source", "taxonomy"]] = None,
    target_id: Optional[str] = None,
    kind: Optional[str] = None,
    proposal_status: Optional[Literal[
        "proposed", "drafted", "merged", "rejected", "stale"
    ]] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    proposals = request.app.state.proposal_service.list(
        target_type, target_id, kind, proposal_status, limit, offset
    )
    return [asdict(proposal) for proposal in proposals]


@router.get("/proposals/{proposal_id}", response_model=ProposalView)
async def get_proposal(proposal_id: str, request: Request):
    return asdict(request.app.state.proposal_service.get(proposal_id))


@router.post(
    "/proposals/{proposal_id}/apply",
    response_model=ProposalApplyView,
)
async def apply_proposal(
    proposal_id: str, body: ProposalApplyRequest, request: Request
):
    proposal = request.app.state.proposal_service.get(proposal_id)
    draft = _proposal_draft(request, proposal)
    if draft.id != body.draft_id:
        raise ValueError("Proposal target does not match its Draft")
    applied_proposal, applied_draft = request.app.state.proposal_service.apply_to_draft(
        proposal_id, draft, body.expected_draft_revision
    )
    return {"proposal": asdict(applied_proposal), "draft": asdict(applied_draft)}


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalView)
async def reject_proposal(proposal_id: str, body: ProposalRejectRequest, request: Request):
    result = request.app.state.proposal_service.reject(
        proposal_id,
        body.review_note,
        candidate_type=body.candidate_type,
        candidate_value=body.candidate_value,
        scope=body.scope,
    )
    return asdict(result)


def _proposal_draft(request: Request, proposal):
    draft_id = proposal.payload.get("draft_id")
    if not isinstance(draft_id, str) or not draft_id:
        raise ValueError("Proposal is not associated with a Draft")
    draft = request.app.state.draft_service.get(draft_id)
    if draft.entity_type != proposal.target_type or draft.entity_id != proposal.target_id:
        raise ValueError("Proposal target does not match its Draft")
    return draft
