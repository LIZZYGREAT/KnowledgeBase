"""Runtime records created by Research discovery."""

from typing import Any, Literal, Optional

from pydantic import ConfigDict, StrictBool, StrictFloat, StrictInt, model_validator

from backend.app.domain.common import CanonicalModel, NonEmptyText, Slug
from backend.app.domain.ai import ResearchCandidateAnalysisOutput
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


class ResearchWorkAnalysisRecord(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyText
    work_id: NonEmptyText
    profile_id: Slug
    input_hash: NonEmptyText
    outcome: Literal["surface", "filtered"]
    analysis: ResearchCandidateAnalysisOutput
    provider: NonEmptyText
    model: NonEmptyText
    prompt_version: NonEmptyText
    analysis_version: StrictInt
    context_entity_ids: tuple[NonEmptyText, ...] = ()
    analyzed_at: NonEmptyText

    @model_validator(mode="after")
    def outcome_matches_analysis(self):
        expected = "surface" if self.analysis.relevant else "filtered"
        if self.outcome != expected:
            raise ValueError("Research Analysis outcome must match its relevance decision")
        return self


ResearchCandidateStatus = Literal[
    "new", "shortlisted", "dismissed", "saved_source", "note_created"
]
ResearchDismissReason = Literal[
    "not_relevant", "already_known", "too_similar", "not_following_subfield", "other"
]


class ResearchCandidateRecord(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyText
    work_id: NonEmptyText
    profile_id: Slug
    status: ResearchCandidateStatus
    primary_lens_id: Optional[Slug] = None
    analysis_id: NonEmptyText
    user_note: Optional[NonEmptyText] = None
    dismiss_reason: Optional[ResearchDismissReason] = None
    created_at: NonEmptyText
    updated_at: NonEmptyText
    first_viewed_at: Optional[NonEmptyText] = None
    last_viewed_at: Optional[NonEmptyText] = None
    decided_at: Optional[NonEmptyText] = None


ResearchRunStatus = Literal[
    "running",
    "success",
    "partial",
    "failed",
    "interrupted",
    "skipped_paused",
    "skipped_disabled",
    "skipped_ai_disabled",
    "skipped_inbox_full",
    "capacity_reached",
]

ResearchRunRequestStatus = Literal["pending", "claimed", "completed", "failed"]


class ResearchRunRequestRecord(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyText
    profile_id: Slug
    trigger: Literal["manual"] = "manual"
    override: dict[str, Any]
    status: ResearchRunRequestStatus
    created_at: NonEmptyText
    claimed_at: Optional[NonEmptyText] = None
    completed_at: Optional[NonEmptyText] = None


class ResearchRunRecord(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyText
    profile_id: Slug
    request_id: Optional[NonEmptyText] = None
    trigger: Literal["scheduled", "manual"]
    status: ResearchRunStatus
    profile_content_hash: NonEmptyText
    effective_config: dict[str, Any]
    fetched_count: StrictInt = 0
    new_work_count: StrictInt = 0
    duplicate_count: StrictInt = 0
    deterministic_filtered_count: StrictInt = 0
    analyzed_count: StrictInt = 0
    surfaced_count: StrictInt = 0
    provider_summary: dict[str, Any]
    error_summary: Optional[NonEmptyText] = None
    started_at: NonEmptyText
    finished_at: Optional[NonEmptyText] = None


class ResearchProfileStateRecord(CanonicalModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: Slug
    paused_until: Optional[NonEmptyText] = None
    last_successful_scheduled_run_at: Optional[NonEmptyText] = None
    created_at: NonEmptyText
    updated_at: NonEmptyText


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
