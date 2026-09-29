"""Draft, Proposal, Import, Publish, and Usage API routes."""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
from typing import Literal, Optional

from fastapi import APIRouter, Query, Request, status

from backend.app.api.schemas import (
    BlankDocumentRequest,
    BundleAssociationRequest,
    BundleAssociationView,
    ConfirmSourceRequest,
    DraftCreateRequest,
    DraftUpdateRequest,
    DraftView,
    ImportCreateRequest,
    ImportItemUpdateRequest,
    ImportItemView,
    ImportJobView,
    ProposalMergeRequest,
    ProposalReviewRequest,
    ProposalView,
    PublishRequest,
    PublishedView,
    UsageDocumentView,
    UsageEventView,
    UsageRequest,
)
from backend.app.domain.document import DocumentMetadata
from backend.app.domain.source import SourceMetadata
from backend.app.domain.taxonomy import TaxonomyRegistry as TaxonomyRegistryModel
from backend.app.domain.term import TermMetadata
from backend.app.services.markdown_parser import parse_markdown, parse_yaml
from backend.app.services.publisher import PublishedResult


router = APIRouter(prefix="/api", tags=["Runtime"])


@router.post("/drafts", response_model=DraftView, status_code=status.HTTP_201_CREATED)
async def create_draft(body: DraftCreateRequest, request: Request):
    root = request.app.state.repository_root
    target = _draft_target_path(root, body.entity_type, body.entity_id, body.content,
                                request.app.state.runtime_connection)
    git = request.app.state.git_manager
    return asdict(
        request.app.state.draft_service.create(
            body.entity_type,
            body.entity_id,
            body.content,
            git.current_revision(),
            git.content_hash(target),
        )
    )


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


