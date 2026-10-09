"""Import staging and Draft creation API routes."""

from dataclasses import asdict
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Literal, Optional
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status

from backend.app.api.schemas import (
    BlankDocumentRequest,
    BundleAssociationRequest,
    BundleAssociationView,
    ConfirmSourceRequest,
    DraftView,
    ImportCreateRequest,
    ImportDraftRequest,
    ImportItemContentView,
    ImportItemUpdateRequest,
    ImportItemView,
    ImportJobView,
)

router = APIRouter(prefix="/api", tags=["Runtime"])


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
async def create_import_draft(
    item_id: str, request: Request, body: Optional[ImportDraftRequest] = None
):
    draft = request.app.state.import_service.create_draft(
        item_id, title_override=body.title if body is not None else None
    )
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
