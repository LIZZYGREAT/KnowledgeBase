"""Structured outputs accepted from the AI Gateway."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import NonEmptyText, Slug


class AIOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MetadataChanges(AIOutput):
    title: Optional[NonEmptyText] = None
    type: Optional[Literal["paper-note", "learning-note", "course-note"]] = None
    domains: Optional[list[Slug]] = None
    topics: Optional[list[Slug]] = None
    tags: Optional[list[Slug]] = None
    sources: Optional[list[Slug]] = None


class SuggestMetadataOutput(AIOutput):
    changes: MetadataChanges
    rationale: NonEmptyText

    @model_validator(mode="after")
    def require_a_change(self):
        if not self.changes.model_dump(exclude_none=True):
            raise ValueError("metadata suggestions must include at least one change")
        return self


class TermCandidate(AIOutput):
    mention: NonEmptyText
    action: Literal["link_existing", "propose_new"]
    term_id: Optional[Slug] = None
    confidence: float = Field(ge=0, le=1)
    rationale: NonEmptyText

    @model_validator(mode="after")
    def validate_link_target(self):
        if self.action == "link_existing" and not self.term_id:
            raise ValueError("link_existing candidates require term_id")
        if self.action == "propose_new" and self.term_id is not None:
            raise ValueError("propose_new candidates cannot include term_id")
        return self


class DetectTermsOutput(AIOutput):
    candidates: list[TermCandidate]


class ReviewFinding(AIOutput):
    topic: NonEmptyText
    explanation: NonEmptyText
    suggestion: NonEmptyText
    severity: Literal["warning", "suggestion"] = "suggestion"
    line: Optional[int] = Field(default=None, ge=1)


class ReviewFormatOutput(AIOutput):
    summary: NonEmptyText
    findings: list[ReviewFinding]


class ReviewDocumentOutput(AIOutput):
    summary: NonEmptyText
    findings: list[ReviewFinding]


class DraftTermOutput(AIOutput):
    id: Slug
    title: NonEmptyText
    type: Literal["concept", "vocabulary"]
    depth: Literal["stub", "standard", "deep"]
    aliases: list[NonEmptyText] = Field(default_factory=list)
    definition: NonEmptyText


class SuggestRevisionOutput(AIOutput):
    proposed_content: NonEmptyText
    rationale: NonEmptyText


class EvidenceCandidate(AIOutput):
    source_id: Slug
    claim: NonEmptyText
    rationale: NonEmptyText


class SuggestEvidenceOutput(AIOutput):
    candidates: list[EvidenceCandidate]


class ResearchRelation(AIOutput):
    entity_type: Literal["document", "term", "source", "collection"]
    entity_id: NonEmptyText
    relation: Literal["extends", "alternative", "contrasts", "applies", "reviews", "related"]
    reason: NonEmptyText


class ResearchCandidateAnalysisOutput(AIOutput):
    relevant: bool
    profile_relevance: float = Field(ge=0.0, le=1.0)
    knowledge_relevance: float = Field(ge=0.0, le=1.0)
    novelty_to_library: float = Field(ge=0.0, le=1.0)
    matched_lenses: list[Slug] = Field(default_factory=list, max_length=1)
    matched_topics: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    summary: NonEmptyText
    why_relevant: NonEmptyText
    reading_reason: NonEmptyText
    existing_relations: list[ResearchRelation] = Field(default_factory=list, max_length=12)
    suggested_collection: Optional[Slug] = None
    suggested_section: Optional[NonEmptyText] = None


TASK_OUTPUTS = {
    "suggest_metadata": SuggestMetadataOutput,
    "detect_terms": DetectTermsOutput,
    "review_format_semantics": ReviewFormatOutput,
    "review_document": ReviewDocumentOutput,
    "draft_term": DraftTermOutput,
    "suggest_revision": SuggestRevisionOutput,
    "suggest_evidence": SuggestEvidenceOutput,
    "research_candidate_analysis": ResearchCandidateAnalysisOutput,
}
