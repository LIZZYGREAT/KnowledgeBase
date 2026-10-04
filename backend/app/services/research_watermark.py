"""Plan incremental Research searches and advance watermarks after full slices."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from backend.app.domain.research import ResearchGlobalConfig, ResearchProfile
from backend.app.domain.research_runtime import ResearchSearchStateRecord
from backend.app.repositories.research_search_repository import ResearchSearchRepository
from backend.app.services.research_query_builder import ResearchQuery, ResearchQueryBuilder


ResumeStrategy = Literal["all", "last_window", "from_now"]


@dataclass(frozen=True)
class ResearchSearchSlice:
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class ResearchSearchPlan:
    profile_id: str
    lens_id: str
    provider: str
    query_key: str
    query_text: str
    slices: tuple[ResearchSearchSlice, ...]
    manual: bool
    previous_watermark: Optional[datetime]
    watermark_skip_required: bool = False


class ResearchWatermarkService:
    def __init__(
        self,
        repository: ResearchSearchRepository,
        query_builder: Optional[ResearchQueryBuilder] = None,
    ):
        self.repository = repository
        self.query_builder = query_builder or ResearchQueryBuilder()

    def build_plan(
        self,
        profile: ResearchProfile,
        query: ResearchQuery,
        provider: str,
        now: datetime,
        global_config: ResearchGlobalConfig,
        manual_range: Optional[tuple[datetime, datetime]] = None,
        resume_strategy: ResumeStrategy = "all",
        catchup_days_override: Optional[int] = None,
        manual_incremental: bool = False,
    ) -> ResearchSearchPlan:
        now_utc = _as_utc(now, "now")
        if query.profile_id != profile.id:
            raise ValueError("Research Query belongs to a different Profile")
        if query.lens_id not in {lens.id for lens in profile.lenses}:
            raise ValueError("Research Query references an unknown Lens")
        if provider not in profile.providers.discovery:
            raise ValueError("Provider is not enabled for discovery by this Profile")
        if resume_strategy not in {"all", "last_window", "from_now"}:
            raise ValueError("Unsupported Research resume strategy")
        if catchup_days_override is not None and (
            isinstance(catchup_days_override, bool)
            or not isinstance(catchup_days_override, int)
            or catchup_days_override < 1
        ):
            raise ValueError("Research catchup_days override must be a positive integer")
        if catchup_days_override is not None and resume_strategy != "last_window":
            raise ValueError("catchup_days override requires the last_window strategy")
        if manual_incremental and manual_range is not None:
            raise ValueError("Manual incremental and historical ranges cannot be combined")
        state = self.repository.get_state(
            profile.id, query.lens_id, provider, query.query_key
        )
        previous_watermark = _parse_stored_timestamp(
            state.completed_through if state is not None else None
        )

        if manual_range is not None:
            if resume_strategy != "all":
                raise ValueError("Resume strategy does not apply to manual historical searches")
            manual_start = _as_utc(manual_range[0], "manual range start")
            manual_end = _as_utc(manual_range[1], "manual range end")
            if manual_start >= manual_end:
                raise ValueError("Manual search end must be later than start")
            if manual_end > now_utc:
                raise ValueError("Manual historical search cannot end in the future")
            return ResearchSearchPlan(
                profile_id=profile.id,
                lens_id=query.lens_id,
                provider=provider,
                query_key=query.query_key,
                query_text=query.text,
                slices=_slice_range(
                    manual_start,
                    manual_end,
                    global_config.runtime.slice_days,
                ),
                manual=True,
                previous_watermark=previous_watermark,
            )

        if resume_strategy == "from_now":
            return ResearchSearchPlan(
                profile_id=profile.id,
                lens_id=query.lens_id,
                provider=provider,
                query_key=query.query_key,
                query_text=query.text,
                slices=(),
                manual=False,
                previous_watermark=previous_watermark,
                watermark_skip_required=True,
            )

        if previous_watermark is None:
            start = now_utc - timedelta(days=profile.search.initial_lookback_days)
        else:
            start = previous_watermark - timedelta(
                hours=global_config.runtime.overlap_hours
            )
        overlap_floor = _parse_stored_timestamp(
            state.overlap_floor if state is not None else None
        )
        if overlap_floor is not None:
            start = max(start, overlap_floor)
        if resume_strategy == "last_window":
            catchup_days = (
                catchup_days_override
                if catchup_days_override is not None
                else profile.search.max_catchup_days
            )
            catchup_start = now_utc - timedelta(days=catchup_days)
            start = max(start, catchup_start)
        return ResearchSearchPlan(
            profile_id=profile.id,
            lens_id=query.lens_id,
            provider=provider,
            query_key=query.query_key,
            query_text=query.text,
            slices=_slice_range(start, now_utc, global_config.runtime.slice_days),
            manual=manual_incremental,
            previous_watermark=previous_watermark,
        )

    def resume_options(
        self,
        profile: ResearchProfile,
        queries: Optional[tuple[ResearchQuery, ...]],
        now: datetime,
    ) -> tuple[ResumeStrategy, ...]:
        now_utc = _as_utc(now, "now")
        active_queries = queries if queries is not None else self.query_builder.build(profile)
        cutoff = timedelta(days=profile.search.max_catchup_days)
        for query in active_queries:
            for provider in profile.providers.discovery:
                state = self.repository.get_state(
                    profile.id, query.lens_id, provider, query.query_key
                )
                watermark = _parse_stored_timestamp(
                    state.completed_through if state is not None else None
                )
                if watermark is not None and now_utc - watermark > cutoff:
                    return ("last_window", "all", "from_now")
        return ("all",)

    def mark_attempt(
        self,
        plan: ResearchSearchPlan,
        search_slice: ResearchSearchSlice,
        attempted_at: datetime,
    ) -> ResearchSearchStateRecord:
        _validate_scheduled_slice(plan, search_slice)
        timestamp = _timestamp(attempted_at, "attempted_at")
        return self.repository.record_attempt(
            plan.profile_id,
            plan.lens_id,
            plan.provider,
            plan.query_key,
            plan.query_text,
            timestamp,
        )

    def complete_slice(
        self,
        plan: ResearchSearchPlan,
        search_slice: ResearchSearchSlice,
        completed_at: datetime,
    ) -> ResearchSearchStateRecord:
        _validate_scheduled_slice(plan, search_slice)
        timestamp = _timestamp(completed_at, "completed_at")
        return self.repository.complete_slice(
            plan.profile_id,
            plan.lens_id,
            plan.provider,
            plan.query_key,
            _timestamp(search_slice.end_at, "slice end"),
            timestamp,
        )

    def skip_profile_to_now(
        self,
        profile: ResearchProfile,
        now: datetime,
        queries: Optional[tuple[ResearchQuery, ...]] = None,
    ) -> tuple[ResearchSearchStateRecord, ...]:
        timestamp = _timestamp(now, "now")
        active_queries = queries if queries is not None else self.query_builder.build(profile)
        specs = tuple(
            (query.lens_id, provider, query.query_key, query.text)
            for query in active_queries
            for provider in profile.providers.discovery
        )
        return self.repository.skip_profile_to_now(profile.id, specs, timestamp)


def _slice_range(
    start: datetime,
    end: datetime,
    slice_days: int,
) -> tuple[ResearchSearchSlice, ...]:
    duration = timedelta(days=slice_days)
    slices = []
    cursor = start
    while cursor < end:
        next_cursor = min(cursor + duration, end)
        slices.append(ResearchSearchSlice(cursor, next_cursor))
        cursor = next_cursor
    return tuple(slices)


def _validate_scheduled_slice(
    plan: ResearchSearchPlan, search_slice: ResearchSearchSlice
) -> None:
    if plan.manual:
        raise ValueError("Manual searches do not update scheduled watermarks")
    if plan.watermark_skip_required:
        raise ValueError("A from_now plan must be applied through skip_profile_to_now")
    if search_slice not in plan.slices:
        raise ValueError("Search slice does not belong to this Research plan")


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(label))
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime, label: str) -> str:
    return _as_utc(value, label).isoformat()


def _parse_stored_timestamp(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")), "stored watermark")
    except (ValueError, TypeError) as error:
        raise ValueError("Stored Research watermark is not a valid UTC timestamp") from error
