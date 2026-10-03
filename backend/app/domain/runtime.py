"""Runtime-only records; these are never canonical knowledge entities."""

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


DraftEntityType = Literal[
    "document", "term", "source", "taxonomy", "collection", "research_profile"
]
ProposalTargetType = Literal["document", "term", "source", "taxonomy"]
ProposalKind = Literal[
    "metadata",
    "link",
    "new_term",
    "term_revision",
    "document_revision",
    "taxonomy",
    "evidence",
    "format",
]
ProposalStatus = Literal["proposed", "drafted", "merged", "rejected", "stale"]
CandidateType = Literal["term", "taxonomy"]
AnnotationEntityType = Literal["document", "term"]
AnnotationStyleType = Literal["highlight", "text_color", "underline"]
AnnotationStatus = Literal["active", "stale"]


@dataclass(frozen=True)
class Draft:
    id: str
    entity_type: DraftEntityType
    entity_id: str
    base_git_revision: str
    base_content_hash: str
    content: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DraftAcquireResult:
    draft: Draft
    created: bool


@dataclass(frozen=True)
class Proposal:
    id: str
    target_type: ProposalTargetType
    target_id: str
    kind: ProposalKind
    status: ProposalStatus
    base_content_hash: str
    payload: Dict[str, Any]
    diff_text: Optional[str]
    created_by: str
    provider: Optional[str]
    model: Optional[str]
    created_at: str
    reviewed_at: Optional[str]
    review_note: Optional[str]


@dataclass(frozen=True)
class RejectedCandidate:
    id: str
    candidate_type: CandidateType
    normalized_value: str
    reason: str
    scope: str
    created_at: str


@dataclass(frozen=True)
class PresentationAnnotation:
    id: str
    entity_type: AnnotationEntityType
    entity_id: str
    style_type: AnnotationStyleType
    style_value: Optional[str]
    selected_text: str
    prefix_text: str
    suffix_text: str
    start_offset: int
    end_offset: int
    base_content_hash: str
    status: AnnotationStatus
    created_at: str
    updated_at: str
