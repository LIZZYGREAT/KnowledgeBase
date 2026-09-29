"""Read-only Knowledge API routes for canonical entries and search."""

from pathlib import Path
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from backend.app.api.schemas import (
    ContextExportRequest,
    ContextExportView,
    EntityDetail,
    EntitySummary,
    RecentlyModifiedView,
    SearchResultView,
    TaxonomyEntryView,
    TopicView,
)
from backend.app.services.search_service import SearchFilters, SearchService


router = APIRouter(prefix="/api", tags=["Knowledge"])


@router.get("/documents", response_model=list[EntitySummary])
async def list_documents(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return request.app.state.knowledge_read_service.list_entities("document", limit, offset)


@router.get("/documents/recently-modified", response_model=list[RecentlyModifiedView])
async def recently_modified_documents(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
):
    return request.app.state.knowledge_read_service.recently_modified(limit)


@router.get("/documents/{entity_id}", response_model=EntityDetail)
async def get_document(entity_id: str, request: Request):
    return request.app.state.knowledge_read_service.get_entity("document", entity_id)


@router.get("/terms", response_model=list[EntitySummary])
async def list_terms(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return request.app.state.knowledge_read_service.list_entities("term", limit, offset)


@router.get("/terms/{entity_id}", response_model=EntityDetail)
async def get_term(entity_id: str, request: Request):
    return request.app.state.knowledge_read_service.get_entity("term", entity_id)


@router.get("/sources", response_model=list[EntitySummary])
async def list_sources(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return request.app.state.knowledge_read_service.list_entities("source", limit, offset)


@router.get("/sources/{entity_id}", response_model=EntityDetail)
async def get_source(entity_id: str, request: Request):
    return request.app.state.knowledge_read_service.get_entity("source", entity_id)


@router.get("/sources/{entity_id}/pdf")
async def open_source_pdf(entity_id: str, request: Request):
    source = request.app.state.knowledge_read_service.get_entity("source", entity_id)
    attachments = source["metadata"].get("attachments") or {}
    attachment = attachments.get("local_pdf") if isinstance(attachments, dict) else None
    if not isinstance(attachment, str):
        raise HTTPException(status_code=404, detail="This Source has no local PDF")
    match = re.fullmatch(
        r"storage://papers/([a-z0-9]+(?:-[a-z0-9]+)*)\.pdf",
        attachment,
    )
    if match is None:
        raise HTTPException(status_code=404, detail="This Source has no local PDF")

    repository_root = Path(request.app.state.repository_root).resolve()
    storage_root = repository_root / "storage"
    papers_root = storage_root / "papers"
    if storage_root.is_symlink() or papers_root.is_symlink():
        raise HTTPException(status_code=404, detail="Local PDF is unavailable")
    resolved_papers = papers_root.resolve()
    try:
        resolved_papers.relative_to(repository_root)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Local PDF is unavailable") from error

    pdf_path = papers_root / "{}.pdf".format(match.group(1))
    if pdf_path.is_symlink():
        raise HTTPException(status_code=404, detail="Local PDF is unavailable")
    resolved_pdf = pdf_path.resolve()
    try:
        resolved_pdf.relative_to(resolved_papers)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Local PDF is unavailable") from error
    if not resolved_pdf.is_file():
        raise HTTPException(status_code=404, detail="Local PDF is unavailable")
    with resolved_pdf.open("rb") as pdf_file:
        if pdf_file.read(5) != b"%PDF-":
            raise HTTPException(status_code=404, detail="Local PDF is unavailable")
    return FileResponse(
        resolved_pdf,
        media_type="application/pdf",
        filename="{}.pdf".format(entity_id),
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/topics", response_model=list[TopicView])
async def list_topics(
    request: Request,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return request.app.state.knowledge_read_service.topics(limit, offset)


@router.get("/taxonomy", response_model=list[TaxonomyEntryView])
async def list_taxonomy(
    request: Request,
    kind: str = Query(pattern="^(domain|topic|tag)$"),
):
    return request.app.state.knowledge_read_service.taxonomy_entries(kind)


@router.get("/review/link-issues")
async def list_link_issues(request: Request):
    return request.app.state.knowledge_read_service.link_issues()


@router.get("/search", response_model=list[SearchResultView])
async def search(
    request: Request,
    query: str = "",
    domain: Optional[str] = None,
    topic: Optional[str] = None,
    tag: Optional[str] = None,
    document_type: Optional[str] = None,
    review: Optional[str] = None,
    maintenance: Optional[str] = None,
    source: Optional[str] = None,
    term: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
):
    filters = SearchFilters(
        domain=domain,
        topic=topic,
        tag=tag,
        document_type=document_type,
        review=review,
        maintenance=maintenance,
        source=source,
        term=term,
    )
    results = SearchService(request.app.state.runtime_connection).search(query, filters, limit)
    return [
        {
            "entity_type": result.entity_type,
            "entity_id": result.entity_id,
            "title": result.title,
            "matched_by": result.matched_by,
            "score": result.score,
            "snippet": result.snippet,
            "metadata": result.metadata,
            "view_count": result.view_count,
            "search_click_count": result.search_click_count,
        }
        for result in results
    ]


@router.post("/context/export", response_model=ContextExportView)
async def export_context(body: ContextExportRequest, request: Request):
    return request.app.state.context_export_service.export(
        document_id=body.document_id,
        source_id=body.source_id,
        trust=body.trust,
        purpose=body.purpose,
    )
