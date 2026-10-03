"""Profile controls, Research Runs, and human-reviewed Candidate routes."""

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request

from backend.app.api.research_schemas import (
    ResearchCandidateDetailView,
    ResearchCandidateNoteRequest,
    ResearchCandidateListItem,
    ResearchCandidateListView,
    ResearchCreateNoteRequest,
    ResearchCreateNoteResultView,
    ResearchDateRangeRequest,
    ResearchDismissRequest,
    ResearchManualRunRequest,
    ResearchPauseRequest,
    ResearchPauseResultView,
    ResearchProfileDetailView,
    ResearchProfileSummaryView,
    ResearchQueuedRunView,
    ResearchResumeRequest,
    ResearchResumeResultView,
    ResearchReactivationReviewRequest,
    ResearchReactivationReviewView,
    ResearchSaveSourceResultView,
    ResearchRunListView,
    ResearchRunSummaryView,
    ResearchShortlistRequest,
    ResearchInboxUsageView,
)
from backend.app.domain.research_runtime import ResearchCandidateStatus
from backend.app.domain.research_runtime import ResearchCandidateRecord, ResearchRunRecord
from backend.app.services.research_conversion_service import ResearchConversionError


router = APIRouter(prefix="/api/research", tags=["Research"])


@router.get("/profiles", response_model=list[ResearchProfileSummaryView])
async def list_profiles(request: Request):
    service = request.app.state.research_service
    return [
        _profile_summary(service, profile)
        for profile in service.profile_registry.profiles
    ]


@router.get("/profiles/{profile_id}", response_model=ResearchProfileDetailView)
async def get_profile(profile_id: str, request: Request):
    service = request.app.state.research_service
    profile = _require_profile(service, profile_id)
    state = service.profile_state_repository.get(profile_id)
    latest = service.run_repository.list_for_profile(profile_id, limit=1)
    resume_strategies = service.watermarks.resume_options(profile, None, service.now())
    resume_options = ["catch_up"]
    if "from_now" in resume_strategies:
        resume_options.append("from_now")
    return {
        "profile": profile,
        "runtime_state": state,
        "inbox": _inbox(service, profile),
        "latest_run": _run_summary(latest[0]) if latest else None,
        "resume_options": resume_options,
    }


@router.post(
    "/profiles/{profile_id}/reactivation-review",
    response_model=ResearchReactivationReviewView,
)
async def review_profile_reactivation(
    profile_id: str, body: ResearchReactivationReviewRequest, request: Request
):
    service = request.app.state.research_service
    _require_profile(service, profile_id)
    draft = request.app.state.draft_service.get(body.draft_id)
    if draft.entity_type != "research_profile" or draft.entity_id != profile_id:
        raise HTTPException(
            status_code=422,
            detail="Reactivation Review requires a Draft for this Research Profile",
        )
    preflight = request.app.state.publisher.preflight(draft.id)
    if not preflight.valid:
        raise HTTPException(
            status_code=422,
            detail="Research Profile Draft must pass preflight before Reactivation Review",
        )
    candidate = service.parse_profile_candidate(profile_id, draft.content)
    return service.reactivation_review(candidate)


@router.post(
    "/profiles/{profile_id}/pause", response_model=ResearchPauseResultView
)
async def pause_profile(
    profile_id: str, body: ResearchPauseRequest, request: Request
):
    service = request.app.state.research_service
    now = service.now()
    paused_until = (
        now + timedelta(days=body.days)
        if body.days is not None
        else body.until.astimezone(timezone.utc)
    )
    state = service.pause_profile(profile_id, paused_until, now)
    return {"runtime_state": state}


@router.post(
    "/profiles/{profile_id}/resume", response_model=ResearchResumeResultView
)
async def resume_profile(
    profile_id: str, body: ResearchResumeRequest, request: Request
):
    service = request.app.state.research_service
    state = service.resume_profile(
        profile_id,
        strategy=body.strategy,
        catchup_days=body.catchup_days,
        now=service.now(),
    )
    return {
        "runtime_state": state,
        "strategy": body.strategy,
        "watermark_skipped": body.strategy == "from_now",
    }


