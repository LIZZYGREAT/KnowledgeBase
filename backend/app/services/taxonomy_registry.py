"""Load the canonical Domain, Topic, and Tag registries."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from backend.app.domain.taxonomy import TaxonomyEntry, TaxonomyRegistry as TaxonomyRegistryModel
from .markdown_parser import parse_yaml
from .resolution import RegistryEntry


TaxonomyKind = Literal["domain", "topic", "tag"]

_REGISTRY_FILES: tuple[tuple[TaxonomyKind, str], ...] = (
    ("domain", "domains.yaml"),
    ("topic", "topics.yaml"),
    ("tag", "tags.yaml"),
)


@dataclass(frozen=True)
class TaxonomyRecord:
    kind: TaxonomyKind
    entry: TaxonomyEntry


@dataclass(frozen=True)
class TaxonomyRegistry:
    records: tuple[TaxonomyRecord, ...]

    @classmethod
    def load(cls, directory: Path) -> "TaxonomyRegistry":
        records = []
        for kind, filename in _REGISTRY_FILES:
            path = Path(directory) / filename
            if not path.is_file():
                raise FileNotFoundError("Missing taxonomy registry: {}".format(path))
            value = parse_yaml(path.read_text(encoding="utf-8"))
            registry = TaxonomyRegistryModel.model_validate(value)
            records.extend(TaxonomyRecord(kind, entry) for entry in registry.entries)
        return cls(tuple(records))

    def entries(self, kind: TaxonomyKind) -> tuple[RegistryEntry, ...]:
        if kind not in {"domain", "topic", "tag"}:
            raise ValueError("Unknown taxonomy kind: {}".format(kind))
        return tuple(
            RegistryEntry(record.entry.id, record.entry.title)
            for record in self.records
            if record.kind == kind
        )

    def get(self, kind: TaxonomyKind, entry_id: str) -> Optional[TaxonomyEntry]:
        return next(
            (
                record.entry
                for record in self.records
                if record.kind == kind and record.entry.id == entry_id
            ),
            None,
        )
