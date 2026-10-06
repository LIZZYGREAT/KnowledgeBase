"""Request bodies for Term Candidate operations."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, constr


class TermRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RejectTermCandidateRequest(TermRequest):
    scope: Literal["local", "global"]
    reason: Optional[constr(strict=True, strip_whitespace=True, min_length=1)] = None


class AcceptExistingTermCandidateRequest(TermRequest):
    term_id: constr(strict=True, strip_whitespace=True, min_length=1)


class TermMergePreviewRequest(TermRequest):
    survivor_term_id: constr(strict=True, strip_whitespace=True, min_length=1)
    loser_term_ids: list[constr(strict=True, strip_whitespace=True, min_length=1)] = Field(
        min_length=1
    )
    final_title: constr(strict=True, strip_whitespace=True, min_length=1)


class TermMergeRequest(TermMergePreviewRequest):
    confirm_loser_bodies_not_merged: bool = False


class TermMergePreviewView(TermRequest):
    survivor_term_id: str
    loser_term_ids: list[str]
    final_title: str
    aliases: list[str]
    loser_bodies_not_merged: list[str]


class TermMergeResultView(TermMergePreviewView):
    commit_revision: str
    warnings: list[str] = Field(default_factory=list)


