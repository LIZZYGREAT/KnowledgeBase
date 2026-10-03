"""Draft publishing API routes."""

from fastapi import APIRouter, Request

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
    result = request.app.state.publisher.publish(
        body.draft_id,
        expected_revision=body.expected_revision,
        commit_message=body.commit_message,
    )
    return _published_view(result)


@router.post("/publish/batch", response_model=BatchPublishedView)
async def publish_batch(body: BatchPublishRequest, request: Request):
    result = request.app.state.publisher.publish_batch(
        [(item.draft_id, item.expected_revision) for item in body.drafts],
        body.commit_message,
    )
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
