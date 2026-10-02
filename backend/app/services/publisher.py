"""Validate Drafts and publish canonical files through Git."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional, Union

import yaml
from pydantic import ValidationError

from backend.app.domain.collection import Collection
from backend.app.domain.document import DocumentMetadata
from backend.app.domain.runtime import Draft
from backend.app.domain.source import SourceMetadata
from backend.app.domain.taxonomy import TaxonomyRegistry as TaxonomyRegistryModel
from backend.app.domain.term import TermMetadata
from backend.app.services.git_manager import (
    GitConflictError,
    GitManager,
    _atomic_write,
)
from backend.app.services.markdown_parser import parse_markdown, parse_yaml
from backend.app.services.indexer import Indexer
from backend.app.services.proposal_service import ProposalService
from backend.app.services.canonical_validator import (
    find_taxonomy_references,
    find_source_references,
    validate_markdown_references,
    validate_collection_references,
    validate_repository_references,
)
from backend.app.services.collection_registry import CollectionRegistry
from backend.app.services.source_registry import SourceRegistry
from backend.app.services.style_linter import lint_markdown, load_writing_standard
from backend.app.services.taxonomy_registry import (
    TaxonomyRecord,
    TaxonomyRegistry,
)
from backend.app.services.term_registry import AliasIndex, TermRegistry
from backend.app.services.term_resolver import TermResolver


class PublishError(RuntimeError):
    pass


class PublishConflictError(PublishError):
    pass


class PublishValidationError(PublishError):
    pass


@dataclass(frozen=True)
class PublishedResult:
    draft_id: str
    entity_type: str
    entity_id: str
    path: str
    commit_revision: str
    proposal_id: Optional[str] = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class DraftPreflightResult:
    draft_id: str
    valid: bool
    conflict: bool = False
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchPublishedResult:
    results: tuple[PublishedResult, ...]
    commit_revision: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestoredResult:
    commit_revision: str
    warnings: tuple[str, ...] = ()


class Publisher:
    """The business-service entry point for writes to Canonical Knowledge."""

    def __init__(
        self,
        repository_root: Union[str, Path],
        draft_service,
        indexer: Indexer,
        proposal_service: Optional[ProposalService] = None,
        git_manager: Optional[GitManager] = None,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        if indexer is None:
            raise ValueError("Publisher requires an Indexer so published files stay searchable")
        self.draft_service = draft_service
        self.proposal_service = proposal_service
        self.git = git_manager or GitManager(self.repository_root)
        self.indexer = indexer
        self.standard = load_writing_standard(
            self.repository_root / "config" / "writing-standard.yaml"
        )

    def publish(
        self,
        draft_id: str,
        proposal_id: Optional[str] = None,
        commit_message: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> PublishedResult:
        if expected_revision is None:
            expected_revision = self.draft_service.get(draft_id).revision
        proposal_ids = {draft_id: proposal_id} if proposal_id is not None else None
        result = self.publish_batch(
            [draft_id], commit_message, proposal_ids, {draft_id: expected_revision}
        )
        return result.results[0]

    def preflight(self, draft_id: str) -> DraftPreflightResult:
        """Validate a Draft without writing canonical files or creating a Git commit."""
        draft = self.draft_service.get(draft_id)
        try:
            path, metadata = self._target_path(draft, draft.content)
        except (ValueError, ValidationError, yaml.YAMLError, TypeError) as error:
            return DraftPreflightResult(draft_id, False, errors=(str(error),))

        try:
            self.git.assert_base(draft.base_git_revision, draft.base_content_hash, path)
        except (GitConflictError, ValueError) as error:
            return DraftPreflightResult(draft_id, False, conflict=True, errors=(str(error),))

        previous = path.read_bytes() if path.is_file() else None
        if previous == draft.content.encode("utf-8"):
            return DraftPreflightResult(
                draft_id, False, errors=("Draft has no canonical changes to publish",)
            )

        try:
            warnings = self._validate_candidate(
                draft, draft.content, path, metadata, validate_references=True
            )
            if draft.entity_type == "collection":
                current = CollectionRegistry.load(self.knowledge_root / "collections")
                proposed = [
                    collection
                    for collection in current.collections
                    if collection.id != metadata.id
                ] + [metadata]
                issues = validate_collection_references(self.repository_root, proposed)
                if issues:
                    raise PublishValidationError(
                        "; ".join(
                            "{}: {}".format(issue.path, issue.message) for issue in issues
                        )
                    )
        except (PublishValidationError, ValueError, OSError, yaml.YAMLError, TypeError) as error:
            return DraftPreflightResult(draft_id, False, errors=(str(error),))

        return DraftPreflightResult(draft_id, True, warnings=tuple(warnings))

    def publish_batch(
        self,
        draft_ids,
        commit_message: Optional[str] = None,
        proposal_ids: Optional[dict[str, str]] = None,
        expected_revisions: Optional[dict[str, int]] = None,
    ) -> BatchPublishedResult:
        """Validate and publish multiple Drafts in one canonical Git commit."""
        if isinstance(draft_ids, (str, bytes)) or not draft_ids:
            raise ValueError("At least one Draft id is required")
        draft_ids = list(draft_ids)
        if len(draft_ids) != len(set(draft_ids)):
            raise PublishValidationError("Draft ids in a batch must be unique")
        proposal_ids = proposal_ids or {}
        if set(proposal_ids) - set(draft_ids):
            raise PublishValidationError("A Proposal may only be applied to a Draft in the batch")
        if expected_revisions is not None and set(expected_revisions) != set(draft_ids):
            raise PublishValidationError(
                "Every Draft in a publish batch must include its reviewed revision"
            )

        prepared = []
        target_paths = set()
        for draft_id in draft_ids:
            draft = self.draft_service.get(draft_id)
            expected_revision = (
                expected_revisions[draft_id]
                if expected_revisions is not None
                else draft.revision
            )
            if draft.revision != expected_revision:
                raise PublishConflictError(
                    "Draft changed after review. Refresh the Publish Review before publishing. "
                    "(expected revision {}, current revision {})".format(
                        expected_revision, draft.revision
                    )
                )
            content = draft.content
            proposal = None
            proposal_id = proposal_ids.get(draft.id)
            if proposal_id is not None:
                if self.proposal_service is None:
                    raise PublishError("ProposalService is required to apply a Proposal")
                proposal = self.proposal_service.get(proposal_id)
                if proposal.target_type != draft.entity_type or proposal.target_id != draft.entity_id:
                    raise PublishValidationError("Proposal target does not match the Draft")
                proposed_content = proposal.payload.get("content")
                if not isinstance(proposed_content, str):
                    raise PublishValidationError(
                        "Publishable Proposal payload must include full Markdown/YAML 'content'"
                    )
                content = proposed_content

            try:
                path, metadata = self._target_path(draft, content)
            except (ValueError, ValidationError, yaml.YAMLError, TypeError) as error:
                raise PublishValidationError(str(error)) from error

            try:
                self.git.assert_base(draft.base_git_revision, draft.base_content_hash, path)
            except (GitConflictError, ValueError) as error:
                raise PublishConflictError(str(error)) from error

            if path.resolve() in target_paths:
                raise PublishValidationError("A batch cannot publish the same canonical path twice")
            target_paths.add(path.resolve())

            draft_content_hash = hashlib.sha256(draft.content.encode("utf-8")).hexdigest()
            if proposal is not None:
                proposal = self.proposal_service.assert_applicable(
                    proposal.id, draft_content_hash
                )

            previous = path.read_bytes() if path.is_file() else None
            new_content = content.encode("utf-8")
            if previous == new_content:
                raise PublishError(
                    "Draft '{}' has no canonical changes to publish".format(draft.id)
                )
            prepared.append(
                {
                    "draft": draft,
                    "proposal": proposal,
                    "content": content,
                    "content_hash": draft_content_hash,
                    "path": path,
                    "metadata": metadata,
                    "previous": previous,
                    "new_content": new_content,
                    "warnings": [],
                }
            )

        for item in prepared:
            item["warnings"] = self._validate_candidate(
                item["draft"],
                item["content"],
                item["path"],
                item["metadata"],
                validate_references=False,
            )

        try:
            for item in prepared:
                _atomic_write(item["path"], item["new_content"])

            reference_issues = validate_repository_references(self.repository_root)
            if reference_issues:
                raise PublishValidationError(
                    "; ".join(
                        "{}: {}".format(issue.path, issue.message)
                        for issue in reference_issues
                    )
                )

            message = commit_message or self._default_batch_commit_message(prepared)
            commit_revision = self.git.commit_many(
                [item["path"] for item in prepared], message
            )
        except Exception as error:
            rollback_errors = self._restore_prepared_files(prepared)
            if rollback_errors:
                raise PublishError(
                    "Batch publish failed and canonical rollback was incomplete: {}".format(
                        "; ".join(rollback_errors)
                    )
                ) from error
            raise

        post_publish_warnings = []
        for item in prepared:
            draft = item["draft"]
            try:
                self.draft_service.discard(draft.id, draft.revision)
            except Exception as error:
                post_publish_warnings.append(
                    "Draft cleanup failed after commit for '{}': {}".format(draft.id, error)
                )
            proposal = item["proposal"]
            if proposal is not None:
                try:
                    self.proposal_service.merge(proposal.id, item["content_hash"])
                except Exception as error:
                    post_publish_warnings.append(
                        "Proposal status update failed after commit: {}".format(error)
                    )
            elif self.proposal_service is not None:
                try:
                    self.proposal_service.finalize_draft_publish(
                        draft, item["content"]
                    )
                except Exception as error:
                    post_publish_warnings.append(
                        "Proposal status update failed after commit: {}".format(error)
                    )

        for item in prepared:
            try:
                self.indexer.update_path(item["path"])
            except Exception as error:
                post_publish_warnings.append(
                    "Index update failed; run `python tools/kb.py rebuild`: {}".format(error)
                )

        results = tuple(
            PublishedResult(
                draft_id=item["draft"].id,
                entity_type=item["draft"].entity_type,
                entity_id=item["draft"].entity_id,
                path=item["path"].relative_to(self.repository_root).as_posix(),
                commit_revision=commit_revision,
                proposal_id=item["proposal"].id if item["proposal"] else None,
                warnings=tuple(item["warnings"] + post_publish_warnings),
            )
            for item in prepared
        )
        return BatchPublishedResult(
            results=results,
            commit_revision=commit_revision,
            warnings=tuple(post_publish_warnings),
        )

    def restore(
        self,
        path: Union[str, Path],
        revision: str,
        commit_message: Optional[str] = None,
    ) -> RestoredResult:
        """Restore a canonical file by creating a new commit through GitManager."""
        historical_content = self.git.read_at_revision(path, revision)
        restore_warnings = self._validate_restore_candidate(path, historical_content)
        commit_revision = self.git.restore(path, revision, commit_message)
        warnings = list(restore_warnings)
        try:
            self.indexer.update_path(path)
        except Exception as error:
            warnings.append(
                "Index update failed; run `python tools/kb.py rebuild`: {}".format(error)
            )
        return RestoredResult(commit_revision, tuple(warnings))

    def _validate_restore_candidate(
        self, path: Union[str, Path], historical_content: Optional[bytes]
    ) -> list[str]:
        relative_path = self.git._relative_knowledge_path(path)
        parts = Path(relative_path).parts
        if (
            len(parts) == 4
            and parts[:2] == ("knowledge", "documents")
            and parts[3].endswith(".md")
        ):
            entity_type = "document"
        elif (
            len(parts) == 3
            and parts[:2] == ("knowledge", "terms")
            and parts[2].endswith(".md")
        ):
            entity_type = "term"
        elif (
            len(parts) == 3
            and parts[:2] == ("knowledge", "sources")
            and parts[2].endswith(".yaml")
        ):
            entity_type = "source"
        elif (
            len(parts) == 3
            and parts[:2] == ("knowledge", "taxonomy")
            and parts[2] in {"domains.yaml", "topics.yaml", "tags.yaml"}
        ):
            entity_type = "taxonomy"
        elif (
            len(parts) == 3
            and parts[:2] == ("knowledge", "collections")
            and parts[2].endswith(".yaml")
        ):
            entity_type = "collection"
        else:
            raise PublishValidationError(
                "Restore target is not a supported canonical entity path"
            )

        if historical_content is None:
            if entity_type in {"document", "term", "collection"}:
                return []
            if entity_type == "source":
                references = find_source_references(
                    self.repository_root, {Path(relative_path).stem}
                )
                if references:
                    raise PublishValidationError(
                        "; ".join(
                            "{}: {}".format(issue.path, issue.message)
                            for issue in references
                        )
                    )
                return []
            raise PublishValidationError(
                "A Taxonomy Registry cannot be restored to an absent file"
            )

        try:
            content = historical_content.decode("utf-8")
            candidate = SimpleNamespace(
                entity_type=entity_type, entity_id=Path(relative_path).stem
            )
            candidate_path, metadata = self._target_path(candidate, content)
            if candidate_path.resolve() != (self.repository_root / relative_path).resolve():
                raise PublishValidationError(
                    "Restore content does not match its canonical path"
                )
            warnings = self._validate_candidate(
                candidate,
                content,
                candidate_path,
                metadata,
                allow_style_warnings=True,
            )
            if entity_type == "collection":
                issues = validate_collection_references(self.repository_root, [metadata])
                if issues:
                    raise PublishValidationError(
                        "; ".join(
                            "{}: {}".format(issue.path, issue.message) for issue in issues
                        )
                    )
            return warnings
        except PublishValidationError:
            raise
        except (
            UnicodeError,
            ValueError,
            ValidationError,
            yaml.YAMLError,
            TypeError,
        ) as error:
            raise PublishValidationError(
                "Restore content is not valid canonical content: {}".format(error)
            ) from error

    def _target_path(self, draft: Draft, content: str):
        if not isinstance(content, str):
            raise ValueError("Canonical content must be text")
        entity_id = _require_slug(draft.entity_id, "entity_id")
        if draft.entity_type in {"document", "term"}:
            parsed = parse_markdown(content)
            if parsed.frontmatter is None:
                raise ValueError("Canonical Markdown requires valid YAML frontmatter")
            if draft.entity_type == "document":
                metadata = DocumentMetadata.model_validate(parsed.frontmatter)
                folder = {
                    "paper-note": "papers",
                    "learning-note": "learning",
                    "course-note": "courses",
                }[metadata.type]
                relative = (
                    Path("knowledge")
                    / "documents"
                    / folder
                    / "{}.md".format(entity_id)
                )
            else:
                metadata = TermMetadata.model_validate(parsed.frontmatter)
                relative = Path("knowledge") / "terms" / "{}.md".format(entity_id)
            if metadata.id != entity_id:
                raise ValueError("Draft entity_id must match canonical frontmatter id")
            return self.repository_root / relative, metadata

        if draft.entity_type == "source":
            value = parse_yaml(content)
            metadata = SourceMetadata.model_validate(value)
            if metadata.id != entity_id:
                raise ValueError("Draft entity_id must match Source id")
            relative = Path("knowledge") / "sources" / "{}.yaml".format(entity_id)
            return self.repository_root / relative, metadata

        if draft.entity_type == "taxonomy":
            registry_name_to_kind = {
                "domains": "domain",
                "topics": "topic",
                "tags": "tag",
            }
            if entity_id not in registry_name_to_kind:
                raise ValueError("Taxonomy Draft entity_id must be domains, topics, or tags")
            value = parse_yaml(content)
            metadata = TaxonomyRegistryModel.model_validate(value)
            relative = Path("knowledge") / "taxonomy" / "{}.yaml".format(entity_id)
            return self.repository_root / relative, metadata

        if draft.entity_type == "collection":
            metadata = Collection.model_validate(parse_yaml(content))
            if metadata.id != entity_id:
                raise ValueError("Draft entity_id must match Collection id")
            relative = Path("knowledge") / "collections" / "{}.yaml".format(entity_id)
            return self.repository_root / relative, metadata

        raise ValueError("Unsupported Draft entity type: {}".format(draft.entity_type))

    def _validate_candidate(
        self,
        draft: Draft,
        content: str,
        path: Path,
        metadata,
        allow_style_warnings: bool = False,
        validate_references: bool = True,
    ) -> list[str]:
        self._ensure_entity_path(draft, path)
        if draft.entity_type == "source":
            self._validate_source_attachment(metadata)
            return []

        if draft.entity_type == "collection":
            return []

        if draft.entity_type == "taxonomy":
            kind = {"domains": "domain", "topics": "topic", "tags": "tag"}[draft.entity_id]
            existing = TaxonomyRegistry.load(self.knowledge_root / "taxonomy")
            replacement = self._load_taxonomy_override(draft, content, metadata)
            old_ids = {entry.id for entry in existing.entries(kind)}
            new_ids = {entry.id for entry in replacement.entries(kind)}
            removed_ids = old_ids - new_ids
            if removed_ids:
                references = find_taxonomy_references(
                    self.repository_root, kind, removed_ids
                )
                if references:
                    raise PublishValidationError(
                        "; ".join("{}: {}".format(issue.path, issue.message) for issue in references)
                    )
            return []

        issues = lint_markdown(
            content,
            entity_type=draft.entity_type,
            standard=self.standard,
            maintenance_status=(metadata.maintenance.status if metadata.maintenance else None),
        )
        errors = [
            issue
            for issue in issues
            if issue.severity == "ERROR"
            and not (
                allow_style_warnings
                and issue.code.startswith(("heading.", "mermaid."))
            )
        ]
        if errors:
            raise PublishValidationError(
                "Markdown validation failed: "
                + "; ".join("{}: {}".format(issue.code, issue.message) for issue in errors)
            )

        warnings = [
            "{}:{}: {}".format(issue.code, issue.line, issue.message)
            for issue in issues
            if issue.severity == "WARN"
            or (
                allow_style_warnings
                and issue.code.startswith(("heading.", "mermaid."))
            )
        ]
        if not validate_references:
            return warnings

        terms = self._load_terms_override(draft, content, path, metadata)
        sources = self._load_sources_override(draft, content, path, metadata)
        taxonomy = self._load_taxonomy_override(draft, content, metadata)
        parsed = parse_markdown(content)
        references = validate_markdown_references(
            path,
            self.repository_root,
            metadata,
            parsed,
            taxonomy,
            sources,
            TermResolver(terms),
        )
        if references:
            raise PublishValidationError(
                "; ".join("{}: {}".format(issue.path, issue.message) for issue in references)
            )
        return warnings

    def _ensure_entity_path(self, draft: Draft, target_path: Path) -> None:
        if draft.entity_type == "document":
            search_roots = [self.knowledge_root / "documents"]
            suffix = ".md"
        elif draft.entity_type == "term":
            search_roots = [self.knowledge_root / "terms"]
            suffix = ".md"
        elif draft.entity_type == "source":
            search_roots = [self.knowledge_root / "sources"]
            suffix = ".yaml"
        else:
            return
        for root in search_roots:
            if not root.exists():
                continue
            for existing in root.rglob("*{}".format(suffix)):
                if existing.resolve() == target_path.resolve():
                    continue
                try:
                    text = existing.read_text(encoding="utf-8")
                    if draft.entity_type == "document" or draft.entity_type == "term":
                        parsed = parse_markdown(text)
                        current_id = (parsed.frontmatter or {}).get("id")
                    else:
                        current_id = (parse_yaml(text) or {}).get("id")
                except Exception:
                    continue
                if current_id == draft.entity_id:
                    raise PublishValidationError(
                        "Entity already exists at a different canonical path: {}".format(
                            existing.relative_to(self.repository_root).as_posix()
                        )
                    )

    def _validate_source_attachment(self, metadata: SourceMetadata) -> None:
        attachment = metadata.attachments.local_pdf
        if attachment is None:
            return
        match = re.fullmatch(
            r"storage://papers/([a-z0-9]+(?:-[a-z0-9]+)*)\.pdf", attachment
        )
        if match is None:
            raise PublishValidationError(
                "Source PDF attachments must use storage://papers/<source-id>.pdf"
            )
        if match.group(1) != metadata.id:
            raise PublishValidationError(
                "Source PDF attachment ID must match the Source ID"
            )
        storage_root = self.repository_root / "storage"
        papers_root = storage_root / "papers"
        for directory in (storage_root, papers_root):
            if directory.is_symlink():
                raise PublishValidationError("Source PDF storage paths cannot be symbolic links")
            try:
                directory.resolve().relative_to(self.repository_root)
            except ValueError as error:
                raise PublishValidationError(
                    "Source PDF storage must remain inside the repository"
                ) from error
        path = papers_root / "{}.pdf".format(match.group(1))
        if path.is_symlink() or not path.is_file():
            raise PublishValidationError("Source PDF attachment is missing from storage/papers")
        with path.open("rb") as attachment_file:
            is_pdf = attachment_file.read(5) == b"%PDF-"
        if not is_pdf:
            raise PublishValidationError("Source PDF attachment has an invalid PDF header")

    def _load_terms_override(self, draft: Draft, content: str, path: Path, metadata) -> TermRegistry:
        terms: Dict[str, TermMetadata] = {}
        directory = self.knowledge_root / "terms"
        if directory.exists():
            for existing in directory.glob("*.md"):
                if existing.resolve() == path.resolve():
                    continue
                parsed = parse_markdown(existing.read_text(encoding="utf-8"))
                if parsed.frontmatter is None:
                    raise PublishValidationError("Term file has invalid frontmatter: {}".format(existing.name))
                term = TermMetadata.model_validate(parsed.frontmatter)
                if existing.stem != term.id or term.id in terms:
                    raise PublishValidationError("Term registry contains a duplicate or mismatched id")
                terms[term.id] = term
        if draft.entity_type == "term":
            terms[metadata.id] = metadata
        term_values = tuple(terms[key] for key in sorted(terms))
        return TermRegistry(term_values, AliasIndex.from_terms(term_values))

    def _load_sources_override(self, draft: Draft, content: str, path: Path, metadata) -> SourceRegistry:
        sources: Dict[str, SourceMetadata] = {}
        directory = self.knowledge_root / "sources"
        if directory.exists():
            for existing in directory.glob("*.yaml"):
                if existing.resolve() == path.resolve():
                    continue
                source = SourceMetadata.model_validate(parse_yaml(existing.read_text(encoding="utf-8")))
                if existing.stem != source.id or source.id in sources:
                    raise PublishValidationError("Source registry contains a duplicate or mismatched id")
                sources[source.id] = source
        if draft.entity_type == "source":
            sources[metadata.id] = metadata
        return SourceRegistry(tuple(sources[key] for key in sorted(sources)))

    def _load_taxonomy_override(self, draft: Draft, content: str, metadata) -> TaxonomyRegistry:
        name_kind = {"domains": "domain", "topics": "topic", "tags": "tag"}
        records: List[TaxonomyRecord] = []
        for name, kind in name_kind.items():
            if draft.entity_type == "taxonomy" and draft.entity_id == name:
                value = metadata
            else:
                file_path = self.knowledge_root / "taxonomy" / "{}.yaml".format(name)
                if not file_path.is_file():
                    raise PublishValidationError("Missing taxonomy registry: {}".format(file_path.name))
                value = TaxonomyRegistryModel.model_validate(
                    parse_yaml(file_path.read_text(encoding="utf-8"))
                )
            records.extend(TaxonomyRecord(kind, entry) for entry in value.entries)
        all_ids = [(record.kind, record.entry.id) for record in records]
        if len(all_ids) != len(set(all_ids)):
            raise PublishValidationError("Taxonomy registry contains duplicate IDs")
        return TaxonomyRegistry(tuple(records))

    def _default_commit_message(self, draft: Draft, was_existing: bool = False) -> str:
        if draft.entity_type == "document":
            return "docs({}): publish knowledge update".format(draft.entity_id)
        if draft.entity_type == "term":
            verb = "update term" if was_existing else "add term"
            return "kb({}): {}".format(draft.entity_id, verb)
        if draft.entity_type == "source":
            return "kb({}): publish source update".format(draft.entity_id)
        if draft.entity_type == "collection":
            return "kb(collection): update {}".format(draft.entity_id)
        return "kb(taxonomy): update {}".format(draft.entity_id)

    def _default_batch_commit_message(self, prepared) -> str:
        if len(prepared) == 1:
            item = prepared[0]
            return self._default_commit_message(
                item["draft"], was_existing=item["previous"] is not None
            )
        return "kb: publish {} canonical updates".format(len(prepared))

    def _restore_prepared_files(self, prepared) -> list[str]:
        errors = []
        for item in reversed(prepared):
            path = item["path"]
            previous = item["previous"]
            try:
                if previous is None:
                    if path.exists():
                        if not path.is_file():
                            raise PublishError("Canonical target became a non-file")
                        path.unlink()
                else:
                    _atomic_write(path, previous)
            except Exception as error:
                errors.append("{}: {}".format(path, error))
        return errors


def _require_slug(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError("{} must be a lowercase canonical slug".format(field))
    return value
