from typing import Literal, Optional

from pydantic import AnyHttpUrl, Field, conint, constr

from .common import CanonicalModel, NonEmptyText, Slug


class SourceIdentifiers(CanonicalModel):
    doi: Optional[NonEmptyText] = None
    arxiv_id: Optional[NonEmptyText] = None
    openalex_id: Optional[NonEmptyText] = None


class SourceAttachments(CanonicalModel):
    local_pdf: Optional[constr(strict=True, pattern=r"^storage://[A-Za-z0-9_./-]+$")] = None


class SourceMetadataReview(CanonicalModel):
    status: NonEmptyText


class SourceMetadata(CanonicalModel):
    schema_version: Literal[1]
    id: Slug
    type: Literal["paper", "book", "course", "web", "personal"]
    title: NonEmptyText
    authors: list[NonEmptyText] = Field(default_factory=list)
    year: Optional[conint(strict=True, ge=1000, le=9999)] = None
    identifiers: SourceIdentifiers = Field(default_factory=SourceIdentifiers)
    url: Optional[AnyHttpUrl] = None
    zotero_key: Optional[NonEmptyText] = None
    attachments: SourceAttachments = Field(default_factory=SourceAttachments)
    metadata_review: Optional[SourceMetadataReview] = None
