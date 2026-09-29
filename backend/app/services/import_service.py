"""Stage Markdown/PDF imports and turn reviewed candidates into Drafts."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import hashlib
import os
import re
import shutil
import uuid

import yaml
from pydantic import ValidationError

from backend.app.domain.document import DocumentMetadata
from backend.app.domain.imports import ImportItem, ImportJob
from backend.app.domain.runtime import Draft
from backend.app.domain.source import SourceMetadata
from backend.app.domain.term import TermMetadata
from backend.app.repositories.import_repository import (
    ImportItemNotFoundError,
    ImportRepository,
)
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.resolution import normalize_key
from backend.app.services.source_registry import SourceRegistry
from backend.app.services.source_resolver import SourceResolver
from backend.app.services.style_linter import lint_markdown, load_writing_standard


class ImportValidationError(RuntimeError):
    pass


class ImportService:
    def __init__(
        self,
        repository_root: Union[str, Path],
        repository: ImportRepository,
        draft_service: DraftService,
        git_manager: Optional[GitManager] = None,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        self.storage_root = self.repository_root / "storage"
        self.staging_root = self.storage_root / "staging"
        self.papers_root = self.storage_root / "papers"
        self.repository = repository
        self.draft_service = draft_service
        self.git = git_manager or GitManager(self.repository_root)
        self.standard = load_writing_standard(
            self.repository_root / "config" / "writing-standard.yaml"
        )
        self._ensure_storage_roots()

    def stage_paths(
        self, paths: Sequence[Union[str, Path]], profile: str = "standard"
    ) -> ImportJob:
        if profile not in {"standard", "legacy"}:
            raise ValueError("profile must be 'standard' or 'legacy'")
        job_id = uuid.uuid4().hex
        now = _utc_now()
        self.repository.create_job(
            ImportJob(job_id, "staging", profile, now, now, None)
        )
        self.staging_root.mkdir(parents=True, exist_ok=True)

        sources, errors = _expand_inputs(paths)
        for source in sources:
            try:
                self._stage_file(job_id, profile, source)
            except Exception as error:
                self._create_failed_item(job_id, source, error)
                errors.append("{}: {}".format(source, error))

        self._suggest_bundle_associations(job_id)
        items = self.repository.list_items(job_id)
        usable = [item for item in items if item.status != "failed"]
        status = "ready" if usable else "failed"
        error_message = "; ".join(errors) if errors else None
        if not sources and not errors:
            error_message = "No Markdown or PDF files were found"
            status = "failed"
        return self.repository.update_job(job_id, status, _utc_now(), error_message)

    def get_job(self, job_id: str) -> ImportJob:
        job = self.repository.get_job(job_id)
        if job is None:
            raise LookupError("Import Job '{}' does not exist".format(job_id))
        return job

    def get_items(self, job_id: str) -> List[ImportItem]:
        self.get_job(job_id)
        return self.repository.list_items(job_id)

    def update_markdown_item(self, item_id: str, content: str) -> ImportItem:
        item = self._get_item(item_id)
        if item.file_type != "markdown" or item.status in {"duplicate", "failed", "drafted"}:
            raise ImportValidationError("This Import Item cannot be edited")
        if not isinstance(content, str):
            raise ValueError("Markdown content must be text")
        stage_path = self._staged_path(item)
        _atomic_write(stage_path, content.encode("utf-8"))
        metadata = dict(item.metadata)
        metadata.update(self._analyze_markdown(content, metadata.get("profile", "standard")))
        updated = ImportItem(
            id=item.id,
            job_id=item.job_id,
            path=item.path,
            file_type=item.file_type,
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            status=metadata.pop("candidate_status"),
            detected_entity_type=metadata.get("detected_entity_type"),
            metadata=metadata,
        )
        return self.repository.update_item(updated)

    def create_draft(self, item_id: str) -> Draft:
        item = self._get_item(item_id)
        if item.status == "duplicate":
            raise ImportValidationError("Duplicate files do not create new Drafts")
        if item.status in {"drafted", "confirmed", "failed"}:
            raise ImportValidationError("Import Item is in '{}' status".format(item.status))
        if item.file_type != "markdown":
            raise ImportValidationError("PDF-only imports create Source Drafts, not Document Drafts")

        stage_path = self._staged_path(item)
        content = stage_path.read_text(encoding="utf-8")
        profile = item.metadata.get("profile", "standard")
        if profile == "legacy":
            content = _apply_legacy_defaults(content)
        parsed = parse_markdown(content)
        if parsed.frontmatter is None:
            raise ImportValidationError("Markdown frontmatter must be completed before creating a Draft")

        entity_type = item.detected_entity_type or "document"
        try:
            metadata = (
                DocumentMetadata.model_validate(parsed.frontmatter)
                if entity_type == "document"
                else TermMetadata.model_validate(parsed.frontmatter)
                if entity_type == "term"
                else None
            )
        except ValidationError as error:
            raise ImportValidationError("Canonical metadata is invalid: {}".format(error)) from error
        if metadata is None:
            raise ImportValidationError("Only Document and Term Markdown can create Drafts")

        issues = lint_markdown(
            content,
            entity_type=entity_type,
            standard=self.standard,
            maintenance_status=(metadata.maintenance.status if metadata.maintenance else None),
        )

        if entity_type == "document":
            folder = {
                "paper-note": "papers",
                "learning-note": "learning",
                "course-note": "courses",
            }[metadata.type]
            target = Path("knowledge") / "documents" / folder / "{}.md".format(metadata.id)
        else:
            target = Path("knowledge") / "terms" / "{}.md".format(metadata.id)
        revision = self.git.current_revision()
        content_hash = self.git.content_hash(target)
        draft = self.draft_service.create(
            entity_type,
            metadata.id,
            content,
            revision,
            content_hash,
        )

        item_metadata = dict(item.metadata)
        item_metadata.update(
            {
                "draft_id": draft.id,
                "canonical_path": target.as_posix(),
                "candidate_title": metadata.title,
                "lint_issues": [
                    {
                        "code": issue.code,
                        "message": issue.message,
                        "line": issue.line,
                        "severity": issue.severity,
                    }
                    for issue in issues
                ],
            }
        )
        self.repository.update_item(
            ImportItem(
                id=item.id,
                job_id=item.job_id,
                path=item.path,
                file_type=item.file_type,
                sha256=item.sha256,
                status="drafted",
                detected_entity_type=entity_type,
                metadata=item_metadata,
            )
        )
        return draft

    def confirm_pdf_source(
        self,
        item_id: str,
        source_id: Optional[str] = None,
        title: Optional[str] = None,
        source_type: str = "paper",
        authors: Optional[List[str]] = None,
        year: Optional[int] = None,
        doi: Optional[str] = None,
        arxiv_id: Optional[str] = None,
        zotero_key: Optional[str] = None,
    ) -> Draft:
        item = self._get_item(item_id)
        if item.file_type != "pdf" or item.status != "ready":
            raise ImportValidationError("Only a ready PDF candidate can create a Source Draft")
        stage_path = self._staged_path(item)
        if not stage_path.is_file() or not stage_path.read_bytes().startswith(b"%PDF-"):
            raise ImportValidationError("Staged PDF is missing or invalid")

        source_registry = SourceRegistry.load(self.knowledge_root / "sources")
        resolver = SourceResolver(source_registry)
        match = source_registry.get(source_id) if source_id else None
        if source_id and match is None:
            raise ImportValidationError("Selected Source '{}' does not exist".format(source_id))
        if not source_id:
            identifiers = [value for value in (doi, arxiv_id, zotero_key) if value]
            queries = identifiers or [title or item.metadata.get("candidate_title", "")]
            for query in queries:
                if not query:
                    continue
                resolution = resolver.resolve(query)
                if resolution.status == "ambiguous":
                    raise ImportValidationError(
                        "Source match is ambiguous; select a canonical Source before continuing"
                    )
                if resolution.status == "resolved":
                    match = source_registry.get(resolution.entity_id)
                    break

        if match is not None:
            if source_id is not None and source_id != match.id:
                raise ImportValidationError(
                    "Provided Source id conflicts with the resolved canonical Source"
                )
            source_id = match.id
            title = title or match.title
            source_type = match.type
            authors = authors if authors is not None else list(match.authors)
            year = year if year is not None else match.year
            doi = doi or match.identifiers.doi
            arxiv_id = arxiv_id or match.identifiers.arxiv_id
            zotero_key = zotero_key or match.zotero_key
        else:
            title = title or item.metadata.get("candidate_title") or _display_title(
                item.metadata.get("display_name", "Imported PDF")
            )
            source_id = source_id or _slugify(
                title, fallback="source-{}".format(item.sha256[:12])
            )

        source_id = _require_slug(source_id, "source_id")
        storage_path = self.papers_root / "{}.pdf".format(source_id)
        storage_uri = "storage://papers/{}.pdf".format(source_id)
        value = {
            "schema_version": 1,
            "id": source_id,
            "type": source_type,
            "title": title,
            "authors": authors or [],
            "identifiers": {"doi": doi, "arxiv_id": arxiv_id},
            "zotero_key": zotero_key,
            "attachments": {"local_pdf": storage_uri},
        }
        try:
            source = SourceMetadata.model_validate(value)
        except ValidationError as error:
            raise ImportValidationError("Source candidate is invalid: {}".format(error)) from error

        self.papers_root.mkdir(parents=True, exist_ok=True)
        copied_pdf = False
        if storage_path.is_symlink():
            raise ImportValidationError("PDF destination cannot be a symbolic link")
        if storage_path.exists():
            if _sha256_file(storage_path) != item.sha256:
                raise ImportValidationError(
                    "A different PDF is already stored for Source '{}'".format(source_id)
                )
        else:
            _atomic_copy(stage_path, storage_path)
            copied_pdf = True

        source_content = yaml.safe_dump(
            source.model_dump(mode="json", exclude_none=True),
            allow_unicode=True,
            sort_keys=False,
        )
        canonical_path = Path("knowledge") / "sources" / "{}.yaml".format(source_id)
        try:
            draft = self.draft_service.create(
                "source",
                source_id,
                source_content,
                self.git.current_revision(),
                self.git.content_hash(canonical_path),
            )
        except Exception:
            if copied_pdf and storage_path.exists():
                storage_path.unlink()
            raise

        metadata = dict(item.metadata)
        metadata.update(
            {
                "draft_id": draft.id,
                "canonical_path": canonical_path.as_posix(),
                "storage_uri": storage_uri,
                "resolved_source_id": match.id if match is not None else None,
            }
        )
        self.repository.update_item(
            ImportItem(
                id=item.id,
                job_id=item.job_id,
                path=item.path,
                file_type=item.file_type,
                sha256=item.sha256,
                status="drafted",
                detected_entity_type="source",
                metadata=metadata,
            )
        )
        return draft

    def associate_bundle(
        self, markdown_item_id: str, pdf_item_id: str
    ) -> Tuple[ImportItem, ImportItem]:
        markdown = self._get_item(markdown_item_id)
        pdf = self._get_item(pdf_item_id)
        if markdown.job_id != pdf.job_id:
            raise ImportValidationError("Bundle items must belong to the same Import Job")
        if markdown.file_type != "markdown" or pdf.file_type != "pdf":
            raise ImportValidationError("A bundle association requires one Markdown and one PDF")
        if markdown.status in {"duplicate", "failed"} or pdf.status in {"duplicate", "failed"}:
            raise ImportValidationError("Duplicate or failed items cannot be associated")

        markdown_metadata = dict(markdown.metadata)
        pdf_metadata = dict(pdf.metadata)
        markdown_metadata["bundle_association"] = {
            "item_id": pdf.id,
            "status": "confirmed",
        }
        pdf_metadata["bundle_association"] = {
            "item_id": markdown.id,
            "status": "confirmed",
        }
        updated_markdown = self.repository.update_item(
            ImportItem(
                markdown.id, markdown.job_id, markdown.path, markdown.file_type,
                markdown.sha256, markdown.status, markdown.detected_entity_type,
                markdown_metadata,
            )
        )
        updated_pdf = self.repository.update_item(
            ImportItem(
                pdf.id, pdf.job_id, pdf.path, pdf.file_type, pdf.sha256,
                pdf.status, pdf.detected_entity_type, pdf_metadata,
            )
        )
        return updated_markdown, updated_pdf

    def create_blank_document(
        self,
        title: str,
        document_type: str = "learning-note",
        entity_id: Optional[str] = None,
    ) -> Draft:
        if not isinstance(title, str) or not title.strip() or "\n" in title:
            raise ValueError("title must be one non-empty line")
        if document_type not in {"paper-note", "learning-note", "course-note"}:
            raise ValueError("Unsupported Document type")
        entity_id = _require_slug(
            entity_id or _slugify(title, fallback="document-{}".format(uuid.uuid4().hex[:12])),
            "entity_id",
        )
        content = _blank_document_content(entity_id, title.strip(), document_type)
        job_id = uuid.uuid4().hex
        item_id = uuid.uuid4().hex
        now = _utc_now()
        self.staging_root.mkdir(parents=True, exist_ok=True)
        self.repository.create_job(
            ImportJob(job_id, "staging", "new-blank", now, now, None)
        )
        stage_path = self.staging_root / job_id / "{}.md".format(item_id)
        _atomic_write(stage_path, content.encode("utf-8"))
        item = ImportItem(
            id=item_id,
            job_id=job_id,
            path="new:{}".format(entity_id),
            file_type="markdown",
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            status="ready",
            detected_entity_type="document",
            metadata={
                "profile": "standard",
                "display_name": title,
                "staging_path": stage_path.relative_to(self.repository_root).as_posix(),
                "candidate_status": "ready",
                "candidate_title": title,
                "entity_id": entity_id,
                "lint_issues": [],
            },
        )
        self.repository.create_item(item)
        self.repository.update_job(job_id, "ready", _utc_now())
        return self.create_draft(item.id)

    def _stage_file(self, job_id: str, profile: str, source: Path) -> ImportItem:
        if source.is_symlink() or not source.is_file():
            raise ValueError("Import input must be a regular file")
        extension = source.suffix.lower()
        if extension not in {".md", ".pdf"}:
            raise ValueError("Only .md and .pdf files are supported in Phase 6")
        file_type = "markdown" if extension == ".md" else "pdf"
        sha256 = _sha256_file(source)
        canonical_duplicate = self._canonical_duplicate(file_type, sha256)
        prior_duplicate = self.repository.find_duplicate(file_type, sha256)
        item_id = uuid.uuid4().hex
        metadata = {
            "profile": profile,
            "display_name": source.name,
        }
        if canonical_duplicate:
            metadata.update(
                {"duplicate_kind": "canonical", "duplicate_of": canonical_duplicate}
            )
            return self.repository.create_item(
                ImportItem(
                    item_id, job_id, str(source), file_type, sha256, "duplicate",
                    "document" if file_type == "markdown" else "source", metadata,
                )
            )
        if prior_duplicate is not None:
            metadata.update(
                {
                    "duplicate_kind": "import_item",
                    "duplicate_of": prior_duplicate.id,
                }
            )
            return self.repository.create_item(
                ImportItem(
                    item_id, job_id, str(source), file_type, sha256, "duplicate",
                    prior_duplicate.detected_entity_type, metadata,
                )
            )

        if file_type == "pdf" and not _is_pdf(source):
            raise ValueError("File does not have a PDF header")
        stage_path = self.staging_root / job_id / "{}.{}".format(
            item_id, "md" if file_type == "markdown" else "pdf"
        )
        _atomic_copy(source, stage_path)
        if _sha256_file(stage_path) != sha256:
            stage_path.unlink(missing_ok=True)
            raise ValueError("Input changed while it was copied to Staging")
        metadata["staging_path"] = stage_path.relative_to(self.repository_root).as_posix()

        if file_type == "markdown":
            try:
                content = stage_path.read_text(encoding="utf-8")
            except UnicodeError:
                stage_path.unlink(missing_ok=True)
                raise ValueError("Markdown file must be UTF-8")
            analysis = self._analyze_markdown(content, profile)
            metadata.update(analysis)
            status = metadata.pop("candidate_status")
            detected_type = metadata.get("detected_entity_type")
        else:
            metadata["candidate_title"] = _display_title(source.stem)
            metadata["suggested_source_id"] = _slugify(
                metadata["candidate_title"], fallback="source-{}".format(sha256[:12])
            )
            try:
                metadata["source_candidates"] = self._source_candidates(
                    metadata["candidate_title"]
                )
            except Exception as error:
                metadata["source_candidates"] = []
                metadata["source_resolution_error"] = str(error)
            metadata["association_status"] = "unassociated"
            status = "ready"
            detected_type = "source"
        return self.repository.create_item(
            ImportItem(
                item_id, job_id, str(source), file_type, sha256,
                status, detected_type, metadata,
            )
        )

    def _analyze_markdown(self, content: str, profile: str) -> dict:
        parsed = parse_markdown(content)
        detected_type = "document"
        if parsed.frontmatter and parsed.frontmatter.get("type") in {"concept", "vocabulary"}:
            detected_type = "term"
        issues = lint_markdown(
            content,
            entity_type=detected_type,
            standard=self.standard,
            maintenance_status="legacy" if profile == "legacy" else None,
        )
        entity_id = None
        title = None
        resolution_candidates = []
        try:
            if parsed.frontmatter is not None:
                entity = (
                    DocumentMetadata.model_validate(parsed.frontmatter)
                    if detected_type == "document"
                    else TermMetadata.model_validate(parsed.frontmatter)
                )
                entity_id = entity.id
                title = entity.title
                resolution_candidates = self._document_candidates(
                    entity_id, entity.title
                ) if detected_type == "document" else []
        except ValidationError:
            pass
        return {
            "detected_entity_type": detected_type,
            "entity_id": entity_id,
            "candidate_title": title,
            "resolver_candidates": resolution_candidates,
            "lint_issues": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "line": issue.line,
                    "severity": issue.severity,
                }
                for issue in issues
            ],
            "candidate_status": (
                "ready"
                if not issues and entity_id and not resolution_candidates
                else "needs_review"
            ),
        }

    def _document_candidates(self, entity_id: str, title: str) -> list[dict]:
        matches = []
        normalized_title = normalize_key(title)
        root = self.knowledge_root / "documents"
        if not root.exists():
            return matches
        for path in sorted(root.rglob("*.md")):
            try:
                parsed = parse_markdown(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            metadata = parsed.frontmatter or {}
            current_id = metadata.get("id")
            current_title = metadata.get("title")
            if current_id == entity_id or (
                isinstance(current_title, str)
                and normalize_key(current_title) == normalized_title
            ):
                matches.append(
                    {
                        "entity_id": current_id,
                        "title": current_title,
                        "path": path.relative_to(self.repository_root).as_posix(),
                        "matched_by": "id" if current_id == entity_id else "title",
                    }
                )
        return matches

    def _source_candidates(self, title: str) -> list[dict]:
        registry = SourceRegistry.load(self.knowledge_root / "sources")
        resolution = SourceResolver(registry).resolve(title)
        return [
            {
                "entity_id": candidate.id,
                "title": candidate.title,
                "matched_by": candidate.matched_by,
                "score": candidate.score,
            }
            for candidate in resolution.candidates
        ]

    def _canonical_duplicate(self, file_type: str, sha256: str) -> Optional[str]:
        roots = (
            [self.knowledge_root / "documents", self.knowledge_root / "terms"]
            if file_type == "markdown"
            else [self.papers_root]
        )
        for root in roots:
            if not root.exists():
                continue
            extension = ".md" if file_type == "markdown" else ".pdf"
            for path in sorted(root.rglob("*{}".format(extension))):
                if path.is_file() and _sha256_file(path) == sha256:
                    return path.relative_to(self.repository_root).as_posix()
        return None

    def _suggest_bundle_associations(self, job_id: str) -> None:
        items = self.repository.list_items(job_id)
        markdown = [
            item for item in items
            if item.file_type == "markdown" and item.status not in {"failed", "duplicate"}
        ]
        pdfs = [
            item for item in items
            if item.file_type == "pdf" and item.status not in {"failed", "duplicate"}
        ]
        groups: Dict[Tuple[str, str], Dict[str, list]] = {}
        for item in markdown + pdfs:
            path = Path(item.path)
            key = (str(path.parent).casefold(), normalize_key(path.stem))
            group = groups.setdefault(key, {"markdown": [], "pdf": []})
            group[item.file_type].append(item)
        for group in groups.values():
            if len(group["markdown"]) != 1 or len(group["pdf"]) != 1:
                continue
            markdown_item = group["markdown"][0]
            pdf_item = group["pdf"][0]
            for item, other in ((markdown_item, pdf_item), (pdf_item, markdown_item)):
                metadata = dict(item.metadata)
                metadata["bundle_association"] = {
                    "item_id": other.id,
                    "status": "suggested",
                }
                self.repository.update_item(
                    ImportItem(
                        item.id, item.job_id, item.path, item.file_type,
                        item.sha256, item.status, item.detected_entity_type, metadata,
                    )
                )

    def _create_failed_item(self, job_id: str, source: Path, error: Exception) -> None:
        extension = source.suffix.lower()
        if extension not in {".md", ".pdf"}:
            return
        file_type = "markdown" if extension == ".md" else "pdf"
        try:
            sha256 = _sha256_file(source) if source.is_file() else "0" * 64
        except OSError:
            sha256 = "0" * 64
        item = ImportItem(
            id=uuid.uuid4().hex,
            job_id=job_id,
            path=str(source),
            file_type=file_type,
            sha256=sha256,
            status="failed",
            detected_entity_type=None,
            metadata={"errors": [str(error)], "display_name": source.name},
        )
        self.repository.create_item(item)

    def _get_item(self, item_id: str) -> ImportItem:
        item = self.repository.get_item(item_id)
        if item is None:
            raise ImportItemNotFoundError("Import Item '{}' does not exist".format(item_id))
        return item

    def _staged_path(self, item: ImportItem) -> Path:
        self._ensure_storage_roots()
        relative = item.metadata.get("staging_path")
        if not isinstance(relative, str):
            raise ImportValidationError("Import Item has no staged file")
        target = (self.repository_root / relative).resolve()
        try:
            target.relative_to(self.staging_root.resolve())
        except ValueError as error:
            raise ImportValidationError("Staging path escaped storage/staging") from error
        return target

    def _ensure_storage_roots(self) -> None:
        for path in (self.storage_root, self.staging_root, self.papers_root):
            if path.is_symlink():
                raise ImportValidationError("Import storage paths cannot be symlinks")
            try:
                path.resolve().relative_to(self.repository_root)
            except ValueError as error:
                raise ImportValidationError("Import storage must remain inside the repository") from error


def _expand_inputs(paths: Sequence[Union[str, Path]]):
    supported = []
    errors = []
    seen = set()
    for supplied in paths:
        path = Path(supplied).expanduser()
        if path.is_symlink():
            errors.append("{}: symbolic links are not imported".format(path))
            continue
        if not path.exists():
            errors.append("{}: path does not exist".format(path))
            continue
        if path.is_file():
            if path.suffix.lower() in {".md", ".pdf"}:
                resolved = path.resolve()
                if resolved not in seen:
                    supported.append(resolved)
                    seen.add(resolved)
            else:
                errors.append("{}: only .md and .pdf files are supported".format(path))
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_symlink() or not child.is_file():
                    continue
                if any(
                    part.startswith(".")
                    or part in {"node_modules", "__pycache__", "runtime", "storage"}
                    for part in child.relative_to(path).parts
                ):
                    continue
                if child.suffix.lower() not in {".md", ".pdf"}:
                    continue
                resolved = child.resolve()
                if resolved not in seen:
                    supported.append(resolved)
                    seen.add(resolved)
    return supported, errors


def _apply_legacy_defaults(content: str) -> str:
    parsed = parse_markdown(content)
    if parsed.frontmatter is None:
        return content
    value = dict(parsed.frontmatter)
    review = dict(value.get("review") or {})
    human = dict(review.get("human") or {})
    human["status"] = "unreviewed"
    review["human"] = human
    value["review"] = review
    value["maintenance"] = {"status": "legacy"}
    frontmatter = yaml.safe_dump(value, allow_unicode=True, sort_keys=False).rstrip()
    lines = content.lstrip("\ufeff").splitlines()
    body = "\n".join(lines[parsed.frontmatter_end_line :]).lstrip("\n")
    return "---\n{}\n---\n{}".format(frontmatter, body)


def _blank_document_content(entity_id: str, title: str, document_type: str) -> str:
    metadata = {
        "schema_version": 1,
        "id": entity_id,
        "title": title,
        "type": document_type,
        "domains": [],
        "topics": [],
        "tags": [],
        "sources": [],
        "review": {"human": {"status": "unreviewed"}},
        "maintenance": {"status": "current"},
        "provenance": {"origin": "authored", "ai_assisted": False},
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    return "---\n{}\n---\n# {}\n".format(frontmatter, title)


def _slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").casefold()).strip("-")
    return slug or fallback


def _require_slug(value: Optional[str], field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError("{} must be a lowercase canonical slug".format(field))
    return value


def _display_title(value: str) -> str:
    return re.sub(r"[._-]+", " ", value).strip() or "Imported PDF"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_pdf(path: Path) -> bool:
    with path.open("rb") as source:
        return source.read(5) == b"%PDF-"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".{}-{}.tmp".format(path.name, uuid.uuid4().hex))
    try:
        with temporary.open("wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".{}-{}.tmp".format(target.name, uuid.uuid4().hex))
    try:
        shutil.copyfile(str(source), str(temporary))
        os.replace(str(temporary), str(target))
    finally:
        if temporary.exists():
            temporary.unlink()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
