"""Validate Drafts and publish canonical files through Git."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union
import re

import yaml
from pydantic import ValidationError

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


class PostPublishProposalUpdateError(PublishError):
    def __init__(self, commit_revision: str, cause: Exception):
        self.commit_revision = commit_revision
        super().__init__(
            "Canonical content was committed as {}, but Proposal status update failed: {}".format(
                commit_revision, cause
            )
        )


class PostPublishIndexUpdateError(PublishError):
    def __init__(self, commit_revision: str, cause: Exception):
        self.commit_revision = commit_revision
        super().__init__(
            "Canonical content was committed as {}, but incremental indexing failed: {}".format(
                commit_revision, cause
            )
        )


@dataclass(frozen=True)
class PublishedResult:
    draft_id: str
    entity_type: str
    entity_id: str
    path: str
    commit_revision: str
    proposal_id: Optional[str] = None


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
    ) -> PublishedResult:
        draft = self.draft_service.get(draft_id)
        current_revision = self.git.current_revision()
        content = draft.content
        proposal = None

        if proposal_id is not None:
            if self.proposal_service is None:
                raise PublishError("ProposalService is required to apply a Proposal")
            proposal = self.proposal_service.assert_applicable(
                proposal_id, current_revision
            )
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
            self.git.assert_base(
                draft.base_git_revision, draft.base_content_hash, path
            )
        except (GitConflictError, ValueError) as error:
            raise PublishConflictError(str(error)) from error

        self._validate_candidate(draft, content, path, metadata)
        previous = path.read_bytes() if path.is_file() else None
        new_content = content.encode("utf-8")
        if previous == new_content:
            raise PublishError("Draft has no canonical changes to publish")

        _atomic_write(path, new_content)
        try:
            message = commit_message or self._default_commit_message(
                draft, was_existing=previous is not None
            )
            commit_revision = self.git.commit(path, message)
        except Exception:
            if previous is None:
                if path.exists() and path.is_file():
                    path.unlink()
            else:
                _atomic_write(path, previous)
            raise

        proposal_error = None
        if proposal is not None:
            try:
                self.proposal_service.merge(proposal.id, current_revision)
            except Exception as error:
                proposal_error = error

        index_error = None
        try:
            self.indexer.update_path(path)
        except Exception as error:
            index_error = error

        if proposal_error is not None:
            raise PostPublishProposalUpdateError(commit_revision, proposal_error) from proposal_error
        if index_error is not None:
            raise PostPublishIndexUpdateError(commit_revision, index_error) from index_error

        return PublishedResult(
            draft_id=draft.id,
            entity_type=draft.entity_type,
            entity_id=draft.entity_id,
            path=path.relative_to(self.repository_root).as_posix(),
            commit_revision=commit_revision,
            proposal_id=proposal.id if proposal else None,
        )

    def restore(
        self,
        path: Union[str, Path],
        revision: str,
        commit_message: Optional[str] = None,
    ) -> str:
        """Restore a canonical file by creating a new commit through GitManager."""
        commit_revision = self.git.restore(path, revision, commit_message)
        try:
            self.indexer.update_path(path)
        except Exception as error:
            raise PostPublishIndexUpdateError(commit_revision, error) from error
        return commit_revision

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

        raise ValueError("Unsupported Draft entity type: {}".format(draft.entity_type))

    def _validate_candidate(self, draft: Draft, content: str, path: Path, metadata) -> None:
        if draft.entity_type in {"document", "term"}:
            issues = lint_markdown(content, entity_type=draft.entity_type, standard=self.standard)
            if issues:
                raise PublishValidationError(
                    "Markdown validation failed: "
                    + "; ".join("{}: {}".format(issue.code, issue.message) for issue in issues)
                )

        self._ensure_entity_path(draft, path)
        terms = self._load_terms_override(draft, content, path, metadata)
        sources = self._load_sources_override(draft, content, path, metadata)
        taxonomy = self._load_taxonomy_override(draft, content, metadata)
        markdown_entities = self._load_markdown_entities(draft, content, path, metadata)
        term_resolver = TermResolver(terms)
        source_ids = {source.id for source in sources.sources}
        taxonomy_ids = {
            kind: {entry.id for entry in taxonomy.entries(kind)}
            for kind in ("domain", "topic", "tag")
        }

        for entity_path, entity_type, entity_metadata, parsed in markdown_entities:
            for field, kind in (
                ("domains", "domain"),
                ("topics", "topic"),
                ("tags", "tag"),
            ):
                unknown = sorted(set(getattr(entity_metadata, field)) - taxonomy_ids[kind])
                if unknown:
                    raise PublishValidationError(
                        "{} references unknown {} id(s): {}".format(
                            entity_path.relative_to(self.repository_root).as_posix(),
                            kind,
                            ", ".join(unknown),
                        )
                    )
            unknown_sources = sorted(set(entity_metadata.sources) - source_ids)
            if unknown_sources:
                raise PublishValidationError(
                    "{} references unknown Source id(s): {}".format(
                        entity_path.relative_to(self.repository_root).as_posix(),
                        ", ".join(unknown_sources),
                    )
                )

            for link in parsed.wiki_links:
                resolution = term_resolver.resolve(link.target)
                if resolution.status == "ambiguous":
                    choices = ", ".join(candidate.id for candidate in resolution.candidates)
                    raise PublishValidationError(
                        "Ambiguous wiki link '{}' in {} (candidates: {})".format(
                            link.target,
                            entity_path.relative_to(self.repository_root).as_posix(),
                            choices,
                        )
                    )
            for citation in parsed.citations:
                if citation.source_id not in source_ids:
                    raise PublishValidationError(
                        "Unknown Source citation '{}' in {}".format(
                            citation.source_id,
                            entity_path.relative_to(self.repository_root).as_posix(),
                        )
                    )

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

    def _load_markdown_entities(self, draft: Draft, content: str, path: Path, metadata):
        entities = []
        roots = (self.knowledge_root / "documents", self.knowledge_root / "terms")
        for root in roots:
            if not root.exists():
                continue
            for existing in sorted(root.rglob("*.md")):
                if existing.resolve() == path.resolve():
                    continue
                parsed = parse_markdown(existing.read_text(encoding="utf-8"))
                if parsed.frontmatter is None:
                    raise PublishValidationError("Canonical Markdown has invalid frontmatter: {}".format(existing))
                entity_type = "document" if root.name == "documents" else "term"
                model = DocumentMetadata if entity_type == "document" else TermMetadata
                entity_metadata = model.model_validate(parsed.frontmatter)
                entities.append((existing, entity_type, entity_metadata, parsed))

        if draft.entity_type in {"document", "term"}:
            parsed = parse_markdown(content)
            entities.append((path, draft.entity_type, metadata, parsed))
        return entities

    def _default_commit_message(self, draft: Draft, was_existing: bool = False) -> str:
        if draft.entity_type == "document":
            return "docs({}): publish knowledge update".format(draft.entity_id)
        if draft.entity_type == "term":
            verb = "update term" if was_existing else "add term"
            return "kb({}): {}".format(draft.entity_id, verb)
        if draft.entity_type == "source":
            return "kb({}): publish source update".format(draft.entity_id)
        return "kb(taxonomy): update {}".format(draft.entity_id)


def _require_slug(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError("{} must be a lowercase canonical slug".format(field))
    return value
