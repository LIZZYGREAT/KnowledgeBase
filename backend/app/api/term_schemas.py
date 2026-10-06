"""Request bodies for Term Candidate operations."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, constr


class TermRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RejectTermCandidateRequest(TermRequest):
    scope: Literal["local", "global"]
    reason: Optional[constr(strict=True, strip_whitespace=True, min_length=1)] = None


class AcceptExistingTermCandidateRequest(TermRequest):
    term_id: constr(strict=True, strip_whitespace=True, min_length=1)


