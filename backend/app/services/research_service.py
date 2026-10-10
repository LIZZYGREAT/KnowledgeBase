"""Single-profile Research pipeline with durable run and watermark boundaries."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence
import uuid

from backend.app.domain.research import ResearchLens, ResearchProfile
from backend.app.domain.runtime import Draft
from backend.app.domain.research_runtime import (
    ResearchContextPack,
    ResearchRunRequestRecord,
    ResearchRunRecord,
    ResearchRunStatus,
    ResearchWorkRecord,
)
from backend.app.domain.term_runtime import (
    TermCandidateEvidenceInput,
    TermDiscoveryAssessment,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.repositories.research_run_repository import (
    ResearchProfileStateRepository,
    ResearchRunRepository,
)
from backend.app.repositories.research_run_request_repository import (
    ResearchRunRequestRepository,
)
from backend.app.repositories.research_control_event_repository import (
    ResearchControlEventRepository,
)
from backend.app.repositories.research_search_repository import ResearchSearchRepository
from backend.app.services.ai_client import AIGatewayError
from backend.app.services.research_analysis_service import (
    ResearchAnalysisCircuitBreaker,
    ResearchAnalysisService,
)
from backend.app.services.term_candidate_service import TermCandidateConflict
from backend.app.services.research_candidate_service import ResearchCandidateService
from backend.app.services.research_context_builder import ResearchContextBuilder
from backend.app.services.research_deduplicator import (
    ResearchDeduplicator,
    ResearchIdentityConflict,
    normalize_identifiers,
)
from backend.app.services.research_profile_registry import ResearchProfileRegistry
from backend.app.services.research_providers.base import (
    ProviderPage,
    ProviderWork,
    ResearchProvider,
    ResearchProviderError,
)
from backend.app.services.research_screening import ResearchScreeningService
from backend.app.services.research_query_builder import ResearchQuery, ResearchQueryBuilder
from backend.app.services.research_watermark import (
    ResearchSearchPlan,
    ResearchSearchSlice,
    ResearchWatermarkService,
    ResumeStrategy,
)
from backend.app.services.research_lock import GlobalResearchLock
from backend.app.services.source_registry import SourceRegistry
from backend.app.services.markdown_parser import parse_yaml
from backend.app.services.research_history import research_anchor_year, historical_plan


MAX_ANALYSIS_BACKLOG_PER_RUN = 10
MAX_ANALYSIS_BACKLOG_PAGE_SIZE = 100
_LENS_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_BACKLOG_SEARCH_SLICE = ResearchSearchSlice(
    datetime.min.replace(tzinfo=timezone.utc),
    datetime.max.replace(tzinfo=timezone.utc),
)


@dataclass
class _SearchStream:
    order: int
    query: ResearchQuery
    lens: ResearchLens
    provider_name: str
    provider: ResearchProvider
    plan: ResearchSearchPlan
    slice_index: int = 0
    cursor: Optional[str] = None
    seen_cursors: set[str] = field(default_factory=set)
    attempt_marked: bool = False
    complete_after_round: bool = False
    identity_conflict_seen: bool = False
    active: bool = True

    @property
    def search_slice(self) -> ResearchSearchSlice:
        return self.plan.slices[self.slice_index]


@dataclass(frozen=True)
class _RankedWork:
    work_id: str
    query: ResearchQuery
    lens: ResearchLens
    discovery_provider: str
    score: float
    order: tuple[int, int]
    backlog: bool = False


class ResearchService:
    """Own end-to-end run decisions; repositories and provider adapters own IO details."""

    def __init__(
        self,
        repository_root: Path,
        connection,
        profile_registry: ResearchProfileRegistry,
        providers: Mapping[str, ResearchProvider],
        context_builder: ResearchContextBuilder,
        analysis_service: ResearchAnalysisService,
        candidate_service: ResearchCandidateService,
        source_registry: Optional[SourceRegistry] = None,
        global_lock: Optional[GlobalResearchLock] = None,
        clock=lambda: datetime.now(timezone.utc),
        id_factory=lambda: str(uuid.uuid4()),
        stale_run_after: timedelta = timedelta(minutes=45),
        provider_failure_threshold: int = 3,
        term_candidate_service=None,
    ):
        if provider_failure_threshold < 1:
            raise ValueError("provider_failure_threshold must be positive")
        if stale_run_after <= timedelta(0):
            raise ValueError("stale_run_after must be positive")
        self.repository_root = Path(repository_root).resolve()
        self.connection = connection
        self.profile_registry = profile_registry
        self.providers = dict(providers)
        self.context_builder = context_builder
        self.analysis_service = analysis_service
        self.candidate_service = candidate_service
        self.term_candidate_service = term_candidate_service
        self.work_repository = ResearchRepository(connection)
        self.search_repository = ResearchSearchRepository(connection)
        self.run_repository = ResearchRunRepository(connection)
        self.run_request_repository = ResearchRunRequestRepository(connection)
        self.control_event_repository = ResearchControlEventRepository(connection)
        self.profile_state_repository = ResearchProfileStateRepository(connection)
        self.candidate_repository = candidate_service.repository
        self.query_builder = ResearchQueryBuilder()
        self.watermarks = ResearchWatermarkService(self.search_repository, self.query_builder)
        self.deduplicator = ResearchDeduplicator(
            self.work_repository, clock=clock, id_factory=id_factory
        )
        if source_registry is None:
            source_registry = SourceRegistry.load(
                self.repository_root / "knowledge" / "sources"
            )
        self.screening = ResearchScreeningService(self.work_repository, source_registry)
        self.global_lock = global_lock or GlobalResearchLock(
            self.repository_root / "runtime" / "research.lock"
        )
        self.clock = clock
        self.id_factory = id_factory
        self.stale_run_after = stale_run_after
        self.provider_failure_threshold = provider_failure_threshold

    def refresh_canonical_state(
        self, published_drafts: Sequence[Draft] = ()
    ) -> None:
        if published_drafts and not any(
            draft.entity_type in {"source", "research_profile"}
            for draft in published_drafts
        ):
            return
        profile_registry = ResearchProfileRegistry.load(self.repository_root)
        source_registry = SourceRegistry.load(
            self.repository_root / "knowledge" / "sources"
        )
        self.profile_registry = profile_registry
        self.screening.sources = source_registry

    def run_profile(
        self,
        profile_id: str,
        trigger: str = "scheduled",
        request_id: Optional[str] = None,
        manual_range: Optional[tuple[datetime, datetime]] = None,
        lens_overrides: Optional[Mapping[str, bool]] = None,
        resume_strategy: ResumeStrategy = "all",
        additional_queries: tuple[str, ...] = (),
        additional_query_lens: Optional[str] = None,
        breadth_override: Optional[str] = None,
        catchup_days_override: Optional[int] = None,
        manual_incremental: bool = False,
    ) -> Optional[ResearchRunRecord]:
        if trigger not in {"scheduled", "manual"}:
            raise ValueError("Research Run trigger must be scheduled or manual")
        if manual_range is not None and trigger != "manual":
            raise ValueError("Manual historical ranges require a manual Research Run")
        if manual_incremental and trigger != "manual":
            raise ValueError("Manual incremental search requires a manual Research Run")
        if manual_incremental and manual_range is not None:
            raise ValueError("Manual incremental and historical ranges cannot be combined")
        if manual_incremental and resume_strategy != "all":
            raise ValueError("Manual incremental search uses the scheduled watermark window")
        if not self.global_lock.try_acquire():
            return None
        try:
            now = self._now()
            self.run_repository.mark_stale_interrupted(
                now - self.stale_run_after, now
            )
            return self._run_profile_locked(
                profile_id=profile_id,
                trigger=trigger,
                request_id=request_id,
                manual_range=manual_range,
                lens_overrides=lens_overrides,
                resume_strategy=resume_strategy,
                now=now,
                additional_queries=additional_queries,
                additional_query_lens=additional_query_lens,
                breadth_override=breadth_override,
                catchup_days_override=catchup_days_override,
                manual_incremental=manual_incremental,
            )
        finally:
            self.global_lock.release()

    def now(self) -> datetime:
        return self._now()

    def parse_profile_candidate(self, profile_id: str, content: str) -> ResearchProfile:
        if not isinstance(content, str):
            raise ValueError("Research Profile Draft content must be text")
        candidate = ResearchProfile.model_validate(parse_yaml(content))
        if candidate.id != profile_id:
            raise ValueError("Research Profile Draft id does not match its target")
        profile_path = (
            self.repository_root
            / "config"
            / "research"
            / "profiles"
            / "{}.yaml".format(profile_id)
        )
        ResearchProfileRegistry.validate_candidate(
            self.repository_root, candidate, profile_path
        )
        return candidate

    def pause_profile(
        self, profile_id: str, paused_until: datetime, now: Optional[datetime] = None
    ):
        if self.profile_registry.get(profile_id) is None:
            raise LookupError("Research Profile '{}' does not exist".format(profile_id))
        timestamp = self._now() if now is None else _aware_utc(now, "now")
        until = _aware_utc(paused_until, "paused_until")
        if until <= timestamp:
            raise ValueError("Research Profile pause time must be in the future")
        with self.work_repository.write_transaction():
            state = self.profile_state_repository.pause_until(profile_id, until, timestamp)
            self.control_event_repository.create(
                profile_id,
                "pause",
                {"paused_until": until.isoformat()},
                timestamp,
            )
        return state

    def resume_profile(
        self,
        profile_id: str,
        strategy: str = "catch_up",
        catchup_days: Optional[int] = None,
        now: Optional[datetime] = None,
    ):
        profile = self.profile_registry.get(profile_id)
        if profile is None:
            raise LookupError("Research Profile '{}' does not exist".format(profile_id))
        if strategy not in {"catch_up", "from_now"}:
            raise ValueError("Research resume strategy must be catch_up or from_now")
        if catchup_days is not None and (
            isinstance(catchup_days, bool)
            or not isinstance(catchup_days, int)
            or catchup_days < 1
        ):
            raise ValueError("catchup_days must be a positive integer")
        if strategy == "from_now" and catchup_days is not None:
            raise ValueError("catchup_days cannot be combined with from_now")
        if strategy == "catch_up" and catchup_days is None:
            catchup_days = profile.search.max_catchup_days
        timestamp = self._now() if now is None else _aware_utc(now, "now")
        with self.work_repository.write_transaction():
            queries = self.query_builder.build(profile)
            if strategy == "from_now":
                self.watermarks.skip_profile_to_now(profile, timestamp, queries)
            elif catchup_days is not None:
                floor = timestamp - timedelta(days=catchup_days)
                self.watermarks.advance_streams_to_floor(
                    profile,
                    floor,
                    queries,
                    recorded_at=timestamp,
                )
            state = self.profile_state_repository.pause_until(
                profile_id, None, timestamp
            )
            self.control_event_repository.create(
                profile_id,
                "resume",
                {"strategy": strategy, "catchup_days": catchup_days},
                timestamp,
            )
        return state

    def queue_manual_run(
        self, profile_id: str, override: Optional[Mapping] = None
    ) -> ResearchRunRequestRecord:
        profile = self.profile_registry.get(profile_id)
        if profile is None:
            raise LookupError("Research Profile '{}' does not exist".format(profile_id))
        normalized_override = dict(override or {})
        options = _manual_request_options(normalized_override, profile)
        queued_at = self._now()
        if not profile.enabled:
            raise ValueError("Research Profile is disabled")
        if (
            profile.ai_analysis.enabled
            and self.candidate_service.remaining_capacity(profile) <= 0
        ):
            raise ValueError("Research Inbox is full")
        if options["additional_query_lens"] is not None:
            normalized_override["additional_query_lens"] = options[
                "additional_query_lens"
            ]
        return self.run_request_repository.enqueue(
            profile_id,
            normalized_override,
            queued_at,
            request_id=self.id_factory(),
        )

    def tick(self) -> Optional[ResearchRunRecord]:
        """Run one queued manual request, otherwise one most-overdue scheduled Profile."""
        if not self.global_lock.try_acquire():
            return None
        try:
            now = self._now()
            stale_before = now - self.stale_run_after
            self.run_repository.mark_stale_interrupted(stale_before, now)
            stale_requests = self.run_request_repository.list_stale_claims(stale_before)
            for stale_request in stale_requests:
                self.run_repository.interrupt_for_request(stale_request.id, now)
            self.run_request_repository.recover_stale_claims(stale_before)

            request = self.run_request_repository.claim_next(now)
            if request is not None:
                try:
                    profile = self.profile_registry.get(request.profile_id)
                    if profile is None:
                        raise LookupError(
                            "Research Profile '{}' does not exist".format(request.profile_id)
                        )
                    options = _manual_request_options(request.override, profile)
                    run = self._run_profile_locked(
                        profile_id=request.profile_id,
                        trigger="manual",
                        request_id=request.id,
                        now=now,
                        **options,
                    )
                    if run is None:
                        raise RuntimeError("Manual Research Run did not produce a Run record")
                except Exception:
                    self.run_request_repository.finish(request.id, "failed", self._now())
                    raise
                status = "failed" if run.status in {"failed", "interrupted"} else "completed"
                self.run_request_repository.finish(request.id, status, self._now())
                return run

            profile = self._most_overdue_profile(now)
            if profile is None:
                return None
            state = self.profile_state_repository.get(profile.id)
            (
                resume_strategy,
                catchup_days_override,
                catchup_effective_at,
            ) = self._scheduled_resume_options(
                profile.id, state
            )
            return self._run_profile_locked(
                profile_id=profile.id,
                trigger="scheduled",
                request_id=None,
                manual_range=None,
                lens_overrides=None,
                resume_strategy=resume_strategy,
                catchup_days_override=catchup_days_override,
                catchup_effective_at=catchup_effective_at,
                now=now,
            )
        finally:
            self.global_lock.release()

    def _most_overdue_profile(self, now: datetime) -> Optional[ResearchProfile]:
        eligible = []
        for profile in self.profile_registry.profiles:
            if (
                not profile.enabled
                or profile.schedule.mode == "manual"
            ):
                continue
            if not any(lens.enabled for lens in profile.lenses):
                continue
            state = self.profile_state_repository.get(profile.id)
            if state is not None and state.paused_until is not None:
                if _parse_timestamp(state.paused_until) > now:
                    continue
            if (
                profile.ai_analysis.enabled
                and self.candidate_service.remaining_capacity(profile) <= 0
            ):
                continue
            latest_scheduled_run = self.run_repository.latest_scheduled_for_profile(
                profile.id
            )
            if (
                latest_scheduled_run is not None
                and latest_scheduled_run.status
                in {"failed", "partial", "interrupted"}
            ):
                last_attempt = _parse_timestamp(latest_scheduled_run.started_at)
                cooldown = timedelta(
                    minutes=(
                        self.profile_registry.global_config.runtime.retry_cooldown_minutes
                    )
                )
                retry_after = last_attempt + cooldown
                if now < retry_after:
                    continue
            interval = timedelta(days=1 if profile.schedule.mode == "daily" else 7)
            last_success = (
                _parse_timestamp(state.last_successful_scheduled_run_at)
                if state is not None and state.last_successful_scheduled_run_at is not None
                else None
            )
            due_at = last_success + interval if last_success is not None else datetime.min.replace(
                tzinfo=timezone.utc
            )
            if due_at <= now:
                eligible.append((due_at, profile.id, profile))
        if not eligible:
            return None
        return min(eligible, key=lambda item: (item[0], item[1]))[2]

    def _scheduled_resume_options(
        self, profile_id: str, state
    ) -> tuple[str, Optional[int], Optional[datetime]]:
        event = self.control_event_repository.latest_resume(profile_id)
        if event is None:
            return "all", None, None
        last_success = (
            _parse_timestamp(state.last_successful_scheduled_run_at)
            if state is not None and state.last_successful_scheduled_run_at is not None
            else None
        )
        event_at = _parse_timestamp(event["created_at"])
        if last_success is not None and event_at <= last_success:
            return "all", None, None
        payload = event["payload"]
        catchup_days = payload.get("catchup_days")
        if payload.get("strategy") == "catch_up" and catchup_days is not None:
            return "last_window", catchup_days, event_at
        return "all", None, None

    def _run_profile_locked(
        self,
        profile_id: str,
        trigger: str,
        request_id: Optional[str],
        manual_range: Optional[tuple[datetime, datetime]],
        lens_overrides: Optional[Mapping[str, bool]],
        resume_strategy: ResumeStrategy,
        now: datetime,
        additional_queries: tuple[str, ...] = (),
        additional_query_lens: Optional[str] = None,
        breadth_override: Optional[str] = None,
        catchup_days_override: Optional[int] = None,
        catchup_effective_at: Optional[datetime] = None,
        manual_incremental: bool = False,
    ) -> Optional[ResearchRunRecord]:
        if manual_incremental and trigger != "manual":
            raise ValueError("Manual incremental search requires a manual Research Run")
        if manual_incremental and (manual_range is not None or resume_strategy != "all"):
            raise ValueError("Manual incremental search uses the scheduled watermark window")
        canonical_profile = self.profile_registry.get(profile_id)
        if canonical_profile is None:
            raise LookupError("Research Profile '{}' does not exist".format(profile_id))
        profile_hash = self.profile_registry.content_hash(profile_id)
        effective_config = _effective_config(
            canonical_profile,
            lens_overrides,
            manual_range,
            resume_strategy,
            additional_queries,
            breadth_override,
            catchup_days_override,
            additional_query_lens,
            manual_incremental,
        )
        execution_resume_strategy = resume_strategy
        execution_catchup_days_override = catchup_days_override
        execution_catchup_effective_at = catchup_effective_at
        if execution_catchup_effective_at is not None:
            # Resume catch-up already persisted its lower boundary at resume time.
            execution_resume_strategy = "all"
            execution_catchup_days_override = None
            execution_catchup_effective_at = None
        profile = canonical_profile
        profile_updates = {}
        if lens_overrides is not None:
            profile_updates["lenses"] = [
                lens.model_copy(
                    update={"enabled": lens_overrides.get(lens.id, lens.enabled)}
                )
                for lens in profile.lenses
            ]
        if breadth_override is not None:
            profile_updates["search"] = profile.search.model_copy(
                update={"breadth": breadth_override}
            )
        if profile_updates:
            profile = profile.model_copy(update=profile_updates)

        if not profile.enabled:
            return self._create_finished_run(
                profile,
                profile_hash,
                effective_config,
                trigger,
                request_id,
                "skipped_disabled",
                now,
            )
        if trigger == "scheduled" and not self._schedule_due(profile, now):
            return None
        profile_state = self.profile_state_repository.get_or_create(profile.id, now)
        if (
            trigger == "scheduled"
            and profile_state.paused_until is not None
            and _parse_timestamp(profile_state.paused_until) > now
        ):
            return self._create_finished_run(
                profile,
                profile_hash,
                effective_config,
                trigger,
                request_id,
                "skipped_paused",
                now,
            )
        if (
            profile.ai_analysis.enabled
            and self.candidate_service.remaining_capacity(profile) <= 0
        ):
            return self._create_finished_run(
                profile,
                profile_hash,
                effective_config,
                trigger,
                request_id,
                "skipped_inbox_full",
                now,
            )

        queries = self.query_builder.build(
            profile,
            lens_overrides,
            additional_queries,
            additional_query_lens,
        )
        queries = tuple(
            sorted(queries, key=lambda query: _LENS_PRIORITY_ORDER[query.priority])
        )
        run = ResearchRunRecord(
            id=self.id_factory(),
            profile_id=profile.id,
            request_id=request_id,
            trigger=trigger,
            status="running",
            profile_content_hash=profile_hash,
            effective_config=effective_config,
            provider_summary={},
            started_at=now.isoformat(),
        )
        self.run_repository.create(run)

        # The run row is committed before any network or AI call.
        if (
            trigger == "scheduled"
            and execution_resume_strategy == "from_now"
            and manual_range is None
        ):
            self.watermarks.skip_profile_to_now(profile, now, queries)
            return self.run_repository.finish(
                run.id, "success", {}, None, self._now()
            )

        latest_resume = self.control_event_repository.latest_resume(profile.id)
        resume_is_pending = (
            latest_resume is not None
            and (
                profile_state.last_successful_scheduled_run_at is None
                or _parse_timestamp(latest_resume["created_at"])
                > _parse_timestamp(profile_state.last_successful_scheduled_run_at)
            )
        )
        if trigger == "scheduled" and not resume_is_pending:
            self.watermarks.cap_stale_streams_to_max_catchup(
                profile, queries, now
            )

        all_provider_names = tuple(
            dict.fromkeys(
                list(profile.providers.discovery) + list(profile.providers.enrichment)
            )
        )
        stats = _new_stats(all_provider_names)
        discovery_provider_failures = {name: 0 for name in all_provider_names}
        enrichment_provider_failures = {name: 0 for name in all_provider_names}
        unavailable_discovery_providers: set[str] = set()
        unavailable_enrichment_providers: set[str] = set()
        analysis_breaker = ResearchAnalysisCircuitBreaker()
        errors: list[str] = []
        warnings: list[str] = []
        terminal_status: Optional[ResearchRunStatus] = None

        try:
            terminal_status = self._run_search_streams(
                run,
                profile,
                queries,
                now,
                manual_range,
                execution_resume_strategy,
                execution_catchup_days_override,
                execution_catchup_effective_at,
                manual_incremental,
                stats,
                errors,
                warnings,
                discovery_provider_failures,
                unavailable_discovery_providers,
                enrichment_provider_failures,
                unavailable_enrichment_providers,
                analysis_breaker,
            )
            status: ResearchRunStatus = terminal_status or ("partial" if errors else "success")
        except Exception as error:
            errors.append("{}: {}".format(type(error).__name__, str(error)[:240]))
            status = "failed"

        summary = _freeze_stats(stats)
        run_issues = errors + ["Warning: {}".format(warning) for warning in warnings]
        finished = self.run_repository.finish(
            run.id,
            status,
            summary,
            "; ".join(run_issues)[:1_000] or None,
            self._now(),
        )
        if trigger == "scheduled" and status == "success":
            self.profile_state_repository.record_successful_scheduled_run(
                profile.id, _parse_timestamp(finished.finished_at)
            )
        return finished

    def _run_search_streams(
        self,
        run: ResearchRunRecord,
        profile: ResearchProfile,
        queries: Sequence[ResearchQuery],
        now: datetime,
        manual_range: Optional[tuple[datetime, datetime]],
        resume_strategy: ResumeStrategy,
        catchup_days_override: Optional[int],
        catchup_effective_at: Optional[datetime],
        manual_incremental: bool,
        stats: dict,
        errors: list[str],
        warnings: list[str],
        discovery_provider_failures: dict[str, int],
        unavailable_discovery_providers: set[str],
        enrichment_provider_failures: dict[str, int],
        unavailable_enrichment_providers: set[str],
        analysis_breaker: ResearchAnalysisCircuitBreaker,
    ) -> Optional[ResearchRunStatus]:
        streams = []
        stream_order = 0
        anchor = (
            research_anchor_year(self.repository_root, profile, self.screening.sources)
            if (run.trigger == "scheduled" or manual_incremental) and manual_range is None else None
        )
        for query in queries:
            lens = _lens_for(profile, query)
            for provider_name in profile.providers.discovery:
                if provider_name in unavailable_discovery_providers:
                    continue
                provider = self.providers.get(provider_name)
                if provider is None:
                    unavailable_discovery_providers.add(provider_name)
                    errors.append("{}: adapter is not configured".format(provider_name))
                    _provider_stats(stats, provider_name)["errors"] += 1
                    continue
                plan = self.watermarks.build_plan(
                    profile,
                    query,
                    provider_name,
                    now,
                    self.profile_registry.global_config,
                    manual_range=manual_range,
                    resume_strategy=resume_strategy,
                    catchup_days_override=catchup_days_override,
                    catchup_effective_at=catchup_effective_at,
                    manual_incremental=manual_incremental,
                    manual_run=run.trigger == "manual",
                )
                if anchor is not None:
                    history = historical_plan(self.search_repository, profile, query, provider_name, anchor, now)
                    if history.slices:
                        checkpoint = self.search_repository.history_checkpoint(history.profile_id, history.lens_id, history.provider, history.query_key)
                        streams.append(_SearchStream(
                            order=stream_order, query=query, lens=lens,
                            provider_name=provider_name, provider=provider, plan=history,
                            cursor=checkpoint["cursor"] if checkpoint else None,
                        ))
                        stream_order += 1
                if plan.watermark_skip_required or not plan.slices:
                    continue
                streams.append(
                    _SearchStream(
                        order=stream_order,
                        query=query,
                        lens=lens,
                        provider_name=provider_name,
                        provider=provider,
                        plan=plan,
                    )
                )
                stream_order += 1

        # Oldest attempted streams run first, including streams never requested.
        # Keep request order durable even with a fixed or coarse-grained clock.
        attempted = {}
        for stream in streams:
            plan = stream.plan
            state = self.search_repository.get_state(plan.profile_id, plan.lens_id, plan.provider, plan.query_key)
            attempted[stream.order] = datetime.fromisoformat(state.last_attempt_at) if state and state.last_attempt_at else datetime.min.replace(tzinfo=timezone.utc)
        streams.sort(key=lambda stream: (attempted[stream.order], stream.order))
        last_attempt = max(attempted.values(), default=datetime.min.replace(tzinfo=timezone.utc))

        pending_by_work = {}
        identity_conflict_count = 0
        identity_conflict_examples: list[str] = []
        identity_conflict_error_index: Optional[int] = None

        def record_identity_conflict(
            stream: _SearchStream,
            provider_work: ProviderWork,
            error: ResearchIdentityConflict,
        ) -> None:
            nonlocal identity_conflict_count, identity_conflict_error_index
            identity_conflict_count += 1
            stream.identity_conflict_seen = True
            _provider_stats(stats, stream.provider_name)["errors"] += 1
            if len(identity_conflict_examples) < 4:
                identity_conflict_examples.append(
                    _format_identity_conflict_example(
                        profile.id,
                        stream.query.lens_id,
                        stream.provider_name,
                        provider_work,
                        stream.query.query_key,
                        error,
                    )
                )
            summary = _format_identity_conflict_summary(
                identity_conflict_count, identity_conflict_examples
            )
            if identity_conflict_error_index is None:
                identity_conflict_error_index = len(errors)
                errors.append(summary)
            else:
                errors[identity_conflict_error_index] = summary

        backlog_budget = _analysis_backlog_budget(
            profile.search.max_analyses_per_run
        )
        if profile.ai_analysis.enabled:
            backlog_candidates = self._collect_analysis_backlog(
                profile, queries, warnings, backlog_budget
            )
            self._merge_ranked_works(
                pending_by_work,
                backlog_candidates,
                set(),
            )
        else:
            backlog_candidates = []
        processed_work_ids: set[str] = set()
        backlog_attempts = 0
        backlog_attempt_limit = backlog_budget
        request_limit = self.profile_registry.global_config.runtime.discovery_page_size

        while pending_by_work or any(stream.active for stream in streams):
            round_candidates = pending_by_work
            pending_by_work = {}
            budget_reached = False
            for stream in streams:
                if not stream.active:
                    continue
                if stream.provider_name in unavailable_discovery_providers:
                    stream.active = False
                    continue
                if (
                    profile.ai_analysis.enabled
                    and self.candidate_service.remaining_capacity(profile) <= 0
                ):
                    errors.append("Inbox capacity reached before the current search round completed")
                    return "capacity_reached"
                provider_summary = _provider_stats(stats, stream.provider_name)
                if sum(value["requests"] for value in stats.values()) >= profile.search.max_provider_requests_per_run:
                    budget_reached = True
                    break
                if not stream.plan.manual:
                    last_attempt = max(self._now(), last_attempt + timedelta(microseconds=1))
                    self.watermarks.mark_attempt(
                        stream.plan, stream.search_slice, last_attempt
                    )
                    if not stream.attempt_marked and stream.plan.query_key.startswith("history:"):
                        self.search_repository.save_history_checkpoint(stream.plan, stream.search_slice.start_at, stream.cursor)
                    stream.attempt_marked = True
                provider_summary["requests"] += 1
                try:
                    page = stream.provider.search(
                        stream.query.text,
                        stream.search_slice.start_at,
                        stream.search_slice.end_at,
                        stream.cursor,
                        limit=request_limit,
                    )
                except ResearchProviderError as error:
                    provider_summary["errors"] += 1
                    discovery_provider_failures[stream.provider_name] += 1
                    errors.append(
                        "{}: {}".format(stream.provider_name, str(error)[:240])
                    )
                    if (
                        discovery_provider_failures[stream.provider_name]
                        >= self.provider_failure_threshold
                    ):
                        unavailable_discovery_providers.add(stream.provider_name)
                        provider_summary["circuit_open"] = True
                    stream.active = False
                    continue

                discovery_provider_failures[stream.provider_name] = 0
                provider_summary["pages"] += 1
                if not isinstance(page, ProviderPage):
                    errors.append(
                        "{}: adapter returned an invalid page".format(
                            stream.provider_name
                        )
                    )
                    provider_summary["errors"] += 1
                    stream.active = False
                    continue
                if len(page.works) > request_limit:
                    errors.append(
                        "{}: adapter returned more Works than the requested limit".format(
                            stream.provider_name
                        )
                    )
                    provider_summary["errors"] += 1
                    stream.active = False
                    continue
                provider_summary["works"] += len(page.works)
                for index, provider_work in enumerate(page.works):
                    if (
                        profile.ai_analysis.enabled
                        and self.candidate_service.remaining_capacity(profile) <= 0
                    ):
                        errors.append(
                            "Inbox capacity reached before the current search round completed"
                        )
                        return "capacity_reached"
                    self.run_repository.update_progress(run.id, fetched_count=1)
                    if not isinstance(provider_work, ProviderWork):
                        raise ValueError("Provider page contained an invalid Work")
                    try:
                        ingested = self.deduplicator.record_discovery(
                            profile.id,
                            stream.query.lens_id,
                            stream.query.query_key,
                            stream.query.text,
                            provider_work,
                            discovered_at=self._now(),
                        )
                    except ResearchIdentityConflict as error:
                        record_identity_conflict(stream, provider_work, error)
                        continue
                    if ingested.created_work:
                        self.run_repository.update_progress(run.id, new_work_count=1)
                    else:
                        self.run_repository.update_progress(run.id, duplicate_count=1)
                    screened = self.screening.screen(
                        ingested.work,
                        profile,
                        stream.query,
                        stream.search_slice,
                        self._now(),
                    )
                    if "ambiguous_existing_source" in screened.metadata_warnings:
                        warnings.append(
                            "ambiguous_existing_source: Work '{}' was retained because "
                            "its canonical Source identity is ambiguous".format(
                                ingested.work.id
                            )
                        )
                    if not screened.eligible:
                        self.run_repository.update_progress(
                            run.id, deterministic_filtered_count=1
                        )
                        continue
                    if screened.pre_rank is None:
                        raise RuntimeError("Eligible Work is missing its Pre-Rank score")
                    self._merge_ranked_works(
                        round_candidates,
                        [
                            _RankedWork(
                                work_id=ingested.work.id,
                                query=stream.query,
                                lens=stream.lens,
                                discovery_provider=provider_work.provider,
                                score=screened.pre_rank.score,
                                order=(stream.order + 1, index),
                            )
                        ],
                        processed_work_ids,
                    )

                if page.next_cursor is None:
                    stream.complete_after_round = True
                elif page.next_cursor in stream.seen_cursors or page.next_cursor == stream.cursor:
                    errors.append(
                        "{}: pagination cursor did not advance".format(
                            stream.provider_name
                        )
                    )
                    provider_summary["errors"] += 1
                    stream.active = False
                else:
                    stream.seen_cursors.add(page.next_cursor)
                    stream.cursor = page.next_cursor

            ordered_candidates = sorted(
                round_candidates.values(),
                key=lambda item: (not item.backlog, -item.score, item.order),
            )
            for candidate in ordered_candidates:
                if candidate.backlog and backlog_attempts >= backlog_attempt_limit:
                    continue
                attempts_before = self.run_repository.get(
                    run.id
                ).analysis_attempt_count
                complete_work, work_status = self._process_ranked_work(
                    run,
                    profile,
                    candidate,
                    stats,
                    errors,
                    warnings,
                    enrichment_provider_failures,
                    unavailable_enrichment_providers,
                    analysis_breaker,
                )
                if not complete_work:
                    return work_status or "partial"
                processed_work_ids.add(candidate.work_id)
                attempts_after = self.run_repository.get(
                    run.id
                ).analysis_attempt_count
                if candidate.backlog:
                    backlog_attempts += max(0, attempts_after - attempts_before)
                if profile.ai_analysis.enabled and (
                    attempts_after >= profile.search.max_analyses_per_run
                ):
                    warnings.append(
                        "Analysis budget reached; the current search slices remain incomplete and their watermarks were not advanced."
                    )
                    return "partial" if identity_conflict_count else "success"
                if profile.ai_analysis.enabled and (
                    self.run_repository.get(run.id).surfaced_count
                    >= profile.search.max_candidates_per_run
                ):
                    warnings.append(
                        "Candidate budget reached; the current search slices remain incomplete and their watermarks were not advanced."
                    )
                    return "partial" if identity_conflict_count else "success"
                if profile.ai_analysis.enabled and self.candidate_service.remaining_capacity(profile) <= 0:
                    errors.append("Inbox capacity reached before the next search round")
                    return "capacity_reached"

            current_run = self.run_repository.get(run.id)
            if profile.ai_analysis.enabled and (
                current_run.analysis_attempt_count >= profile.search.max_analyses_per_run
            ):
                warnings.append(
                    "Analysis budget reached; the current search slices remain incomplete and their watermarks were not advanced."
                )
                return "success"
            if profile.ai_analysis.enabled and (
                current_run.surfaced_count >= profile.search.max_candidates_per_run
            ):
                warnings.append(
                    "Candidate budget reached; the current search slices remain incomplete and their watermarks were not advanced."
                )
                return "success"
            if profile.ai_analysis.enabled and self.candidate_service.remaining_capacity(profile) <= 0:
                errors.append("Inbox capacity reached before the next search round")
                return "capacity_reached"

            for stream in streams:
                if stream.active and stream.attempt_marked and not stream.identity_conflict_seen and stream.plan.query_key.startswith("history:"):
                    self.search_repository.save_history_checkpoint(stream.plan, stream.search_slice.start_at, stream.cursor)
                if not stream.complete_after_round:
                    continue
                if stream.identity_conflict_seen:
                    stream.active = False
                    continue
                if not stream.plan.manual:
                    self.watermarks.complete_slice(
                        stream.plan, stream.search_slice, self._now()
                    )
                    if stream.plan.query_key.startswith("history:"):
                        self.search_repository.save_history_checkpoint(stream.plan, None, None)
                stream.slice_index += 1
                stream.cursor = None
                stream.seen_cursors.clear()
                stream.attempt_marked = False
                stream.complete_after_round = False
                stream.identity_conflict_seen = False
                if stream.slice_index >= len(stream.plan.slices):
                    stream.active = False
            if budget_reached:
                warnings.append("Provider request budget reached; fetched pages were processed and unfinished windows will resume.")
                return "partial"
        return None

    def _collect_analysis_backlog(
        self,
        profile: ResearchProfile,
        queries: Sequence[ResearchQuery],
        warnings: list[str],
        max_candidates: int,
    ) -> list[_RankedWork]:
        if max_candidates <= 0:
            return []
        query_by_key = {query.query_key: query for query in queries}
        query_keys = tuple(query_by_key)
        backlog = []
        after = None
        scanned = 0
        while len(backlog) < max_candidates:
            page = self.work_repository.list_pending_discoveries(
                profile.id,
                query_keys,
                MAX_ANALYSIS_BACKLOG_PAGE_SIZE,
                after=after,
                min_profile_relevance=profile.search.min_profile_relevance,
                min_information_gain=profile.search.min_information_gain,
            )
            if not page:
                break
            for discovery in page:
                after = (discovery.discovered_at, discovery.id)
                query = query_by_key.get(discovery.query_key)
                work = self.work_repository.get_work(discovery.work_id)
                index = scanned
                scanned += 1
                if query is None or work is None:
                    continue
                lens = _lens_for(profile, query)
                screened = self.screening.screen(
                    work, profile, query, _BACKLOG_SEARCH_SLICE, self._now()
                )
                if "ambiguous_existing_source" in screened.metadata_warnings:
                    warnings.append(
                        "ambiguous_existing_source: Work '{}' was retained because "
                        "its canonical Source identity is ambiguous".format(work.id)
                    )
                if not screened.eligible or screened.pre_rank is None:
                    continue
                backlog.append(
                    _RankedWork(
                        work_id=work.id,
                        query=query,
                        lens=lens,
                        discovery_provider=discovery.provider,
                        score=screened.pre_rank.score,
                        order=(0, index),
                        backlog=True,
                    )
                )
                if len(backlog) >= max_candidates:
                    break
            if len(page) < MAX_ANALYSIS_BACKLOG_PAGE_SIZE:
                break
        return backlog

    @staticmethod
    def _merge_ranked_works(
        target: dict[str, _RankedWork],
        candidates: Sequence[_RankedWork],
        processed_work_ids: set[str],
    ) -> None:
        for candidate in candidates:
            if candidate.work_id in processed_work_ids:
                continue
            current = target.get(candidate.work_id)
            if current is None:
                target[candidate.work_id] = candidate
                continue
            selected = (
                candidate
                if (-candidate.score, candidate.order)
                < (-current.score, current.order)
                else current
            )
            if current.backlog or candidate.backlog:
                selected = replace(selected, backlog=True)
            target[candidate.work_id] = selected

    def _process_ranked_work(
        self,
        run: ResearchRunRecord,
        profile: ResearchProfile,
        candidate: _RankedWork,
        stats: dict,
        errors: list[str],
        warnings: list[str],
        enrichment_provider_failures: dict[str, int],
        unavailable_enrichment_providers: set[str],
        analysis_breaker: ResearchAnalysisCircuitBreaker,
    ) -> tuple[bool, Optional[ResearchRunStatus]]:
        work = self.work_repository.get_work(candidate.work_id)
        if work is None:
            return True, None
        if not profile.ai_analysis.enabled:
            enriched_work = self._enrich_work(
                work,
                profile,
                stats,
                candidate.discovery_provider,
                warnings,
                enrichment_provider_failures,
                unavailable_enrichment_providers,
            )
            self._post_enrichment_check(
                run, work, enriched_work, profile, candidate.query, warnings
            )
            return True, None

        current_run = self.run_repository.get(run.id)
        if current_run.analysis_attempt_count >= profile.search.max_analyses_per_run:
            return False, "success"
        if current_run.surfaced_count >= profile.search.max_candidates_per_run:
            return False, "success"
        if self.candidate_service.remaining_capacity(profile) <= 0:
            errors.append("Inbox capacity reached before the candidate could be analyzed")
            return False, "capacity_reached"

        original_work = work
        work = self._enrich_work(
            work,
            profile,
            stats,
            candidate.discovery_provider,
            warnings,
            enrichment_provider_failures,
            unavailable_enrichment_providers,
        )
        if not self._post_enrichment_check(
            run, original_work, work, profile, candidate.query, warnings
        ):
            return True, None

        context_pack = self.context_builder.build(
            work,
            profile,
            candidate.lens,
            keywords=(candidate.query.text,),
        )
        analysis_hash = self.analysis_service.input_hash(
            work, profile, candidate.lens, context_pack
        )
        analysis = self.work_repository.get_analysis(
            work.id, profile.id, analysis_hash
        )
        if analysis is None:
            if analysis_breaker.analysis_disabled_for_run:
                errors.append("DeepSeek analysis circuit opened for this run")
                return False, "partial"
            analysis_attempted = False

            def record_analysis_attempt():
                nonlocal analysis_attempted
                self.run_repository.update_progress(
                    run.id, analysis_attempt_count=1
                )
                analysis_attempted = True

            try:
                analysis = self.analysis_service.analyze(
                    work,
                    profile,
                    candidate.lens,
                    context_pack,
                    circuit_breaker=analysis_breaker,
                    on_attempt=record_analysis_attempt,
                )
            except AIGatewayError as error:
                errors.append("DeepSeek: {}".format(str(error)[:240]))
                return False, "partial"
            if analysis_attempted and analysis is not None:
                self.run_repository.update_progress(run.id, analyzed_count=1)
        if analysis is None:
            if analysis_breaker.analysis_disabled_for_run:
                errors.append("DeepSeek analysis circuit opened for this run")
                return False, "partial"
            return True, None

        generated = self.candidate_service.generate(
            analysis, profile, candidate.lens
        )
        if generated.outcome == "inbox_full":
            errors.append("Inbox capacity reached before the candidate could be saved")
            return False, "capacity_reached"
        if generated.outcome == "budget_reached":
            warnings.append("Daily recommendation exposure budget reached; analyzed Works remain saved for a later Run.")
            return False, "success"
        if generated.outcome in {"created", "existing"}:
            self._store_research_term_candidates(analysis, work, warnings)
        if generated.outcome == "created":
            self.run_repository.update_progress(run.id, surfaced_count=1)
            if self.candidate_service.remaining_capacity(profile) <= 0:
                errors.append("Inbox capacity reached before the next search round")
                return False, "capacity_reached"
        return True, None

    def _store_research_term_candidates(self, analysis, work, warnings):
        if self.term_candidate_service is None:
            return
        for suggestion in analysis.analysis.term_candidates:
            evidence = TermCandidateEvidenceInput(
                origin_type="research_work",
                origin_id=work.id,
                mention=suggestion.mention,
                context_excerpt=suggestion.context_excerpt,
                confidence=suggestion.confidence,
                rationale=suggestion.rationale,
            )
            assessment = TermDiscoveryAssessment(
                readiness=suggestion.readiness,
                recommendation_level=suggestion.recommendation_level,
                known_prerequisites=suggestion.known_prerequisites,
                missing_prerequisites=suggestion.missing_prerequisites,
                why_now=suggestion.why_now,
            )
            try:
                self.term_candidate_service.create_candidate(
                    suggestion.mention,
                    suggestion.term_type,
                    [evidence],
                    preferred_term_id=suggestion.existing_term_id,
                    discovery_assessment=assessment,
                )
            except TermCandidateConflict:
                # A scoped or global Term rejection affects only this Term origin;
                # it never changes the independently reviewed Research Candidate.
                continue
            except ValueError as error:
                warnings.append(
                    "Term Candidate '{}' was skipped: {}".format(
                        suggestion.mention, str(error)[:180]
                    )
                )

    def _post_enrichment_check(
        self,
        run: ResearchRunRecord,
        original_work: ResearchWorkRecord,
        enriched_work: ResearchWorkRecord,
        profile: ResearchProfile,
        query: ResearchQuery,
        warnings: list[str],
    ) -> bool:
        if _screening_metadata_signature(original_work) == _screening_metadata_signature(
            enriched_work
        ):
            return True
        decision = self.screening.post_enrichment_check(enriched_work, profile, query)
        if "ambiguous_existing_source" in decision.metadata_warnings:
            warning = (
                "ambiguous_existing_source: Work '{}' was retained because "
                "its canonical Source identity is ambiguous".format(enriched_work.id)
            )
            if warning not in warnings:
                warnings.append(warning)
        if decision.eligible:
            return True
        self.run_repository.update_progress(run.id, deterministic_filtered_count=1)
        return False

    def _enrich_work(
        self,
        work: ResearchWorkRecord,
        profile: ResearchProfile,
        stats: dict,
        discovery_provider: str,
        warnings: list[str],
        provider_failures: dict[str, int],
        unavailable_providers: set[str],
    ) -> ResearchWorkRecord:
        enriched_work = work
        for provider_name in profile.providers.enrichment:
            if provider_name in unavailable_providers:
                continue
            if provider_name == discovery_provider:
                continue
            if provider_name == "crossref" and not enriched_work.doi:
                continue
            if provider_name == "openalex" and not _needs_openalex_enrichment(
                enriched_work
            ):
                continue
            provider = self.providers.get(provider_name)
            enrich = getattr(provider, "enrich", None) if provider is not None else None
            summary = _provider_stats(stats, provider_name)
            if not callable(enrich):
                summary["errors"] += 1
                warnings.append(
                    "{} enrichment adapter is not configured".format(provider_name)
                )
                provider_failures[provider_name] = self.provider_failure_threshold
                unavailable_providers.add(provider_name)
                continue
            if sum(value["requests"] for value in stats.values()) >= profile.search.max_provider_requests_per_run:
                warnings.append("Provider request budget reached; metadata enrichment deferred.")
                break
            summary["requests"] += 1
            try:
                enriched = enrich(enriched_work)
            except ResearchProviderError as error:
                summary["errors"] += 1
                provider_failures[provider_name] += 1
                detail = str(error)
                prefix = "{}: ".format(provider_name)
                if detail.startswith(prefix):
                    detail = detail[len(prefix) :]
                warnings.append(
                    "{} enrichment: {}".format(provider_name, detail[:220])
                )
                if provider_failures[provider_name] >= self.provider_failure_threshold:
                    summary["circuit_open"] = True
                    unavailable_providers.add(provider_name)
                continue
            provider_failures[provider_name] = 0
            if enriched is None:
                continue
            if not isinstance(enriched, ProviderWork):
                summary["errors"] += 1
                warnings.append(
                    "{} enrichment returned an invalid Work".format(provider_name)
                )
                unavailable_providers.add(provider_name)
                continue
            try:
                enriched_work = self.deduplicator.enrich_existing_work(
                    enriched_work.id, enriched
                )
            except ResearchIdentityConflict as error:
                summary["errors"] += 1
                warnings.append(
                    "{} enrichment identity conflict; existing Work was retained: {}".format(
                        provider_name, str(error)[:180]
                    )
                )
                continue
            except (LookupError, ValueError) as error:
                summary["errors"] += 1
                warnings.append(
                    "{} enrichment could not be applied: {}".format(
                        provider_name, str(error)[:220]
                    )
                )
                unavailable_providers.add(provider_name)
                continue
            summary["works"] += 1
        return enriched_work

    def _create_finished_run(
        self,
        profile: ResearchProfile,
        profile_hash: str,
        effective_config: dict,
        trigger: str,
        request_id: Optional[str],
        status: ResearchRunStatus,
        now: datetime,
    ) -> ResearchRunRecord:
        run = ResearchRunRecord(
            id=self.id_factory(),
            profile_id=profile.id,
            request_id=request_id,
            trigger=trigger,
            status=status,
            profile_content_hash=profile_hash,
            effective_config=effective_config,
            provider_summary={},
            started_at=now.isoformat(),
            finished_at=now.isoformat(),
        )
        return self.run_repository.create(run)

    def _schedule_due(self, profile: ResearchProfile, now: datetime) -> bool:
        if profile.schedule.mode == "manual":
            return False
        state = self.profile_state_repository.get(profile.id)
        if state is None or state.last_successful_scheduled_run_at is None:
            return True
        last_run = _parse_timestamp(state.last_successful_scheduled_run_at)
        interval = timedelta(days=1 if profile.schedule.mode == "daily" else 7)
        return now - last_run >= interval

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Research clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


def _effective_config(
    profile: ResearchProfile,
    lens_overrides: Optional[Mapping[str, bool]],
    manual_range: Optional[tuple[datetime, datetime]],
    resume_strategy: ResumeStrategy,
    additional_queries: tuple[str, ...] = (),
    breadth_override: Optional[str] = None,
    catchup_days_override: Optional[int] = None,
    additional_query_lens: Optional[str] = None,
    manual_incremental: bool = False,
) -> dict:
    return {
        "profile": profile.model_dump(mode="json"),
        "lens_overrides": dict(lens_overrides or {}),
        "manual_range": (
            [manual_range[0].isoformat(), manual_range[1].isoformat()]
            if manual_range is not None
            else None
        ),
        "resume_strategy": resume_strategy,
        "additional_queries": list(additional_queries),
        "additional_query_lens": additional_query_lens,
        "manual_incremental": manual_incremental,
        "breadth_override": breadth_override,
        "catchup_days_override": catchup_days_override,
    }


def _new_stats(providers: tuple[str, ...]) -> dict:
    return {
        name: {"requests": 0, "pages": 0, "works": 0, "errors": 0, "circuit_open": False}
        for name in providers
    }


def _provider_stats(stats: dict, provider: str) -> dict:
    return stats.setdefault(
        provider,
        {"requests": 0, "pages": 0, "works": 0, "errors": 0, "circuit_open": False},
    )


def _format_identity_conflict_example(
    profile_id: str,
    lens_id: str,
    provider_name: str,
    provider_work: ProviderWork,
    query_key: str,
    error: ResearchIdentityConflict,
) -> str:
    identifiers = normalize_identifiers(provider_work)
    identity_text = ",".join(
        "{}={}".format(name, _diagnostic_value(value, 38))
        for name, value in identifiers.items()
        if value is not None
    ) or "none"
    matched_ids = ",".join(
        _diagnostic_value(work_id, 36) for work_id in error.matched_work_ids[:3]
    ) or "unknown"
    if len(error.matched_work_ids) > 3:
        matched_ids += ",..."
    return (
        "profile={} lens={} provider={} record={} query={} ids={} reason={} works={}"
    ).format(
        _diagnostic_value(profile_id, 36),
        _diagnostic_value(lens_id, 36),
        _diagnostic_value(provider_name, 20),
        _diagnostic_value(provider_work.provider_record_id, 48),
        _diagnostic_value(query_key, 44),
        identity_text,
        _diagnostic_value(error.reason, 64),
        matched_ids,
    )


def _format_identity_conflict_summary(count: int, examples: list[str]) -> str:
    prefix = "Research identity conflicts count={}: ".format(count)
    selected = []
    for example in examples:
        candidate = prefix + " | ".join(selected + [example])
        omitted = count - len(selected) - 1
        if omitted > 0:
            candidate += " | additional conflicts={}".format(omitted)
        if len(candidate) > 940:
            break
        selected.append(example)
    summary = prefix + " | ".join(selected)
    omitted = count - len(selected)
    if omitted > 0:
        summary += " | additional conflicts={}".format(omitted)
    return summary[:940]


def _diagnostic_value(value, limit: int) -> str:
    if value is None:
        return "-"
    compact = " ".join(str(value).split())
    return compact[:limit] or "-"


def _needs_openalex_enrichment(work: ResearchWorkRecord) -> bool:
    if not (work.openalex_id or work.doi):
        return False
    return any(
        (
            not (work.abstract and work.abstract.strip()),
            not work.authors,
            work.year is None and work.published_at is None,
            not work.venue,
            not work.url,
        )
    )


def _analysis_backlog_budget(max_analyses_per_run: int) -> int:
    if max_analyses_per_run <= 0:
        return 0
    return min(MAX_ANALYSIS_BACKLOG_PER_RUN, max(1, max_analyses_per_run // 3))


def _screening_metadata_signature(work: ResearchWorkRecord) -> tuple:
    return (
        work.title,
        work.abstract,
        work.authors,
        work.year,
        work.published_at,
        work.doi,
        work.arxiv_id,
        work.openalex_id,
        work.semantic_scholar_id,
    )


def _freeze_stats(stats: dict) -> dict:
    return {name: dict(values) for name, values in sorted(stats.items())}


def _lens_for(profile: ResearchProfile, query: ResearchQuery):
    lens = next((item for item in profile.lenses if item.id == query.lens_id), None)
    if lens is None:
        raise ValueError("Research Query references an unknown Lens")
    return lens


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Research Runtime timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _aware_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Research {} must be timezone-aware".format(label))
    return value.astimezone(timezone.utc)


def _manual_request_options(override: Mapping, profile: ResearchProfile) -> dict:
    if not isinstance(override, Mapping):
        raise ValueError("Manual Research Run override must be an object")
    allowed = {
        "lens_overrides",
        "manual_range",
        "manual_incremental",
        "resume_strategy",
        "breadth",
        "additional_queries",
        "additional_query_lens",
    }
    unexpected = set(override) - allowed
    if unexpected:
        raise ValueError(
            "Unsupported Manual Research Run override field(s): {}".format(
                ", ".join(sorted(str(key) for key in unexpected))
            )
        )

    lens_overrides = override.get("lens_overrides")
    if lens_overrides is not None:
        if not isinstance(lens_overrides, Mapping):
            raise ValueError("lens_overrides must map Lens ids to booleans")
        known_lenses = {lens.id for lens in profile.lenses}
        if set(lens_overrides) - known_lenses:
            raise ValueError("Manual Research Run contains an unknown Lens id")
        if any(type(enabled) is not bool for enabled in lens_overrides.values()):
            raise ValueError("lens_overrides values must be booleans")
        lens_overrides = dict(lens_overrides)

    manual_range_value = override.get("manual_range")
    manual_range = None
    if manual_range_value is not None:
        if not isinstance(manual_range_value, (tuple, list)) or len(manual_range_value) != 2:
            raise ValueError("manual_range must contain start and end timestamps")
        manual_range = tuple(
            _parse_override_datetime(value) for value in manual_range_value
        )
        if manual_range[0] >= manual_range[1]:
            raise ValueError("Manual Research Run range must end after it starts")

    manual_incremental = override.get("manual_incremental", False)
    if type(manual_incremental) is not bool:
        raise ValueError("manual_incremental must be a boolean")
    if manual_incremental and manual_range is not None:
        raise ValueError("Manual incremental and historical ranges cannot be combined")

    resume_strategy = override.get("resume_strategy", "all")
    if resume_strategy not in {"all", "from_now"}:
        raise ValueError("resume_strategy must be 'all' or 'from_now'")
    if manual_range is not None and resume_strategy != "all":
        raise ValueError("Resume strategy does not apply to manual historical searches")
    if manual_incremental and resume_strategy != "all":
        raise ValueError("Manual incremental search uses the scheduled watermark window")
    breadth = override.get("breadth")
    if breadth is not None and breadth not in {"strict", "balanced", "explore"}:
        raise ValueError("breadth must be strict, balanced, or explore")
    additional_queries = override.get("additional_queries", ())
    if not isinstance(additional_queries, (list, tuple)) or len(additional_queries) > 20:
        raise ValueError("additional_queries must contain at most 20 query strings")
    normalized_queries = []
    for query in additional_queries:
        if not isinstance(query, str) or not query.strip() or len(query) > 2_000:
            raise ValueError("additional_queries entries must be text up to 2000 characters")
        normalized_queries.append(query.strip())
    additional_query_lens = override.get("additional_query_lens")
    if additional_query_lens is not None and not isinstance(additional_query_lens, str):
        raise ValueError("additional_query_lens must be a Lens id")
    if normalized_queries:
        selected_lenses = [
            lens
            for lens in profile.lenses
            if (lens_overrides or {}).get(lens.id, lens.enabled)
        ]
        if not selected_lenses:
            raise ValueError("Additional Research queries require a selected Lens")
        selected_lens_ids = {lens.id for lens in selected_lenses}
        if additional_query_lens is None:
            if len(selected_lenses) > 1:
                raise ValueError(
                    "Additional Research queries require an explicit Lens when multiple Lenses are selected"
                )
            additional_query_lens = selected_lenses[0].id
        elif additional_query_lens not in selected_lens_ids:
            raise ValueError(
                "Additional Research query Lens must be one of the selected Lenses"
            )
    elif additional_query_lens is not None:
        raise ValueError("additional_query_lens requires additional_queries")
    return {
        "manual_range": manual_range,
        "manual_incremental": manual_incremental,
        "lens_overrides": lens_overrides,
        "resume_strategy": resume_strategy,
        "additional_queries": tuple(normalized_queries),
        "additional_query_lens": additional_query_lens,
        "breadth_override": breadth,
        "catchup_days_override": None,
    }


def _parse_override_datetime(value) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Manual Research Run timestamps must be non-empty text")
    if len(value) == 10:
        try:
            return datetime.combine(
                datetime.strptime(value, "%Y-%m-%d").date(),
                datetime.min.time(),
                timezone.utc,
            )
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Manual Research Run range contains an invalid timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Manual Research Run timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)
