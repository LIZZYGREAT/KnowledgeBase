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
    mention: NonEmptyText = Field(max_length=200)
    action: Literal["link_existing", "propose_new"]
    term_id: Optional[Slug] = None
    suggested_type: Optional[Literal["concept", "entity", "vocabulary"]] = None
    confidence: float = Field(ge=0, le=1)
    rationale: NonEmptyText = Field(max_length=1000)
    context_excerpt: NonEmptyText = Field(max_length=800)

    @model_validator(mode="after")
    def validate_link_target(self):
        if self.action == "link_existing" and not self.term_id:
            raise ValueError("link_existing candidates require term_id")
        if self.action == "propose_new" and self.term_id is not None:
            raise ValueError("propose_new candidates cannot include term_id")
        if self.action == "propose_new" and self.suggested_type is None:
            raise ValueError("propose_new candidates require suggested_type")
        return self


class DetectTermsOutput(AIOutput):
    candidates: list[TermCandidate] = Field(max_length=40)


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
    type: Literal["concept", "entity", "vocabulary"]
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
    reason_zh: Optional[NonEmptyText] = None


class ResearchRelationAnalysisOutput(ResearchRelation):
    reason_zh: NonEmptyText


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
    summary_zh: Optional[NonEmptyText] = None
    why_relevant_zh: Optional[NonEmptyText] = None
    reading_reason_zh: Optional[NonEmptyText] = None
    existing_relations: list[ResearchRelation] = Field(default_factory=list, max_length=12)
    suggested_collection: Optional[Slug] = None
    suggested_section: Optional[NonEmptyText] = None


class ResearchCandidateAnalysisAIOutput(ResearchCandidateAnalysisOutput):
    summary_zh: NonEmptyText
    why_relevant_zh: NonEmptyText
    reading_reason_zh: NonEmptyText
    existing_relations: list[ResearchRelationAnalysisOutput] = Field(default_factory=list, max_length=12)


TASK_OUTPUTS = {
    "suggest_metadata": SuggestMetadataOutput,
    "detect_terms": DetectTermsOutput,
    "review_format_semantics": ReviewFormatOutput,
    "review_document": ReviewDocumentOutput,
    "draft_term": DraftTermOutput,
    "suggest_revision": SuggestRevisionOutput,
    "suggest_evidence": SuggestEvidenceOutput,
    "research_candidate_analysis": ResearchCandidateAnalysisAIOutput,
}
