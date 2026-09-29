from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, constr


Slug = constr(strict=True, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NonEmptyText = constr(strict=True, strip_whitespace=True, min_length=1)


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AIReview(CanonicalModel):
    status: Literal["not_run", "passed", "needs_attention", "failed"]
    provider: Optional[NonEmptyText] = None
    model: Optional[NonEmptyText] = None
    reviewed_at: Optional[NonEmptyText] = None


class HumanReview(CanonicalModel):
    status: Literal["unreviewed", "approved", "rejected"]


class ReviewMetadata(CanonicalModel):
    ai: Optional[AIReview] = None
    human: Optional[HumanReview] = None


class Maintenance(CanonicalModel):
    status: Literal["current", "needs_revision", "legacy"]


class Provenance(CanonicalModel):
    origin: Literal["imported", "human-authored"]
    ai_assisted: bool


class ExternalArtifact(CanonicalModel):
    type: Literal["paperskill"]
    variant: Literal["canonical", "enhanced"]
    url: NonEmptyText


class CanonicalEntity(CanonicalModel):
    schema_version: Literal[1]
    id: Slug
    title: NonEmptyText
    domains: list[Slug] = Field(default_factory=list)
    topics: list[Slug] = Field(default_factory=list)
    tags: list[Slug] = Field(default_factory=list)
    sources: list[Slug] = Field(default_factory=list)
    review: Optional[ReviewMetadata] = None
    maintenance: Optional[Maintenance] = None
    provenance: Optional[Provenance] = None
