"""Collection progress API routes."""

from fastapi import APIRouter, Request

from backend.app.api.schemas import CollectionProgressRequest, CollectionProgressView

router = APIRouter(prefix="/api", tags=["Runtime"])


@router.put(
    "/collections/{collection_id}/progress/{document_id}",
    response_model=CollectionProgressView,
)
async def set_collection_progress(
    collection_id: str,
    document_id: str,
    body: CollectionProgressRequest,
    request: Request,
):
    return request.app.state.collection_service.set_progress(
        collection_id, document_id, body.status
    )
