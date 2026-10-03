"""Typed HTTP contracts for the Research Agent API."""

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from backend.app.api.schemas import APIModel
from backend.app.domain.ai import ResearchCandidateAnalysisOutput, ResearchRelation
from backend.app.domain.common import NonEmptyText, Slug
from backend.app.domain.research import ResearchProfile
from backend.app.domain.research_runtime import (
    ResearchCandidateRecord,
    ResearchDiscoveryRecord,
    ResearchProfileStateRecord,
    ResearchRunRecord,
    ResearchWorkAnalysisRecord,
    ResearchWorkRecord,
)


class ResearchInboxUsageView(APIModel):
    new_count: int = Field(ge=0)
    capacity: int = Field(ge=0)
    remaining: int = Field(ge=0)


class ResearchRunSummaryView(APIModel):
    id: str
    trigger: Literal["scheduled", "manual"]
    status: str
    started_at: str
    finished_at: Optional[str] = None
    fetched_count: int
    surfaced_count: int


class ResearchProfileSummaryView(APIModel):
    id: str
    title: str
    description: Optional[str] = None
    enabled: bool
    schedule_mode: Literal["daily", "weekly", "manual"]
    breadth: Literal["strict", "balanced", "explore"]
    lens_count: int
    enabled_lens_ids: list[str]
    paused_until: Optional[str] = None
    last_successful_scheduled_run_at: Optional[str] = None
    inbox: ResearchInboxUsageView
    latest_run: Optional[ResearchRunSummaryView] = None


class ResearchProfileDetailView(APIModel):
    profile: ResearchProfile
    canonical_content: str
    runtime_state: Optional[ResearchProfileStateRecord] = None
    inbox: ResearchInboxUsageView
    latest_run: Optional[ResearchRunSummaryView] = None
    resume_options: list[Literal["catch_up", "from_now"]]


class ResearchReactivationReviewRequest(APIModel):
    draft_id: NonEmptyText


class ResearchReactivationReviewView(APIModel):
    required: bool
    triggers: list[str] = Field(default_factory=list)
    max_catchup_days: StrictInt = Field(ge=1)
    strategies: list[Literal["last_window", "all", "from_now"]] = Field(
        default_factory=list
    )


class ResearchPauseRequest(APIModel):
    days: Optional[StrictInt] = Field(default=None, ge=1, le=3650)
    until: Optional[datetime] = None

    @field_validator("until")
    @classmethod
    def until_must_be_timezone_aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("until must include a timezone")
        return value

    @model_validator(mode="after")
    def provide_exactly_one_pause_form(self):
        if (self.days is None) == (self.until is None):
            raise ValueError("Provide exactly one of days or until")
        return self


class ResearchResumeRequest(APIModel):
    strategy: Literal["catch_up", "from_now"] = "catch_up"
    catchup_days: Optional[StrictInt] = Field(default=None, ge=1, le=3650)

    @model_validator(mode="after")
    def validate_catchup_override(self):
        if self.strategy == "from_now" and self.catchup_days is not None:
            raise ValueError("catchup_days cannot be combined with from_now")
        return self


class ResearchPauseResultView(APIModel):
    runtime_state: ResearchProfileStateRecord


class ResearchResumeResultView(APIModel):
    runtime_state: ResearchProfileStateRecord
    strategy: Literal["catch_up", "from_now"]
    watermark_skipped: bool


class ResearchDateRangeRequest(APIModel):
    mode: Literal["incremental", "last_7_days", "last_30_days", "last_90_days", "custom"]
    start: Optional[NonEmptyText] = None
    end: Optional[NonEmptyText] = None

    @model_validator(mode="after")
    def validate_custom_range(self):
        if self.mode == "custom":
            if self.start is None or self.end is None:
                raise ValueError("custom date_range requires start and end")
        elif self.start is not None or self.end is not None:
            raise ValueError("start and end are only valid for a custom date_range")
        return self


