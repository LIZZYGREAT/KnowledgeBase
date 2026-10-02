"""Draft, Proposal, Import, Publish, and Usage API routes."""

from dataclasses import asdict
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Literal, Optional
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile, status

from backend.app.api.schemas import (
    BatchPublishRequest,
    BatchPublishedView,
    BlankDocumentRequest,
    BundleAssociationRequest,
    BundleAssociationView,
    CollectionProgressRequest,
    CollectionProgressView,
    ConfirmSourceRequest,
    DraftCreateRequest,
    DraftAcquireView,
    DraftDeleteRequest,
    DraftRebaseRequest,
    DraftPreflightView,
    DraftUpdateRequest,
    DraftView,
    DraftCompareView,
    ImportCreateRequest,
    ImportItemUpdateRequest,
    ImportItemView,
    ImportItemContentView,
    ImportJobView,
    ProposalApplyRequest,
    ProposalApplyView,
    ProposalRejectRequest,
    ProposalView,
    PublishRequest,
    PublishedView,
    PresentationAnnotationCreateRequest,
    PresentationAnnotationStyleRequest,
    PresentationAnnotationView,
    UsageDocumentView,
    UsageEventView,
    UsageRequest,
)
from backend.app.services.publisher import PublishedResult


router = APIRouter(prefix="/api", tags=["Runtime"])


@router.get("/annotations", response_model=list[PresentationAnnotationView])
async def list_annotations(
    request: Request,
    entity_type: Literal["document", "term"],
    entity_id: str,
):
    entity = request.app.state.knowledge_read_service.get_entity(entity_type, entity_id)
    return [
        asdict(annotation)
        for annotation in request.app.state.annotation_service.list_for_entity(
            entity_type, entity_id, entity["content"] or ""
        )
    ]


@router.get("/annotations/stale", response_model=list[PresentationAnnotationView])
async def list_stale_annotations(request: Request):
    connection = request.app.state.runtime_connection
    entities = []
    rows = connection.execute(
        "SELECT DISTINCT entity_type, entity_id FROM presentation_annotations"
    ).fetchall()
    for row in rows:
        try:
            entity = request.app.state.knowledge_read_service.get_entity(
                row["entity_type"], row["entity_id"]
            )
        except LookupError:
            continue
        entities.append((row["entity_type"], row["entity_id"], entity["content"] or ""))
    return [
        asdict(annotation)
        for annotation in request.app.state.annotation_service.list_stale(entities)
    ]


@router.post(
    "/annotations",
    response_model=PresentationAnnotationView,
    status_code=status.HTTP_201_CREATED,
)
async def create_annotation(body: PresentationAnnotationCreateRequest, request: Request):
    entity = request.app.state.knowledge_read_service.get_entity(
        body.entity_type, body.entity_id
    )
    return asdict(
        request.app.state.annotation_service.create(
            **body.model_dump(), content=entity["content"] or ""
        )
    )


@router.put("/annotations/{annotation_id}", response_model=PresentationAnnotationView)
async def update_annotation_style(
    annotation_id: str,
    body: PresentationAnnotationStyleRequest,
    request: Request,
):
    annotation = request.app.state.annotation_service.get(annotation_id)
    entity = request.app.state.knowledge_read_service.get_entity(
        annotation.entity_type, annotation.entity_id
    )
    return asdict(
        request.app.state.annotation_service.update_style(
            annotation_id,
            body.style_type,
            body.style_value,
            entity["content"] or "",
        )
    )


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, request: Request):
    request.app.state.annotation_service.delete(annotation_id)
    return {"deleted": True}


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
        [item.draft_id for item in body.drafts],
        body.commit_message,
        expected_revisions={
            item.draft_id: item.expected_revision for item in body.drafts
        },
    )
    return {
        "results": [_published_view(item) for item in result.results],
        "commit_revision": result.commit_revision,
        "warnings": list(result.warnings),
    }


@router.post("/imports", response_model=ImportJobView, status_code=status.HTTP_201_CREATED)
async def create_import(body: ImportCreateRequest, request: Request):
    paths = _upload_paths(request.app.state.repository_root, body.paths)
    job = request.app.state.import_service.stage_paths(paths, body.profile)
    return _import_job_view(request.app.state.import_service, job)


@router.post("/imports/upload", response_model=ImportJobView, status_code=status.HTTP_201_CREATED)
async def upload_import(
    request: Request,
    files: list[UploadFile] = File(..., alias="files[]"),
    profile: Literal["standard", "legacy"] = Form("standard"),
):
    temporary_directory: Optional[Path] = None
    try:
        if not files:
            raise HTTPException(status_code=422, detail="Select at least one .md or .pdf file")

        used_names: set[str] = set()
        filenames = [
            _browser_upload_filename(upload.filename, index, used_names)
            for index, upload in enumerate(files)
        ]
        temporary_directory = _create_browser_upload_directory(
            request.app.state.repository_root
        )
        paths = []
        for upload, filename in zip(files, filenames):
            destination = temporary_directory / filename
            with destination.open("xb") as output:
                while chunk := await upload.read(1024 * 1024):
                    output.write(chunk)
            paths.append(destination)
        job = request.app.state.import_service.stage_paths(paths, profile)
        return _import_job_view(request.app.state.import_service, job)
    finally:
        for upload in files:
            await upload.close()
        if temporary_directory is not None:
            shutil.rmtree(temporary_directory, ignore_errors=True)


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


@router.get("/import-items/{item_id}/content", response_model=ImportItemContentView)
async def get_import_item_content(item_id: str, request: Request):
    return request.app.state.import_service.get_item_content(item_id)


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


def _browser_upload_filename(filename: Optional[str], index: int, used_names: set[str]) -> str:
    supplied = (filename or "").replace("\\", "/")
    name = PurePosixPath(supplied).name
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name).strip(" .")
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=422, detail="Every uploaded file needs a filename")
    if Path(name).suffix.lower() not in {".md", ".pdf"}:
        raise HTTPException(
            status_code=422,
            detail="Only .md and .pdf files are supported: {}".format(name),
        )
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.IGNORECASE):
        name = "_" + name

    candidate = name
    stem = Path(name).stem
    suffix = Path(name).suffix
    collision = 1
    while candidate.casefold() in used_names:
        candidate = "{}-{}{}".format(stem, index + collision, suffix)
        collision += 1
    used_names.add(candidate.casefold())
    return candidate


def _create_browser_upload_directory(repository_root: Path) -> Path:
    repository_root = Path(repository_root).resolve()
    storage_root = repository_root / "storage"
    uploads_root = storage_root / "uploads"
    browser_root = uploads_root / "browser"
    for path in (storage_root, uploads_root, browser_root):
        if path.is_symlink():
            raise HTTPException(status_code=422, detail="Browser upload paths cannot be symbolic links")
        try:
            path.resolve().relative_to(repository_root)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="Browser uploads must stay under storage/uploads/browser",
            ) from error
    browser_root.mkdir(parents=True, exist_ok=True)
    temporary_directory = browser_root / uuid.uuid4().hex
    temporary_directory.mkdir(exist_ok=False)
    return temporary_directory


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
        "warnings": list(result.warnings),
    }


def _usage_documents(rows: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in row.items() if key != "path"}
        for row in rows
    ]