@router.post(
    "/profiles/{profile_id}/runs",
    response_model=ResearchQueuedRunView,
    status_code=202,
)
async def queue_manual_run(
    profile_id: str, body: ResearchManualRunRequest, request: Request
):
    service = request.app.state.research_service
    profile = _require_profile(service, profile_id)
    if body.lenses is not None:
        known_lenses = {lens.id for lens in profile.lenses}
        if set(body.lenses) - known_lenses:
            raise ValueError("Manual Research Run contains an unknown Lens id")
        lens_overrides = {
            lens.id: lens.id in body.lenses for lens in profile.lenses
        }
    else:
        lens_overrides = None

    override = {}
    if lens_overrides is not None:
        override["lens_overrides"] = lens_overrides
    if body.breadth is not None:
        override["breadth"] = body.breadth
    if body.additional_queries:
        override["additional_queries"] = body.additional_queries
    if body.additional_query_lens is not None:
        override["additional_query_lens"] = body.additional_query_lens
    if body.date_range is not None:
        if body.date_range.mode == "incremental":
            override["manual_incremental"] = True
        else:
            now = service.now()
            start, end = _date_range(body.date_range, now)
            override["manual_range"] = [start.isoformat(), end.isoformat()]

    queued = service.queue_manual_run(profile_id, override)
    return {"request_id": queued.id, "status": queued.status}