class ResearchManualRunRequest(APIModel):
    lenses: Optional[list[Slug]] = Field(default=None, min_length=1, max_length=20)
    breadth: Optional[Literal["strict", "balanced", "explore"]] = None
    date_range: Optional[ResearchDateRangeRequest] = None
    additional_queries: list[Annotated[StrictStr, Field(min_length=1, max_length=2000)]] = Field(
        default_factory=list, max_length=20
    )
    additional_query_lens: Optional[Slug] = None

    @model_validator(mode="after")
    def validate_query_values(self):
        if any(not query.strip() for query in self.additional_queries):
            raise ValueError("additional_queries must contain non-empty query text")
        normalized = [" ".join(query.casefold().split()) for query in self.additional_queries]
        if len(normalized) != len(set(normalized)):
            raise ValueError("additional_queries must be unique")
        if self.lenses is not None and len(self.lenses) != len(set(self.lenses)):
            raise ValueError("lenses must be unique")
        if self.additional_query_lens is not None and not self.additional_queries:
            raise ValueError("additional_query_lens requires additional_queries")
        return self


class ResearchQueuedRunView(APIModel):
    request_id: str
    status: Literal["pending", "claimed", "completed", "failed"]


class ResearchDismissRequest(APIModel):
    reason: Literal[
        "not_relevant", "already_known", "too_redundant", "not_interested", "other"
    ]
    note: Optional[Annotated[str, Field(max_length=4000)]] = None


class ResearchShortlistRequest(APIModel):
    note: Optional[Annotated[str, Field(max_length=4000)]] = None


class ResearchCandidateNoteRequest(APIModel):
    note: Optional[Annotated[str, Field(max_length=4000)]] = None


class ResearchSaveSourceResultView(APIModel):
    action: Literal["linked_existing", "draft_created", "draft_reused"]
    source_id: Slug
    draft_id: Optional[str] = None
    candidate: ResearchCandidateRecord


class ResearchCreateNoteRequest(APIModel):
    document_type: Literal["paper-note", "learning-note"]
    template: Literal["structured", "blank"] = "structured"
    collection_id: Optional[Slug] = None
    section_id: Optional[Slug] = None

    @model_validator(mode="after")
    def validate_section_collection(self):
        if self.section_id is not None and self.collection_id is None:
            raise ValueError("section_id requires collection_id")
        return self


class ResearchCreateNoteResultView(APIModel):
    group_id: NonEmptyText
    source_draft_id: Optional[NonEmptyText] = None
    document_draft_id: NonEmptyText
    collection_draft_id: Optional[NonEmptyText] = None
    collection_id: Optional[Slug] = None
    document_id: Slug
    source_id: Optional[Slug] = None


class ResearchCandidateListItem(APIModel):
    candidate: ResearchCandidateRecord
    work: ResearchWorkRecord
    analysis: ResearchCandidateAnalysisOutput
    recommended_score: float


class ResearchLinkedEntityView(APIModel):
    entity_type: Literal["source", "document"]
    entity_id: str
    relation_type: Literal["source", "note"]
    created_at: str


class ResearchPendingLinkView(APIModel):
    id: str
    group_id: str
    draft_id: str
    intended_entity_type: str
    intended_entity_id: str
    relation_type: str
    created_at: str


class ResearchCandidateDetailView(APIModel):
    candidate: ResearchCandidateRecord
    work: ResearchWorkRecord
    analysis: ResearchWorkAnalysisRecord
    discoveries: list[ResearchDiscoveryRecord]
    knowledge_relations: list[ResearchRelation]
    linked_entities: list[ResearchLinkedEntityView]
    pending_links: list[ResearchPendingLinkView]


class ResearchRunListView(APIModel):
    runs: list[ResearchRunRecord]
    count: int


class ResearchCandidateListView(APIModel):
    candidates: list[ResearchCandidateListItem]
    count: int
    offset: int
    limit: int
