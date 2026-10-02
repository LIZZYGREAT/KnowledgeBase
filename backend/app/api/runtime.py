"""Runtime API router aggregation."""

from fastapi import APIRouter

from backend.app.api.annotations import router as annotations_router
from backend.app.api.collections import router as collections_router
from backend.app.api.drafts import router as drafts_router
from backend.app.api.imports import router as imports_router
from backend.app.api.proposals import router as proposals_router
from backend.app.api.publishing import router as publishing_router
from backend.app.api.usage import router as usage_router

router = APIRouter()
for child_router in (
    annotations_router,
    drafts_router,
    collections_router,
    proposals_router,
    publishing_router,
    imports_router,
    usage_router,
):
    router.include_router(child_router)
