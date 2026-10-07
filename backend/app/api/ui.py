"""Small aggregate responses used by the global application shell."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field


router = APIRouter(prefix="/api/ui", tags=["UI"])


class UiSummaryView(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    terms_open: int = Field(ge=0)
    terms_pending: int = Field(ge=0)
    term_drafts: int = Field(ge=0)
    research_new: int = Field(ge=0)
    research_capacity: int = Field(ge=0)
    research_profiles: int = Field(ge=0)
    pending_imports: int = Field(ge=0)
    maintenance: int = Field(ge=0)


@router.get("/summary", response_model=UiSummaryView)
async def get_ui_summary(request: Request):
    return request.app.state.ui_summary_service.get_summary()
