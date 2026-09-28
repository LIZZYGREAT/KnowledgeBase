"""Resolve references against one canonical Taxonomy registry."""

from backend.app.services.resolution import Resolution, resolve_entry
from backend.app.services.taxonomy_registry import TaxonomyKind, TaxonomyRegistry


class TaxonomyResolver:
    def __init__(self, registry: TaxonomyRegistry):
        self.registry = registry

    def resolve(self, query: str, kind: TaxonomyKind) -> Resolution:
        return resolve_entry(query, self.registry.entries(kind))
