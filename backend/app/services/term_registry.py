"""Load the canonical Term files and build a deterministic alias index."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.app.domain.term import TermMetadata
from .markdown_parser import parse_markdown
from .resolution import RegistryEntry, normalize_key


@dataclass(frozen=True)
class AliasIndex:
    by_normalized_alias: dict[str, tuple[str, ...]]

    @classmethod
    def from_terms(cls, terms: tuple[TermMetadata, ...]) -> "AliasIndex":
        values: dict[str, set[str]] = {}
        for term in terms:
            for alias in term.aliases:
                key = normalize_key(alias)
                if key:
                    values.setdefault(key, set()).add(term.id)
        return cls({key: tuple(sorted(ids)) for key, ids in sorted(values.items())})

    def resolve(self, alias: str) -> tuple[str, ...]:
        return self.by_normalized_alias.get(normalize_key(alias), ())


@dataclass(frozen=True)
class TermRegistry:
    terms: tuple[TermMetadata, ...]
    alias_index: AliasIndex

    @classmethod
    def load(cls, directory: Path) -> "TermRegistry":
        terms = []
        identifiers = set()
        for path in sorted(Path(directory).glob("*.md")):
            parsed = parse_markdown(path.read_text(encoding="utf-8"))
            if parsed.frontmatter is None:
                raise ValueError("Term file has no valid frontmatter: {}".format(path))
            term = TermMetadata.model_validate(parsed.frontmatter)
            if path.stem != term.id:
                raise ValueError(
                    "Term filename '{}' does not match canonical id '{}'".format(path.name, term.id)
                )
            if term.id in identifiers:
                raise ValueError("Duplicate Term id '{}' in {}".format(term.id, directory))
            identifiers.add(term.id)
            terms.append(term)
        term_tuple = tuple(terms)
        return cls(term_tuple, AliasIndex.from_terms(term_tuple))

    @property
    def entries(self) -> tuple[RegistryEntry, ...]:
        return tuple(
            RegistryEntry(term.id, term.title, tuple(term.aliases))
            for term in self.terms
        )

    def get(self, term_id: str) -> Optional[TermMetadata]:
        return next((term for term in self.terms if term.id == term_id), None)
