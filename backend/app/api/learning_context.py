"""User-managed Learning Context API."""

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr


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


class MemoryEntryRequest(LearningContextRequest):
    layer: Literal["active", "important", "topic"]
    topic_id: Optional[StrictStr] = None
    title: StrictStr
    summary: StrictStr


class TopicStatusRequest(LearningContextRequest):
    status: Literal["current", "history", "automatic"]


class SyncRequest(LearningContextRequest):
    dry_run: StrictBool = False
    force: StrictBool = False
    source_id: Optional[StrictStr] = None


router = APIRouter(prefix="/api/learning-context", tags=["Learning Context"])


@router.get("")
async def get_learning_context(request: Request):
    return request.app.state.learning_context_service.get_overview()


@router.post("/sync")
async def sync_learning_context(body: SyncRequest, request: Request):
    return await asyncio.to_thread(
        request.app.state.learning_context_service.sync,
        dry_run=body.dry_run,
        force=body.force,
        source_id=body.source_id,
    )


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


@router.put("/topics/{topic_id}/status")
async def set_learning_topic_status(
    topic_id: str, body: TopicStatusRequest, request: Request
):
    return request.app.state.learning_context_service.set_topic_status(
        topic_id, body.status
    )


@router.put("/topics/{topic_id}")
async def save_learning_topic(topic_id: str, body: MemoryRequest, request: Request):
    return request.app.state.learning_context_service.save_topic(topic_id, body.markdown)


@router.put("/memory/{layer}")
async def save_learning_memory(layer: str, body: MemoryRequest, request: Request):
    return request.app.state.learning_context_service.save_memory(layer, body.markdown)


@router.put("/entries/{entry_id}")
async def update_learning_memory_entry(
    entry_id: str, body: MemoryEntryRequest, request: Request
):
    return request.app.state.learning_context_service.update_memory_entry(
        body.layer,
        entry_id,
        body.title,
        body.summary,
        body.topic_id,
    )


@router.post("/memory/{layer}/restore-automatic")
async def restore_automatic_learning_memory(
    layer: str,
    request: Request,
    topic_id: Optional[str] = None,
    entry_id: Optional[str] = None,
    confirm_support: bool = False,
):
    return request.app.state.learning_context_service.restore_automatic_memory(
        layer, topic_id, entry_id, confirm_support
    )
