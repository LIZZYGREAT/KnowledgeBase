"""Runtime Term Candidate API."""

from typing import Literal, Optional

from fastapi import APIRouter, Query, Request

from backend.app.api.term_schemas import (
    AcceptExistingTermCandidateRequest,
    RejectTermCandidateRequest,
    TermMergePreviewRequest,
    TermMergePreviewView,
    TermMergeRequest,
    TermMergeResultView,
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


@router.post("/merge/preview", response_model=TermMergePreviewView)
async def preview_term_merge(body: TermMergePreviewRequest, request: Request):
    return request.app.state.term_merge_service.preview(
        body.survivor_term_id, body.loser_term_ids, body.final_title
    )


@router.post("/merge", response_model=TermMergeResultView)
async def merge_terms(body: TermMergeRequest, request: Request):
    return request.app.state.term_merge_service.merge(
        body.survivor_term_id,
        body.loser_term_ids,
        body.final_title,
        body.confirm_loser_bodies_not_merged,
    )
