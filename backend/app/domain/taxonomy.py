from typing import Literal

from pydantic import Field, model_validator

from .common import CanonicalModel, NonEmptyText, Slug


class TaxonomyEntry(CanonicalModel):
    id: Slug
    title: NonEmptyText
    aliases: list[NonEmptyText] = Field(default_factory=list)


class TaxonomyRegistry(CanonicalModel):
    schema_version: Literal[1]
    entries: list[TaxonomyEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_ids(self):
        registry = self
        identifiers = [entry.id for entry in registry.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("taxonomy entry IDs must be unique")
        return registry
