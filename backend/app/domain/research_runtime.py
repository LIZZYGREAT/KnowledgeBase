"""Runtime records created by Research discovery."""

from typing import Any, Literal, Optional

from pydantic import ConfigDict, StrictBool, StrictFloat, StrictInt

from backend.app.domain.common import CanonicalModel, NonEmptyText, Slug
from backend.app.domain.research import ResearchProvider as ResearchProviderName


class ResearchWorkRecord(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyText
    canonical_key: NonEmptyText
    title: NonEmptyText
    normalized_title: NonEmptyText
    abstract: Optional[NonEmptyText] = None
    authors: tuple[NonEmptyText, ...] = ()
    year: Optional[StrictInt] = None
    published_at: Optional[NonEmptyText] = None
    venue: Optional[NonEmptyText] = None
    doi: Optional[NonEmptyText] = None
    arxiv_id: Optional[NonEmptyText] = None
    openalex_id: Optional[NonEmptyText] = None
    semantic_scholar_id: Optional[NonEmptyText] = None
    url: Optional[NonEmptyText] = None
    created_at: NonEmptyText
    updated_at: NonEmptyText


class ResearchDiscoveryRecord(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyText
    work_id: NonEmptyText
    profile_id: Slug
    lens_id: Slug
    provider: Literal["arxiv", "openalex", "crossref"]
    provider_record_id: NonEmptyText
    query_key: NonEmptyText
    query_text: NonEmptyText
    metadata: dict[str, Any]
    discovered_at: NonEmptyText


class ResearchIngestResult(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    work: ResearchWorkRecord
    discovery: ResearchDiscoveryRecord
    created_work: bool
    created_discovery: bool
    match_method: Literal[
        "new",
        "doi",
        "arxiv_id",
        "openalex_id",
        "semantic_scholar_id",
        "title_author_year",
        "ambiguous_weak_match",
    ]


class ResearchSearchStateRecord(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: Slug
    lens_id: Slug
    provider: ResearchProviderName
    query_key: NonEmptyText
    query_text: NonEmptyText
    completed_through: Optional[NonEmptyText] = None
    last_attempt_at: Optional[NonEmptyText] = None
    last_success_at: Optional[NonEmptyText] = None
    created_at: NonEmptyText
    updated_at: NonEmptyText


class ResearchContextSection(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    heading: NonEmptyText
    excerpt: NonEmptyText


class ResearchContextCard(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_type: Literal["document", "term", "source", "collection"]
    entity_id: NonEmptyText
    title: NonEmptyText
    review_status: NonEmptyText
    topics: tuple[NonEmptyText, ...] = ()
    domains: tuple[NonEmptyText, ...] = ()
    relevant_sections: tuple[ResearchContextSection, ...] = ()
    metadata: dict[str, Any]
    pinned: StrictBool
    retrieval_score: StrictFloat


class ResearchContextPack(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    focus_query: NonEmptyText
    cards: tuple[ResearchContextCard, ...]
    budget: StrictInt
    omitted_count: StrictInt
