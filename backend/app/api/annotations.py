"""Presentation annotation API routes."""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Request, status

from backend.app.api.schemas import (
    PresentationAnnotationCreateRequest,
    PresentationAnnotationStyleRequest,
    PresentationAnnotationView,
)

router = APIRouter(prefix="/api", tags=["Runtime"])


@router.get("/annotations", response_model=list[PresentationAnnotationView])
async def list_annotations(
    request: Request,
    entity_type: Literal["document", "term"],
    entity_id: str,
):
    entity = request.app.state.knowledge_read_service.get_entity(entity_type, entity_id)
    return [
        asdict(annotation)
        for annotation in request.app.state.annotation_service.list_for_entity(
            entity_type, entity_id, entity["content"] or ""
        )
    ]


@router.get("/annotations/stale", response_model=list[PresentationAnnotationView])
async def list_stale_annotations(request: Request):
    connection = request.app.state.runtime_connection
    entities = []
    rows = connection.execute(
        "SELECT DISTINCT entity_type, entity_id FROM presentation_annotations"
    ).fetchall()
    for row in rows:
        try:
            entity = request.app.state.knowledge_read_service.get_entity(
                row["entity_type"], row["entity_id"]
            )
        except LookupError:
            continue
        entities.append((row["entity_type"], row["entity_id"], entity["content"] or ""))
    return [
        asdict(annotation)
        for annotation in request.app.state.annotation_service.list_stale(entities)
    ]


@router.post(
    "/annotations",
    response_model=PresentationAnnotationView,
    status_code=status.HTTP_201_CREATED,
)
async def create_annotation(body: PresentationAnnotationCreateRequest, request: Request):
    entity = request.app.state.knowledge_read_service.get_entity(
        body.entity_type, body.entity_id
    )
    return asdict(
        request.app.state.annotation_service.create(
            **body.model_dump(), content=entity["content"] or ""
        )
    )


@router.put("/annotations/{annotation_id}", response_model=PresentationAnnotationView)
async def update_annotation_style(
    annotation_id: str,
    body: PresentationAnnotationStyleRequest,
    request: Request,
):
    annotation = request.app.state.annotation_service.get(annotation_id)
    entity = request.app.state.knowledge_read_service.get_entity(
        annotation.entity_type, annotation.entity_id
    )
    return asdict(
        request.app.state.annotation_service.update_style(
            annotation_id,
            body.style_type,
            body.style_value,
            entity["content"] or "",
        )
    )


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, request: Request):
    request.app.state.annotation_service.delete(annotation_id)
    return {"deleted": True}
