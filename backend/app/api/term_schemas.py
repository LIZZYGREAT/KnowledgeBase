"""Request bodies for Term Candidate operations."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, constr, model_validator


class TermRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RejectTermCandidateRequest(TermRequest):
    scope: Literal["local", "global"]
    reason: Optional[constr(strict=True, strip_whitespace=True, min_length=1)] = None


class AcceptExistingTermCandidateRequest(TermRequest):
    term_id: constr(strict=True, strip_whitespace=True, min_length=1)


class DocumentTermAnalysisRequest(TermRequest):
    confirm_deepseek_transfer: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_transfer_confirmation(self):
        if self.confirm_deepseek_transfer is not True:
            raise ValueError(
                "Confirm that canonical Document content and required Term Registry context may be sent to DeepSeek"
            )
        return self


class DocumentTermAnalysisStatistics(TermRequest):
    created_candidates: int
    reused_candidates: int
    existing: int
    new: int
    skipped: int


class DocumentTermAnalysisStateView(TermRequest):
    document_id: str
    status: Literal["never_analyzed", "up_to_date", "outdated"]
    analyzed_content_hash: Optional[str] = None
    prompt_version: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    analyzed_at: Optional[str] = None


class DocumentTermAnalysisResultView(DocumentTermAnalysisStateView):
    status: Literal["up_to_date"]
    analyzed_content_hash: str
    prompt_version: str
    provider: str
    model: str
    analyzed_at: str
    statistics: DocumentTermAnalysisStatistics


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