@router.get("/runs", response_model=ResearchRunListView)
async def list_runs(
    request: Request,
    profile_id: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    service = request.app.state.research_service
    if profile_id is not None:
        _require_profile(service, profile_id)
    runs = service.run_repository.list_recent(limit, offset, profile_id)
    return {"runs": runs, "count": service.run_repository.count_recent(profile_id)}


@router.get("/runs/{run_id}", response_model=ResearchRunRecord)
async def get_run(run_id: str, request: Request):
    run = request.app.state.research_service.run_repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research Run not found")
    return run


@router.get("/candidates", response_model=ResearchCandidateListView)
async def list_candidates(
    request: Request,
    profile_id: Optional[str] = None,
    status: Optional[ResearchCandidateStatus] = Query(default=None),
    lens: Optional[str] = None,
    sort: Literal["recommended", "newest", "most_relevant", "most_novel"] = "recommended",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    service = request.app.state.research_service
    if profile_id is not None:
        profile = _require_profile(service, profile_id)
        if lens is not None and lens not in {item.id for item in profile.lenses}:
            raise ValueError("Research Lens does not belong to the selected Profile")
        ranking_profile = profile
    else:
        ranking_profile = None
    breadth = ranking_profile.search.breadth if ranking_profile else "balanced"
    ranking = getattr(service.profile_registry.global_config.ranking, breadth)
    weights = (
        ranking.profile_relevance_weight,
        ranking.knowledge_relevance_weight,
        ranking.novelty_weight,
    )
    repository = service.candidate_repository
    page = repository.list_filtered(
        profile_id=profile_id,
        status=status,
        lens_id=lens,
        sort=sort,
        offset=offset,
        limit=limit,
        ranking_weights=weights,
    )
    items = []
    for candidate in page:
        work = service.work_repository.get_work(candidate.work_id)
        analysis = service.work_repository.get_analysis_by_id(candidate.analysis_id)
        if work is None or analysis is None:
            continue
        output = analysis.analysis
        score = (
            weights[0] * output.profile_relevance
            + weights[1] * output.knowledge_relevance
            + weights[2] * output.novelty_to_library
        )
        items.append(
            ResearchCandidateListItem(
                candidate=candidate,
                work=work,
                analysis=output,
                recommended_score=score,
            )
        )
    return {
        "candidates": items,
        "count": repository.count_filtered(profile_id, status, lens),
        "offset": offset,
        "limit": limit,
    }


@router.get("/candidates/{candidate_id}", response_model=ResearchCandidateDetailView)
async def get_candidate(candidate_id: str, request: Request):
    service = request.app.state.research_service
    candidate = service.candidate_repository.get(candidate_id)
    if candidate is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Research Candidate not found")
    candidate = service.candidate_service.mark_viewed(candidate_id)
    work = service.work_repository.get_work(candidate.work_id)
    analysis = service.work_repository.get_analysis_by_id(candidate.analysis_id)
    if work is None or analysis is None:
        raise RuntimeError("Research Candidate is missing its Work or Analysis")
    return {
        "candidate": candidate,
        "work": work,
        "analysis": analysis,
        "discoveries": service.work_repository.list_discoveries_for_candidate_context(
            work.id, candidate.profile_id
        ),
        "knowledge_relations": analysis.analysis.existing_relations,
        "linked_entities": service.work_repository.list_entity_links(work.id),
        "pending_links": service.work_repository.list_pending_links(candidate.id),
    }


@router.post(
    "/candidates/{candidate_id}/shortlist",
    response_model=ResearchCandidateRecord,
)
async def shortlist_candidate(
    candidate_id: str,
    request: Request,
    body: Optional[ResearchShortlistRequest] = Body(default=None),
):
    return request.app.state.research_service.candidate_service.shortlist(
        candidate_id, user_note=body.note if body is not None else None
    )


@router.patch(
    "/candidates/{candidate_id}/note",
    response_model=ResearchCandidateRecord,
)
async def update_candidate_note(
    candidate_id: str, request: Request, body: ResearchCandidateNoteRequest
):
    return request.app.state.research_service.candidate_service.update_user_note(
        candidate_id, user_note=body.note
    )


@router.post(
    "/candidates/{candidate_id}/save-source",
    response_model=ResearchSaveSourceResultView,
)
async def save_candidate_source(candidate_id: str, request: Request):
    result = request.app.state.research_conversion_service.save_source(candidate_id)
    return {
        "action": result.action,
        "source_id": result.source_id,
        "draft_id": result.draft_id,
        "candidate": result.candidate,
    }


@router.post(
    "/candidates/{candidate_id}/create-note",
    response_model=ResearchCreateNoteResultView,
)
async def create_candidate_note(
    candidate_id: str, body: ResearchCreateNoteRequest, request: Request
):
    try:
        result = request.app.state.research_conversion_service.create_note(
            candidate_id,
            document_type=body.document_type,
            template=body.template,
            collection_id=body.collection_id,
            section_id=body.section_id,
        )
    except ResearchConversionError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    return {
        "group_id": result.group_id,
        "source_draft_id": result.source_draft_id,
        "document_draft_id": result.document_draft_id,
        "collection_draft_id": result.collection_draft_id,
        "collection_id": result.collection_id,
        "document_id": result.document_id,
        "source_id": result.source_id,
    }


@router.post(
    "/candidates/{candidate_id}/dismiss", response_model=ResearchCandidateRecord
)
async def dismiss_candidate(
    candidate_id: str, body: ResearchDismissRequest, request: Request
):
    reason_map = {
        "not_relevant": "not_relevant",
        "already_known": "already_known",
        "too_redundant": "too_similar",
        "not_interested": "not_following_subfield",
        "other": "other",
    }
    return request.app.state.research_service.candidate_service.dismiss(
        candidate_id,
        reason=reason_map[body.reason],
        user_note=body.note,
    )


def _profile_summary(service, profile):
    state = service.profile_state_repository.get(profile.id)
    latest = service.run_repository.list_for_profile(profile.id, limit=1)
    return ResearchProfileSummaryView(
        id=profile.id,
        title=profile.title,
        description=profile.description,
        enabled=profile.enabled,
        schedule_mode=profile.schedule.mode,
        breadth=profile.search.breadth,
        lens_count=len(profile.lenses),
        enabled_lens_ids=[lens.id for lens in profile.lenses if lens.enabled],
        paused_until=state.paused_until if state else None,
        last_successful_scheduled_run_at=(
            state.last_successful_scheduled_run_at if state else None
        ),
        inbox=_inbox(service, profile),
        latest_run=_run_summary(latest[0]) if latest else None,
    )


def _inbox(service, profile):
    new_count = service.candidate_repository.count_new(profile.id)
    capacity = profile.inbox.max_new_candidates
    return ResearchInboxUsageView(
        new_count=new_count,
        capacity=capacity,
        remaining=max(0, capacity - new_count),
    )


def _run_summary(run):
    return ResearchRunSummaryView(
        id=run.id,
        trigger=run.trigger,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        fetched_count=run.fetched_count,
        surfaced_count=run.surfaced_count,
    )


def _require_profile(service, profile_id: str):
    profile = service.profile_registry.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Research Profile not found")
    return profile


def _date_range(value: ResearchDateRangeRequest, now: datetime) -> tuple[datetime, datetime]:
    if value.mode == "custom":
        start = _parse_date(value.start)
        end = _parse_date(value.end)
    else:
        days = {
            "last_7_days": 7,
            "last_30_days": 30,
            "last_90_days": 90,
        }[value.mode]
        start, end = now - timedelta(days=days), now
    if start >= end:
        raise ValueError("Manual Research Run date_range must end after it starts")
    if end > now:
        raise ValueError("Manual Research Run date_range cannot end in the future")
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _parse_date(value: Optional[str]) -> datetime:
    if value is None:
        raise ValueError("Custom Research date_range requires start and end")
    if len(value) == 10:
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Research date_range contains an invalid date") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Research date_range timestamps must include a timezone")
    return result.astimezone(timezone.utc)
