"""Draft publishing API routes."""

from dataclasses import asdict
import hashlib

from fastapi import APIRouter, HTTPException, Request

from backend.app.api.schemas import (
    BatchPreflightRequest,
    BatchPreflightView,
    BatchPublishRequest,
    BatchPublishedView,
    PublishRequest,
    PublishedView,
)
from backend.app.services.publisher import PublishedResult

router = APIRouter(prefix="/api", tags=["Runtime"])


@router.post("/publish/preflight-batch", response_model=BatchPreflightView)
async def preflight_publish_batch(body: BatchPreflightRequest, request: Request):
    results = request.app.state.publisher.preflight_batch(
        [(item.draft_id, item.expected_revision) for item in body.drafts]
    )
    return {"results": [asdict(result) for result in results]}


@router.post("/publish", response_model=PublishedView)
async def publish(body: PublishRequest, request: Request):
    publisher = request.app.state.publisher
    draft = request.app.state.draft_service.get(body.draft_id)
    if draft.entity_type != "research_profile":
        if body.reactivation_strategy is not None:
            raise HTTPException(
                status_code=422,
                detail="Reactivation strategy is only valid for a Research Profile Draft",
            )
        return _published_view(
            publisher.publish(
                body.draft_id,
                expected_revision=body.expected_revision,
                commit_message=body.commit_message,
            )
        )

    service = request.app.state.research_service
    lock = service.global_lock
    if not lock.try_acquire():
        raise HTTPException(
            status_code=409,
            detail="Research is currently running; retry publishing after it finishes.",
        )
    try:
        draft = request.app.state.draft_service.get(body.draft_id)
        if draft.revision != body.expected_revision:
            raise HTTPException(
                status_code=409,
                detail="Draft changed after review. Refresh the Publish Review before publishing.",
            )
        service.materialize_pending_reactivation_boundary(draft.entity_id)
        candidate = service.parse_profile_candidate(draft.entity_id, draft.content)
        review = service.reactivation_review(candidate)
        if review["required"] and body.reactivation_strategy is None:
            raise HTTPException(
                status_code=409,
                detail="This Research Profile requires Reactivation Review before publishing.",
            )
        if not review["required"] and body.reactivation_strategy is not None:
            raise HTTPException(
                status_code=409,
                detail="The Profile reactivation state changed; review the Draft again.",
            )

        if body.reactivation_strategy is not None:
            service.record_reactivation_choice(
                draft.entity_id,
                hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
                body.reactivation_strategy,
                catchup_days=(
                    candidate.search.max_catchup_days
                    if body.reactivation_strategy == "last_window"
                    else None
                ),
                streams=review.get("streams", []),
                now=service.now(),
            )
        result = publisher.publish(
            body.draft_id,
            expected_revision=body.expected_revision,
            commit_message=body.commit_message,
        )
        return _published_view(result)
    finally:
        lock.release()


@router.post("/publish/batch", response_model=BatchPublishedView)
async def publish_batch(body: BatchPublishRequest, request: Request):
    publisher = request.app.state.publisher
    entries = [(item.draft_id, item.expected_revision) for item in body.drafts]
    drafts = [request.app.state.draft_service.get(draft_id) for draft_id, _ in entries]
    profile_drafts = [draft for draft in drafts if draft.entity_type == "research_profile"]
    service = request.app.state.research_service
    if profile_drafts:
        lock = service.global_lock
        if not lock.try_acquire():
            raise HTTPException(
                status_code=409,
                detail="Research is currently running; retry publishing after it finishes.",
            )
        try:
            for draft in profile_drafts:
                service.materialize_pending_reactivation_boundary(draft.entity_id)
                candidate = service.parse_profile_candidate(draft.entity_id, draft.content)
                if service.reactivation_review(candidate)["required"]:
                    raise HTTPException(
                        status_code=409,
                        detail="Publish this Research Profile Draft individually to complete Reactivation Review.",
                    )
            result = publisher.publish_batch(entries, body.commit_message)
        finally:
            lock.release()
    else:
        result = publisher.publish_batch(entries, body.commit_message)
    return {
        "results": [_published_view(item) for item in result.results],
        "commit_revision": result.commit_revision,
        "warnings": list(result.warnings),
    }


def _published_view(result: PublishedResult) -> dict:
    return {
        "draft_id": result.draft_id,
        "entity_type": result.entity_type,
        "entity_id": result.entity_id,
        "commit_revision": result.commit_revision,
        "warnings": list(result.warnings),
    }
