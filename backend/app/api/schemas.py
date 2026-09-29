"""Stable request and response contracts exposed by the Knowledge API."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.domain.common import NonEmptyText


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntitySummary(APIModel):
    id: str
    title: str
    entity_type: Literal["document", "term", "source"]
    metadata: dict[str, Any]


class EntityDetail(EntitySummary):
    content: Optional[str] = None
    canonical_content: Optional[str] = None
    related_terms: list[dict[str, Any]] = Field(default_factory=list)
    backlinks: list[dict[str, Any]] = Field(default_factory=list)
    detected_mentions: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    related_documents: list[dict[str, Any]] = Field(default_factory=list)


class TopicView(APIModel):
    id: str
    title: str


class TaxonomyEntryView(APIModel):
    id: str
    title: str
    kind: Literal["domain", "topic", "tag"]


class RecentlyModifiedView(EntitySummary):
    modified_at: str


class SearchResultView(APIModel):
    entity_type: Literal["document", "term", "source"]
    entity_id: str
    title: str
    matched_by: str
    score: float
    snippet: str
    metadata: dict[str, Any]
    view_count: int
    search_click_count: int


class DraftCreateRequest(APIModel):
    entity_type: Literal["document", "term", "source", "taxonomy"]
    entity_id: NonEmptyText
    content: str


class DraftUpdateRequest(APIModel):
    content: str
    expected_revision: int = Field(ge=1)


class DraftRebaseRequest(APIModel):
    content: str
    expected_revision: int = Field(ge=1)
    expected_current_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class DraftDeleteRequest(APIModel):
    expected_revision: int = Field(ge=1)


class DraftView(APIModel):
    id: str
    entity_type: str
    entity_id: str
    base_git_revision: str
    base_content_hash: str
    content: str
    revision: int
    created_at: str
    updated_at: str


class DraftCompareView(APIModel):
    draft: DraftView
    base_content: str
    current_content: str
    current_git_revision: str
    current_content_hash: str
    canonical_changed: bool


class ProposalView(APIModel):
    id: str
    target_type: str
    target_id: str
    kind: str
    status: str
    base_content_hash: str
    payload: dict[str, Any]
    diff_text: Optional[str]
    created_by: str
    provider: Optional[str]
    model: Optional[str]
    created_at: str
    reviewed_at: Optional[str]
    review_note: Optional[str]


class ProposalReviewRequest(APIModel):
    review_note: Optional[str] = None
    candidate_type: Optional[Literal["term", "taxonomy"]] = None
    candidate_value: Optional[str] = None
    scope: str = "global"


class PublishRequest(APIModel):
    draft_id: str
    proposal_id: Optional[str] = None
    commit_message: Optional[str] = None


class PublishedView(APIModel):
    draft_id: str
    entity_type: str
    entity_id: str
    commit_revision: str
    proposal_id: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class ProposalMergeRequest(APIModel):
    commit_message: Optional[str] = None


class ImportCreateRequest(APIModel):
    paths: list[NonEmptyText] = Field(min_length=1, max_length=100)
    profile: Literal["standard", "legacy"] = "standard"


class ImportItemView(APIModel):
    id: str
    job_id: str
    display_name: str
    file_type: Literal["markdown", "pdf"]
    sha256: str
    status: Literal["ready", "needs_review", "duplicate", "drafted", "confirmed", "failed"]
    detected_entity_type: Optional[str]
    metadata: dict[str, Any]


class ImportJobView(APIModel):
    id: str
    status: str
    profile: str
    created_at: str
    updated_at: str
    error_message: Optional[str]
    items: list[ImportItemView]


class BundleAssociationView(APIModel):
    markdown: ImportItemView
    pdf: ImportItemView


class ImportItemUpdateRequest(APIModel):
    content: str


class BlankDocumentRequest(APIModel):
    title: NonEmptyText
    document_type: Literal["paper-note", "learning-note", "course-note"] = "learning-note"
    entity_id: Optional[str] = None


class ConfirmSourceRequest(APIModel):
    source_id: Optional[str] = None
    title: Optional[str] = None
    source_type: Literal["paper", "book", "course", "web", "personal"] = "paper"
    authors: Optional[list[str]] = None
    year: Optional[int] = Field(default=None, ge=1000, le=9999)
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    zotero_key: Optional[str] = None


class BundleAssociationRequest(APIModel):
    markdown_item_id: str
    pdf_item_id: str


class UsageRequest(APIModel):
    document_id: NonEmptyText


class UsageEventView(APIModel):
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    created_at: str


class UsageDocumentView(APIModel):
    entity_id: str
    title: str
    view_count: int
    search_click_count: int
    last_viewed_at: Optional[str]


class AIRequest(APIModel):
    draft_id: NonEmptyText
    confirm_deepseek_transfer: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_transfer_confirmation(self):
        if self.confirm_deepseek_transfer is not True:
            raise ValueError("Confirm that Draft content and registry context may be sent to DeepSeek")
        return self


class SelectionReviewRequest(AIRequest):
    selection: NonEmptyText = Field(max_length=20000)


class AIProposalView(APIModel):
    external_provider_notice: str
    proposal: ProposalView


class ContextExportRequest(APIModel):
    document_id: Optional[NonEmptyText] = None
    source_id: Optional[NonEmptyText] = None
    trust: Literal["raw", "reviewed", "verified"] = Field(
        default="raw",
        description=(
            "The verified level is a provisional traceability filter based on human Document approval "
            "and verified Source metadata; it does not represent per-claim Evidence review."
        ),
    )
    purpose: Literal["research", "teaching", "evidence"] = "research"

    @model_validator(mode="after")
    def exactly_one_target(self):
        if bool(self.document_id) == bool(self.source_id):
            raise ValueError("Provide exactly one of document_id or source_id")
        return self


class ContextExportView(APIModel):
    scope: dict[str, str]
    trust: str
    purpose: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    terms: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    known_ambiguities: list[dict[str, Any]] = Field(default_factory=list)
