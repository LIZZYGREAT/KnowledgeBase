"""Runtime Term Candidate API."""

from typing import Literal, Optional

from fastapi import APIRouter, Query, Request

from backend.app.api.term_schemas import (
    AcceptExistingTermCandidateRequest,
    RejectTermCandidateRequest,
)
from backend.app.domain.term_runtime import TermCandidateDetail, TermCandidateRecord


router = APIRouter(prefix="/api/terms", tags=["Terms"])


@router.get("/candidates", response_model=list[TermCandidateRecord])
async def list_term_candidates(
    request: Request,
    status: Optional[Literal["pending", "drafting", "accepted", "rejected"]] = Query(
        default=None
    ),
):
    return request.app.state.term_candidate_service.list_candidates(status)


@router.get("/candidates/{candidate_id}", response_model=TermCandidateDetail)
async def get_term_candidate(candidate_id: str, request: Request):
    return request.app.state.term_candidate_service.get_candidate(candidate_id)


@router.post("/candidates/{candidate_id}/reject", response_model=TermCandidateRecord)
async def reject_term_candidate(
    candidate_id: str,
    body: RejectTermCandidateRequest,
    request: Request,
):
    return request.app.state.term_candidate_service.reject_candidate(
        candidate_id, body.scope, body.reason
    )


@router.post(
    "/candidates/{candidate_id}/accept-existing",
    response_model=TermCandidateRecord,
)
async def accept_existing_term_candidate(
    candidate_id: str,
    body: AcceptExistingTermCandidateRequest,
    request: Request,
):
    return request.app.state.term_candidate_service.accept_existing(
        candidate_id, body.term_id
    )
