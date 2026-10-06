"""Resolve and validate the one canonical path for each knowledge entity."""

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from typing import Union

from backend.app.domain.collection import Collection
from backend.app.domain.document import DocumentMetadata
from backend.app.domain.research import ResearchProfile
from backend.app.domain.source import SourceMetadata
from backend.app.domain.taxonomy import TaxonomyRegistry as TaxonomyRegistryModel
from backend.app.domain.term import TermMetadata
from backend.app.services.markdown_parser import parse_markdown, parse_yaml


@dataclass(frozen=True)
class CanonicalTarget:
    path: Path
    metadata: object


class CanonicalTargetResolver:
    """Own canonical metadata validation and entity-to-path resolution."""

    _SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
    _DOCUMENT_FOLDERS = {
        "paper-note": "papers",
        "learning-note": "learning",
        "course-note": "courses",
    }
    _TAXONOMY_FILES = {
        "domains": "domains.yaml",
        "topics": "topics.yaml",
        "tags": "tags.yaml",
    }

    def __init__(self, repository_root: Union[Path, str], connection: sqlite3.Connection):
        self.repository_root = Path(repository_root).resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        self.connection = connection

    def resolve_target(
        self, entity_type: str, entity_id: str, content: str
    ) -> CanonicalTarget:
        if not isinstance(content, str):
            raise ValueError("Canonical content must be text")
        self._validate_entity_id(entity_type, entity_id)

        if entity_type in {"document", "term"}:
            parsed = parse_markdown(content)
            if parsed.frontmatter is None:
                raise ValueError("Canonical Markdown requires valid YAML frontmatter")
            metadata = (
                DocumentMetadata.model_validate(parsed.frontmatter)
                if entity_type == "document"
                else TermMetadata.model_validate(parsed.frontmatter)
            )
            if metadata.id != entity_id:
                raise ValueError("Draft entity_id must match canonical frontmatter id")
            path = self._markdown_target(entity_type, entity_id, metadata)
        elif entity_type == "source":
            metadata = SourceMetadata.model_validate(parse_yaml(content))
            if metadata.id != entity_id:
                raise ValueError("Draft entity_id must match Source id")
            path = self.knowledge_root / "sources" / "{}.yaml".format(entity_id)
        elif entity_type == "collection":
            metadata = Collection.model_validate(parse_yaml(content))
            if metadata.id != entity_id:
                raise ValueError("Draft entity_id must match Collection id")
            path = self.knowledge_root / "collections" / "{}.yaml".format(entity_id)
        elif entity_type == "taxonomy":
            if entity_id not in self._TAXONOMY_FILES:
                raise ValueError(
                    "Taxonomy Draft entity_id must be domains, topics, or tags"
                )
            metadata = TaxonomyRegistryModel.model_validate(parse_yaml(content))
            path = self.knowledge_root / "taxonomy" / self._TAXONOMY_FILES[entity_id]
        elif entity_type == "research_profile":
            metadata = ResearchProfile.model_validate(parse_yaml(content))
            if metadata.id != entity_id:
                raise ValueError("Draft entity_id must match Research Profile id")
            path = (
                self.repository_root
                / "config"
                / "research"
                / "profiles"
                / "{}.yaml".format(entity_id)
            )
        else:
            raise ValueError("Unsupported Draft entity type: {}".format(entity_type))

        path = self._canonical_path(path, entity_type)
        return CanonicalTarget(path=path, metadata=metadata)

    def resolve_existing_target_path(
        self, entity_type: str, entity_id: str
    ) -> Union[Path, None]:
        """Return the confined canonical path for an existing entity, if present."""
        self._validate_entity_id(entity_type, entity_id)
        if entity_type == "source":
            candidates = [self.knowledge_root / "sources" / "{}.yaml".format(entity_id)]
        elif entity_type == "collection":
            candidates = [
                self.knowledge_root / "collections" / "{}.yaml".format(entity_id)
            ]
        elif entity_type == "term":
            row = self.connection.execute(
                "SELECT path FROM term_index WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            candidates = []
            if row is not None:
                candidates.append(self._indexed_path(row["path"], "term", entity_id))
            candidates.append(self.knowledge_root / "terms" / "{}.md".format(entity_id))
        elif entity_type == "document":
            row = self.connection.execute(
                "SELECT path FROM document_index WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            candidates = []
            if row is not None:
                candidates.append(self._indexed_path(row["path"], "document", entity_id))
            candidates.extend(
                self.knowledge_root / "documents" / folder / "{}.md".format(entity_id)
                for folder in self._DOCUMENT_FOLDERS.values()
            )
        else:
            raise ValueError("Unsupported canonical entity type")

        existing = [
            self._canonical_path(candidate, entity_type)
            for candidate in candidates
            if candidate.is_file()
        ]
        unique = tuple(dict.fromkeys(existing))
        if len(unique) > 1:
            raise ValueError(
                "Multiple canonical targets exist for {} '{}'".format(
                    entity_type, entity_id
                )
            )
        return unique[0] if unique else None

    def _validate_entity_id(self, entity_type: str, entity_id: str) -> None:
        if entity_type == "taxonomy":
            if entity_id not in self._TAXONOMY_FILES:
                raise ValueError(
                    "Taxonomy Draft entity_id must be domains, topics, or tags"
                )
            return
        if not isinstance(entity_id, str) or self._SLUG.fullmatch(entity_id) is None:
            raise ValueError("entity_id must be a lowercase canonical slug")

    def _markdown_target(self, entity_type: str, entity_id: str, metadata) -> Path:
        if entity_type == "document":
            folder = self._DOCUMENT_FOLDERS[metadata.type]
            row = self.connection.execute(
                "SELECT path, document_type FROM document_index WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            if row is not None:
                if row["document_type"] != metadata.type:
                    raise ValueError("A Document Draft cannot change its canonical type")
                path = self._indexed_path(row["path"], "document", entity_id)
                if path.parent.name != folder:
                    raise ValueError(
                        "Indexed Document path does not match its canonical type"
                    )
                return path
            return self.knowledge_root / "documents" / folder / "{}.md".format(entity_id)

        row = self.connection.execute(
            "SELECT path FROM term_index WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if row is not None:
            return self._indexed_path(row["path"], "term", entity_id)
        return self.knowledge_root / "terms" / "{}.md".format(entity_id)

    def _indexed_path(self, indexed_path: str, entity_type: str, entity_id: str) -> Path:
        relative = Path(indexed_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Indexed canonical path is invalid")
        expected_parent = (
            Path("knowledge") / "documents"
            if entity_type == "document"
            else Path("knowledge") / "terms"
        )
        if (
            relative.suffix != ".md"
            or relative.stem != entity_id
            or relative.parts[: len(expected_parent.parts)] != expected_parent.parts
            or (entity_type == "term" and len(relative.parts) != 3)
            or (entity_type == "document" and len(relative.parts) != 4)
        ):
            raise ValueError("Indexed canonical path does not match its entity")
        return self._canonical_path(self.repository_root / relative, entity_type)

    def _canonical_path(self, path: Path, entity_type: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.repository_root / candidate
        try:
            relative = candidate.absolute().relative_to(self.repository_root)
        except ValueError as error:
            raise ValueError("Canonical target must remain inside the repository") from error
        if entity_type == "research_profile":
            if (
                len(relative.parts) != 4
                or relative.parts[:3] != ("config", "research", "profiles")
                or relative.suffix != ".yaml"
            ):
                raise ValueError(
                    "Research Profile target must be config/research/profiles/<id>.yaml"
                )
        elif len(relative.parts) < 3 or relative.parts[0] != "knowledge":
            raise ValueError("Canonical target must be under knowledge/")
        cursor = self.repository_root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Canonical entity paths cannot be symbolic links")
        target = cursor.resolve()
        try:
            target.relative_to(self.repository_root)
        except ValueError as error:
            raise ValueError("Canonical target must remain inside the repository") from error
        return target
