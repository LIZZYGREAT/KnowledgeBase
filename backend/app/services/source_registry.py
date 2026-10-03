"""Load the canonical Source YAML files."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.app.domain.source import SourceMetadata
from .markdown_parser import parse_yaml
from .resolution import RegistryEntry


@dataclass(frozen=True)
class SourceRegistry:
    sources: tuple[SourceMetadata, ...]

    @classmethod
    def load(cls, directory: Path) -> "SourceRegistry":
        sources = []
        identifiers = set()
        for path in sorted(Path(directory).glob("*.yaml")):
            source = SourceMetadata.model_validate(parse_yaml(path.read_text(encoding="utf-8")))
            if path.stem != source.id:
                raise ValueError(
                    "Source filename '{}' does not match canonical id '{}'".format(path.name, source.id)
                )
            if source.id in identifiers:
                raise ValueError("Duplicate Source id '{}' in {}".format(source.id, directory))
            identifiers.add(source.id)
            sources.append(source)
        return cls(tuple(sources))

    @property
    def entries(self) -> tuple[RegistryEntry, ...]:
        entries = []
        for source in self.sources:
            identifiers = tuple(
                value
                for value in (
                    source.identifiers.doi,
                    source.identifiers.arxiv_id,
                    source.identifiers.openalex_id,
                    source.zotero_key,
                )
                if value
            )
            entries.append(RegistryEntry(source.id, source.title, identifiers=identifiers))
        return tuple(entries)

    def get(self, source_id: str) -> Optional[SourceMetadata]:
        return next((source for source in self.sources if source.id == source_id), None)
