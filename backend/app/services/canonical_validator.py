"""Reference checks shared by Publish and the repository-wide ``kb check``."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
import yaml

from backend.app.domain.document import DocumentMetadata
from backend.app.domain.term import TermMetadata
from backend.app.services.markdown_parser import MarkdownDocument, parse_markdown
from backend.app.services.source_registry import SourceRegistry
from backend.app.services.taxonomy_registry import TaxonomyKind, TaxonomyRegistry
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver


@dataclass(frozen=True)
class CanonicalReferenceIssue:
    path: str
    code: str
    message: str
    line: int = 1


def validate_markdown_references(
    path: Path,
    repository_root: Path,
    metadata,
    parsed: MarkdownDocument,
    taxonomy: TaxonomyRegistry,
    sources: SourceRegistry,
    term_resolver: TermResolver,
) -> list[CanonicalReferenceIssue]:
    relative_path = Path(path).resolve().relative_to(Path(repository_root).resolve()).as_posix()
    issues = []
    taxonomy_ids = {
        kind: {entry.id for entry in taxonomy.entries(kind)}
        for kind in ("domain", "topic", "tag")
    }
    for field, kind in (("domains", "domain"), ("topics", "topic"), ("tags", "tag")):
        unknown = sorted(set(getattr(metadata, field)) - taxonomy_ids[kind])
        if unknown:
            issues.append(
                CanonicalReferenceIssue(
                    relative_path,
                    "reference.taxonomy.{}".format(kind),
                    "Unknown {} id(s): {}".format(kind, ", ".join(unknown)),
                )
            )

    source_ids = {source.id for source in sources.sources}
    unknown_sources = sorted(set(metadata.sources) - source_ids)
    if unknown_sources:
        issues.append(
            CanonicalReferenceIssue(
                relative_path,
                "reference.source",
                "Unknown Source id(s): {}".format(", ".join(unknown_sources)),
            )
        )

    for link in parsed.wiki_links:
        resolution = term_resolver.resolve(link.target)
        if resolution.status == "ambiguous":
            choices = ", ".join(candidate.id for candidate in resolution.candidates)
            issues.append(
                CanonicalReferenceIssue(
                    relative_path,
                    "reference.wiki.ambiguous",
                    "Ambiguous wiki link '{}' (candidates: {})".format(link.target, choices),
                    link.line,
                )
            )

    for citation in parsed.citations:
        if citation.source_id not in source_ids:
            issues.append(
                CanonicalReferenceIssue(
                    relative_path,
                    "reference.citation.source",
                    "Unknown Source citation '{}'".format(citation.source_id),
                    citation.line,
                )
            )
    return issues


def validate_repository_references(repository_root: Path) -> list[CanonicalReferenceIssue]:
    """Check cross-file IDs and ambiguous links across canonical Markdown."""
    repository_root = Path(repository_root).resolve()
    knowledge_root = repository_root / "knowledge"
    try:
        taxonomy = TaxonomyRegistry.load(knowledge_root / "taxonomy")
        sources = SourceRegistry.load(knowledge_root / "sources")
        terms = TermRegistry.load(knowledge_root / "terms")
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
        return [
            CanonicalReferenceIssue(
                "knowledge", "reference.registry", "Cannot load canonical registries: {}".format(error)
            )
        ]

    term_resolver = TermResolver(terms)
    issues = []
    for entity_type, root, model in (
        ("document", knowledge_root / "documents", DocumentMetadata),
        ("term", knowledge_root / "terms", TermMetadata),
    ):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                parsed = parse_markdown(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            if parsed.frontmatter is None:
                continue
            try:
                metadata = model.model_validate(parsed.frontmatter)
            except ValidationError:
                continue
            issues.extend(
                validate_markdown_references(
                    path, repository_root, metadata, parsed, taxonomy, sources, term_resolver
                )
            )
    return issues


def find_taxonomy_references(
    repository_root: Path, kind: TaxonomyKind, removed_ids: set[str]
) -> list[CanonicalReferenceIssue]:
    """Return references that would dangle if taxonomy IDs were removed."""
    fields = {"domain": "domains", "topic": "topics", "tag": "tags"}
    field = fields[kind]
    repository_root = Path(repository_root).resolve()
    issues = []
    for root in (
        repository_root / "knowledge" / "documents",
        repository_root / "knowledge" / "terms",
    ):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                parsed = parse_markdown(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            if parsed.frontmatter is None:
                continue
            values = parsed.frontmatter.get(field, [])
            if not isinstance(values, list):
                continue
            referenced = sorted(
                {value for value in values if isinstance(value, str)} & removed_ids
            )
            if referenced:
                issues.append(
                    CanonicalReferenceIssue(
                        path.relative_to(repository_root).as_posix(),
                        "reference.taxonomy.{}".format(kind),
                        "References removed {} id(s): {}".format(kind, ", ".join(referenced)),
                    )
                )
    return issues


def find_source_references(
    repository_root: Path, removed_ids: set[str]
) -> list[CanonicalReferenceIssue]:
    """Return canonical Markdown references that would dangle if Sources were removed."""
    repository_root = Path(repository_root).resolve()
    issues = []
    for root in (
        repository_root / "knowledge" / "documents",
        repository_root / "knowledge" / "terms",
    ):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                parsed = parse_markdown(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            metadata = parsed.frontmatter or {}
            metadata_references = metadata.get("sources", [])
            if not isinstance(metadata_references, list):
                metadata_references = []
            referenced = {
                value
                for value in metadata_references
                if isinstance(value, str) and value in removed_ids
            }
            referenced.update(
                citation.source_id
                for citation in parsed.citations
                if citation.source_id in removed_ids
            )
            if referenced:
                issues.append(
                    CanonicalReferenceIssue(
                        path.relative_to(repository_root).as_posix(),
                        "reference.source",
                        "References removed Source id(s): {}".format(
                            ", ".join(sorted(referenced))
                        ),
                    )
                )
    return issues
