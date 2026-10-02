"""Load the canonical Collection YAML files."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.app.domain.collection import Collection
from .markdown_parser import parse_yaml


@dataclass(frozen=True)
class CollectionRegistry:
    collections: tuple[Collection, ...]

    @classmethod
    def load(cls, directory: Path) -> "CollectionRegistry":
        directory = Path(directory)
        collections = []
        identifiers = set()
        if not directory.exists():
            return cls(())

        for path in sorted(directory.glob("*.yaml")):
            collection = Collection.model_validate(
                parse_yaml(path.read_text(encoding="utf-8"))
            )
            if path.stem != collection.id:
                raise ValueError(
                    "Collection filename '{}' does not match canonical id '{}'".format(
                        path.name, collection.id
                    )
                )
            if collection.id in identifiers:
                raise ValueError(
                    "Duplicate Collection id '{}' in {}".format(collection.id, directory)
                )
            identifiers.add(collection.id)
            collections.append(collection)
        return cls(tuple(collections))

    def get(self, collection_id: str) -> Optional[Collection]:
        return next(
            (collection for collection in self.collections if collection.id == collection_id),
            None,
        )