@router.get("/proposals", response_model=list[ProposalView])
async def list_proposals(
    request: Request,
    target_type: Optional[Literal["document", "term", "source", "taxonomy"]] = None,
    target_id: Optional[str] = None,
    kind: Optional[str] = None,
    proposal_status: Optional[Literal[
        "proposed", "drafted", "approved", "merged", "rejected", "stale"
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


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalView)
async def approve_proposal(proposal_id: str, body: ProposalReviewRequest, request: Request):
    proposal = request.app.state.proposal_service.get(proposal_id)
    draft = _proposal_draft(request, proposal)
    current_hash = hashlib.sha256(draft.content.encode("utf-8")).hexdigest()
    result = request.app.state.proposal_service.approve(
        proposal_id, current_hash, body.review_note
    )
    return asdict(result)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalView)
async def reject_proposal(proposal_id: str, body: ProposalReviewRequest, request: Request):
    if not body.review_note or not body.review_note.strip():
        raise ValueError("review_note is required to reject a Proposal")
    result = request.app.state.proposal_service.reject(
        proposal_id,
        body.review_note,
        candidate_type=body.candidate_type,
        candidate_value=body.candidate_value,
        scope=body.scope,
    )
    return asdict(result)


@router.post("/proposals/{proposal_id}/merge", response_model=PublishedView)
async def merge_proposal(
    proposal_id: str,
    request: Request,
    body: ProposalMergeRequest = ProposalMergeRequest(),
):
    proposal = request.app.state.proposal_service.get(proposal_id)
    draft = _proposal_draft(request, proposal)
    return _published_view(
        request.app.state.publisher.publish(draft.id, proposal_id, body.commit_message)
    )


@router.post("/publish", response_model=PublishedView)
async def publish(body: PublishRequest, request: Request):
    result = request.app.state.publisher.publish(
        body.draft_id, body.proposal_id, body.commit_message
    )
    return _published_view(result)


@router.post("/imports", response_model=ImportJobView, status_code=status.HTTP_201_CREATED)
async def create_import(body: ImportCreateRequest, request: Request):
    paths = _upload_paths(request.app.state.repository_root, body.paths)
    job = request.app.state.import_service.stage_paths(paths, body.profile)
    return _import_job_view(request.app.state.import_service, job)


@router.get("/imports", response_model=list[ImportJobView])
async def list_imports(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return [
        _import_job_view(request.app.state.import_service, job)
        for job in request.app.state.import_service.list_jobs(limit, offset)
    ]


@router.get("/imports/{job_id}", response_model=ImportJobView)
async def get_import(job_id: str, request: Request):
    return _import_job_view(request.app.state.import_service,
                            request.app.state.import_service.get_job(job_id))


@router.post("/imports/blank-document", response_model=DraftView, status_code=status.HTTP_201_CREATED)
async def create_blank_document(body: BlankDocumentRequest, request: Request):
    draft = request.app.state.import_service.create_blank_document(
        body.title, body.document_type, body.entity_id
    )
    return asdict(draft)


@router.put("/import-items/{item_id}", response_model=ImportItemView)
async def update_import_item(item_id: str, body: ImportItemUpdateRequest, request: Request):
    item = request.app.state.import_service.update_markdown_item(item_id, body.content)
    return _import_item_view(item)


@router.post("/import-items/{item_id}/draft", response_model=DraftView, status_code=status.HTTP_201_CREATED)
async def create_import_draft(item_id: str, request: Request):
    draft = request.app.state.import_service.create_draft(item_id)
    return asdict(draft)


@router.post("/import-items/{item_id}/confirm-source", response_model=DraftView, status_code=status.HTTP_201_CREATED)
async def confirm_import_source(item_id: str, body: ConfirmSourceRequest, request: Request):
    draft = request.app.state.import_service.confirm_pdf_source(
        item_id, **body.model_dump(exclude_none=True)
    )
    return asdict(draft)


@router.post("/import-bundles/associate", response_model=BundleAssociationView)
async def associate_import_bundle(body: BundleAssociationRequest, request: Request):
    markdown, pdf = request.app.state.import_service.associate_bundle(
        body.markdown_item_id, body.pdf_item_id
    )
    return {"markdown": _import_item_view(markdown), "pdf": _import_item_view(pdf)}


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


def _proposal_draft(request: Request, proposal):
    draft_id = proposal.payload.get("draft_id")
    if not isinstance(draft_id, str) or not draft_id:
        raise ValueError("Proposal is not associated with a Draft")
    draft = request.app.state.draft_service.get(draft_id)
    if draft.entity_type != proposal.target_type or draft.entity_id != proposal.target_id:
        raise ValueError("Proposal target does not match its Draft")
    return draft


def _draft_target_path(
    root: Path, entity_type: str, entity_id: str, content: str, connection
) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entity_id):
        raise ValueError("entity_id must be a lowercase canonical slug")
    if entity_type in {"document", "term"}:
        parsed = parse_markdown(content)
        if parsed.frontmatter is None:
            raise ValueError("Draft content must have valid YAML frontmatter")
        entity = (
            DocumentMetadata.model_validate(parsed.frontmatter)
            if entity_type == "document"
            else TermMetadata.model_validate(parsed.frontmatter)
        )
        if entity.id != entity_id:
            raise ValueError("Draft content id must match entity_id")
        table = "document_index" if entity_type == "document" else "term_index"
        # Existing Documents retain their indexed path; new ones use their schema type.
        # Terms have one canonical directory and are resolved the same way.
        if entity_type == "document":
            row = _index_path(connection, table, entity_id)
            if row is not None:
                indexed = json.loads(row["metadata_json"])
                if indexed.get("type") != entity.type:
                    raise ValueError("A Document Draft cannot change its canonical type")
                return root / row["path"]
            folder = {"paper-note": "papers", "learning-note": "learning", "course-note": "courses"}[entity.type]
            return root / "knowledge" / "documents" / folder / "{}.md".format(entity_id)
        row = _index_path(connection, table, entity_id)
        return root / row["path"] if row is not None else root / "knowledge" / "terms" / "{}.md".format(entity_id)
    if entity_type == "source":
        entity = SourceMetadata.model_validate(parse_yaml(content))
        if entity.id != entity_id:
            raise ValueError("Source Draft content id must match entity_id")
        return root / "knowledge" / "sources" / "{}.yaml".format(entity_id)
    files = {"domains": "domains.yaml", "topics": "topics.yaml", "tags": "tags.yaml"}
    if entity_type == "taxonomy" and entity_id in files:
        TaxonomyRegistryModel.model_validate(parse_yaml(content))
        return root / "knowledge" / "taxonomy" / files[entity_id]
    raise ValueError("Unsupported canonical Draft target")


def _index_path(connection, table: str, entity_id: str):
    # The table names are fixed by entity_type above; values remain parameterized.
    return connection.execute(
        "SELECT path, metadata_json FROM {} WHERE entity_id = ?".format(table),
        (entity_id,),
    ).fetchone()


def _upload_paths(repository_root: Path, supplied_paths: list[str]) -> list[Path]:
    uploads_root = (Path(repository_root) / "storage" / "uploads").resolve()
    result = []
    for supplied in supplied_paths:
        relative = Path(supplied)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise ValueError("Import paths must stay under storage/uploads")
        candidate = uploads_root / relative
        cursor = uploads_root
        for part in relative.parts:
            if part == ".":
                continue
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Import paths cannot use symbolic links")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(uploads_root)
        except ValueError as error:
            raise ValueError("Import paths must stay under storage/uploads") from error
        result.append(resolved)
    return result


def _import_job_view(service, job) -> dict:
    return {**asdict(job), "items": [_import_item_view(item) for item in service.get_items(job.id)]}


def _import_item_view(item) -> dict:
    metadata = dict(item.metadata)
    display_name = metadata.get("display_name") or Path(item.path).name
    metadata.pop("staging_path", None)
    metadata.pop("canonical_path", None)
    return {
        "id": item.id,
        "job_id": item.job_id,
        "display_name": display_name,
        "file_type": item.file_type,
        "sha256": item.sha256,
        "status": item.status,
        "detected_entity_type": item.detected_entity_type,
        "metadata": metadata,
    }


def _published_view(result: PublishedResult) -> dict:
    return {
        "draft_id": result.draft_id,
        "entity_type": result.entity_type,
        "entity_id": result.entity_id,
        "commit_revision": result.commit_revision,
        "proposal_id": result.proposal_id,
        "warnings": list(result.warnings),
    }


def _usage_documents(rows: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in row.items() if key != "path"}
        for row in rows
    ]
