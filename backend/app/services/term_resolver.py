"""Resolve Term IDs, titles, aliases, and fuzzy candidates."""

from backend.app.services.resolution import Resolution, resolve_entry
from backend.app.services.term_registry import TermRegistry


class TermResolver:
    def __init__(self, registry: TermRegistry):
        self.registry = registry

    def resolve(self, query: str) -> Resolution:
        return resolve_entry(
            query,
            self.registry.entries,
            normalized_aliases=self.registry.alias_index.by_normalized_alias,
        )
