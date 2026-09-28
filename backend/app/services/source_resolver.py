"""Resolve Source IDs, titles, external identifiers, and fuzzy candidates."""

from backend.app.services.resolution import Resolution, resolve_entry
from backend.app.services.source_registry import SourceRegistry


class SourceResolver:
    def __init__(self, registry: SourceRegistry):
        self.registry = registry

    def resolve(self, query: str) -> Resolution:
        return resolve_entry(query, self.registry.entries)
