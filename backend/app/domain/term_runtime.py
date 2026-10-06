"""Runtime records for human-reviewed Term discovery and relations."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, constr


NonEmptyText = constr(strict=True, strip_whitespace=True, min_length=1)


class TermRuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


TermType = Literal["concept", "entity", "vocabulary"]
TermCandidateStatus = Literal["pending", "drafting", "accepted", "rejected"]
TermOriginType = Literal["document", "source", "research_work", "external"]
TermRelationEntityType = Literal["document", "source", "research_work"]


class TermCandidateEvidenceInput(TermRuntimeModel):
    origin_type: TermOriginType
    origin_id: NonEmptyText
    mention: NonEmptyText
    context_excerpt: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    rationale: Optional[str] = None


class TermCandidateEvidence(TermCandidateEvidenceInput):
    id: NonEmptyText
    candidate_id: NonEmptyText
    discovered_at: NonEmptyText
    origin_title: Optional[str] = None
    origin_rejected: bool = False


class TermCandidateRecord(TermRuntimeModel):
    id: NonEmptyText
    normalized_name: NonEmptyText
    display_name: NonEmptyText
    suggested_type: TermType
    suggested_term_id: Optional[NonEmptyText] = None
    status: TermCandidateStatus
    draft_id: Optional[NonEmptyText] = None
    accepted_term_id: Optional[NonEmptyText] = None
    created_at: NonEmptyText
    updated_at: NonEmptyText
    reviewed_at: Optional[NonEmptyText] = None


class TermCandidateDetail(TermCandidateRecord):
    evidence: list[TermCandidateEvidence] = Field(default_factory=list)


class TermEntityRelation(TermRuntimeModel):
    id: NonEmptyText
    entity_type: TermRelationEntityType
    entity_id: NonEmptyText
    term_id: NonEmptyText
    created_from_candidate_id: Optional[NonEmptyText] = None
    created_at: NonEmptyText
