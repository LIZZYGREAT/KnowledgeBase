"""User-managed Learning Context API."""

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr


class LearningContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourcesRequest(LearningContextRequest):
    included_document_ids: list[StrictStr]


class PreferencesRequest(LearningContextRequest):
    fixed_direction: StrictStr = ""
    keywords: list[StrictStr] = Field(default_factory=list)
    exclude_keywords: list[StrictStr] = Field(default_factory=list)
    exploration_directions: list[StrictStr] = Field(default_factory=list)
    important_anchors: list[StrictStr] = Field(default_factory=list)


class MemoryRequest(LearningContextRequest):
    markdown: StrictStr


router = APIRouter(prefix="/api/learning-context", tags=["Learning Context"])


@router.get("")
async def get_learning_context(request: Request):
    return request.app.state.learning_context_service.get_overview()


@router.get("/sources")
async def get_learning_sources(request: Request):
    return request.app.state.learning_context_service.get_sources()


@router.put("/sources")
async def set_learning_sources(body: SourcesRequest, request: Request):
    return request.app.state.learning_context_service.set_sources(body.included_document_ids)


@router.get("/preferences")
async def get_learning_preferences(request: Request):
    return request.app.state.learning_context_service.get_preferences()


@router.put("/preferences")
async def set_learning_preferences(body: PreferencesRequest, request: Request):
    return request.app.state.learning_context_service.set_preferences(body.model_dump())


@router.get("/topics")
async def list_learning_topics(request: Request):
    return request.app.state.learning_context_service.list_topics()


@router.get("/topics/{topic_id}")
async def get_learning_topic(topic_id: str, request: Request):
    return request.app.state.learning_context_service.read_topic(topic_id)


@router.put("/topics/{topic_id}")
async def save_learning_topic(topic_id: str, body: MemoryRequest, request: Request):
    return request.app.state.learning_context_service.save_topic(topic_id, body.markdown)


@router.put("/memory/{layer}")
async def save_learning_memory(layer: str, body: MemoryRequest, request: Request):
    return request.app.state.learning_context_service.save_memory(layer, body.markdown)


@router.post("/memory/{layer}/restore-automatic")
async def restore_automatic_learning_memory(
    layer: str, request: Request, topic_id: Optional[str] = None
):
    return request.app.state.learning_context_service.restore_automatic_memory(
        layer, topic_id
    )
