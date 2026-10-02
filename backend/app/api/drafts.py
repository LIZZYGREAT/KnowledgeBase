"""Runtime Draft API routes."""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Request, Response, status

from backend.app.api.schemas import (
    DraftAcquireView,
    DraftCompareView,
    DraftCreateRequest,
    DraftDeleteRequest,
    DraftPreflightView,
    DraftRebaseRequest,
    DraftUpdateRequest,
    DraftView,
)

router = APIRouter(prefix="/api", tags=["Runtime"])


@router.post("/drafts", response_model=DraftAcquireView, status_code=status.HTTP_201_CREATED)
async def create_draft(body: DraftCreateRequest, request: Request, response: Response):
    target = request.app.state.canonical_target_resolver.resolve_target(
        body.entity_type, body.entity_id, body.content
    ).path
    git = request.app.state.git_manager
    result = request.app.state.draft_service.create_or_get(
        body.entity_type,
        body.entity_id,
        body.content,
        git.current_revision(),
        git.content_hash(target),
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return {"draft": asdict(result.draft), "created": result.created}


@router.get("/drafts", response_model=list[DraftView])
async def list_drafts(
    request: Request,
    entity_type: Literal["document", "term", "source", "taxonomy", "collection"],
    entity_id: str,
):
    return [
        asdict(draft)
        for draft in request.app.state.draft_service.list_for_target(entity_type, entity_id)
    ]


@router.get("/drafts/{draft_id}", response_model=DraftView)
async def get_draft(draft_id: str, request: Request):
    return asdict(request.app.state.draft_service.get(draft_id))


@router.put("/drafts/{draft_id}", response_model=DraftView)
async def update_draft(draft_id: str, body: DraftUpdateRequest, request: Request):
    return asdict(
        request.app.state.draft_service.save(
            draft_id, body.content, body.expected_revision
        )
    )


@router.get("/drafts/{draft_id}/compare", response_model=DraftCompareView)
async def compare_draft(draft_id: str, request: Request):
    draft = request.app.state.draft_service.get(draft_id)
    target = request.app.state.canonical_target_resolver.resolve_target(
        draft.entity_type, draft.entity_id, draft.content
    ).path
    git = request.app.state.git_manager
    current_revision = git.current_revision()
    current_hash = git.content_hash(target)
    current_content = target.read_text(encoding="utf-8") if target.is_file() else ""
    historical = git.read_at_revision(target, draft.base_git_revision)
    base_content = historical.decode("utf-8") if historical is not None else ""
    return {
        "draft": asdict(draft),
        "base_content": base_content,
        "current_content": current_content,
        "current_git_revision": current_revision,
        "current_content_hash": current_hash,
        "canonical_changed": current_hash != draft.base_content_hash,
    }


@router.get("/drafts/{draft_id}/preflight", response_model=DraftPreflightView)
async def preflight_draft(draft_id: str, request: Request):
    return asdict(request.app.state.publisher.preflight(draft_id))


@router.put("/drafts/{draft_id}/rebase", response_model=DraftView)
async def rebase_draft(draft_id: str, body: DraftRebaseRequest, request: Request):
    draft = request.app.state.draft_service.get(draft_id)
    target = request.app.state.canonical_target_resolver.resolve_target(
        draft.entity_type, draft.entity_id, draft.content
    ).path
    git = request.app.state.git_manager
    current_hash = git.content_hash(target)
    if body.expected_current_hash != current_hash:
        raise ValueError("Canonical content changed again; compare the Draft again")
    return asdict(
        request.app.state.draft_service.rebase(
            draft_id,
            body.content,
            body.expected_revision,
            git.current_revision(),
            current_hash,
        )
    )


@router.delete("/drafts/{draft_id}")
async def discard_draft(draft_id: str, body: DraftDeleteRequest, request: Request):
    request.app.state.draft_service.discard(draft_id, body.expected_revision)
    return {"deleted": True}
