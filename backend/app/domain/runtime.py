"""Runtime-only records; these are never canonical knowledge entities."""

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


EntityType = Literal["document", "term", "source", "taxonomy"]
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
ProposalStatus = Literal["proposed", "drafted", "approved", "merged", "rejected", "stale"]
CandidateType = Literal["term", "taxonomy"]


@dataclass(frozen=True)
class Draft:
    id: str
    entity_type: EntityType
    entity_id: str
    base_git_revision: str
    base_content_hash: str
    content: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Proposal:
    id: str
    target_type: EntityType
    target_id: str
    kind: ProposalKind
    status: ProposalStatus
    base_revision: str
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
