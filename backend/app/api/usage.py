"""Document usage API routes."""

from fastapi import APIRouter, Query, Request, status

from backend.app.api.schemas import UsageDocumentView, UsageEventView, UsageRequest

router = APIRouter(prefix="/api", tags=["Runtime"])


@router.post("/usage/document-open", response_model=UsageEventView, status_code=status.HTTP_201_CREATED)
async def record_document_open(body: UsageRequest, request: Request):
    return request.app.state.usage_service.record_document_open(body.document_id)


@router.post("/usage/search-click", response_model=UsageEventView, status_code=status.HTTP_201_CREATED)
async def record_search_click(body: UsageRequest, request: Request):
    return request.app.state.usage_service.record_search_result_click(body.document_id)


@router.get("/usage/recent", response_model=list[UsageDocumentView])
async def recently_viewed(request: Request, limit: int = Query(10, ge=1, le=100)):
    return _usage_documents(request.app.state.usage_service.recently_viewed(limit))


@router.get("/usage/frequent", response_model=list[UsageDocumentView])
async def frequently_viewed(request: Request, limit: int = Query(10, ge=1, le=100)):
    return _usage_documents(request.app.state.usage_service.frequently_viewed(limit))


def _usage_documents(rows: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in row.items() if key != "path"}
        for row in rows
    ]
