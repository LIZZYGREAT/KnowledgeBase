"""Single-profile Research pipeline with durable run and watermark boundaries."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional, Sequence
import uuid

from backend.app.domain.research import ResearchProfile
from backend.app.domain.runtime import Draft
from backend.app.domain.research_runtime import (
    ResearchContextPack,
    ResearchRunRequestRecord,
    ResearchRunRecord,
    ResearchRunStatus,
    ResearchWorkRecord,
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
from backend.app.services.research_candidate_service import ResearchCandidateService
from backend.app.services.research_context_builder import ResearchContextBuilder
from backend.app.services.research_deduplicator import ResearchDeduplicator
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
    ResearchWatermarkService,
    ResumeStrategy,
)
from backend.app.services.research_lock import GlobalResearchLock
from backend.app.services.source_registry import SourceRegistry
from backend.app.services.markdown_parser import parse_yaml


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

    def reactivation_review(self, candidate: ResearchProfile) -> dict:
        current = self.profile_registry.get(candidate.id)
        if current is None:
            return {
                "required": False,
                "triggers": [],
                "max_catchup_days": candidate.search.max_catchup_days,
                "strategies": [],
            }

        triggers = []
        if not current.enabled and candidate.enabled:
            triggers.append("profile_enabled")
        if not current.ai_analysis.enabled and candidate.ai_analysis.enabled:
            triggers.append("ai_analysis_enabled")
        current_lenses = {lens.id: lens for lens in current.lenses}
        for lens in candidate.lenses:
            previous = current_lenses.get(lens.id)
            if lens.enabled and (previous is None or not previous.enabled):
                triggers.append("lens_enabled:{}".format(lens.id))
        current_discovery = set(current.providers.discovery)
        for provider in candidate.providers.discovery:
            if provider not in current_discovery:
                triggers.append("provider_enabled:{}".format(provider))
        if current.schedule.mode == "manual" and candidate.schedule.mode != "manual":
            triggers.append("schedule_enabled")

        reactivation_can_run = bool(triggers) and _profile_can_discover(candidate)
        catchup_required = (
            reactivation_can_run
            and "last_window"
            in self.watermarks.resume_options(candidate, None, self._now())
        )
        return {
            "required": catchup_required,
            "triggers": triggers if catchup_required else [],
            "max_catchup_days": candidate.search.max_catchup_days,
            "strategies": (
                ["last_window", "all", "from_now"] if catchup_required else []
            ),
        }

    def record_reactivation_choice(
        self,
        profile_id: str,
        profile_content_hash: str,
        strategy: str,
        catchup_days: Optional[int] = None,
        now: Optional[datetime] = None,
    ):
        profile = self.profile_registry.get(profile_id)
        if profile is None:
            raise LookupError("Research Profile '{}' does not exist".format(profile_id))
        if (
            not isinstance(profile_content_hash, str)
            or len(profile_content_hash) != 64
            or any(character not in "0123456789abcdef" for character in profile_content_hash)
        ):
            raise ValueError("Research Profile content hash must be a lowercase SHA-256 digest")
        if strategy not in {"last_window", "all", "from_now"}:
            raise ValueError("Unknown Research reactivation strategy")
        if strategy == "last_window":
            if catchup_days is None:
                catchup_days = profile.search.max_catchup_days
            if isinstance(catchup_days, bool) or not isinstance(catchup_days, int) or catchup_days < 1:
                raise ValueError("catchup_days must be a positive integer")
        elif catchup_days is not None:
            raise ValueError("catchup_days is only valid for the last_window strategy")
        timestamp = self._now() if now is None else _aware_utc(now, "now")
        return self.control_event_repository.create(
            profile_id,
            "reactivation_choice",
            {
                "profile_content_hash": profile_content_hash,
                "strategy": strategy,
                "catchup_days": catchup_days,
            },
            timestamp,
        )

    def resolve_effective_resume_policy(
        self, profile_id: str, profile_hash: str
    ) -> Optional[tuple[ResumeStrategy, Optional[int], Optional[datetime]]]:
        """Resolve a published reactivation choice for scheduled or incremental work."""
        choice = self.control_event_repository.latest_reactivation_choice_for_hash(
            profile_id, profile_hash
        )
        if choice is None:
            return None

        chosen_at = _parse_timestamp(choice["created_at"])
        state = self.profile_state_repository.get(profile_id)
        last_success = (
            _parse_timestamp(state.last_successful_scheduled_run_at)
            if state is not None and state.last_successful_scheduled_run_at is not None
            else None
        )
        if last_success is not None and last_success >= chosen_at:
            return None

        latest_resume = self.control_event_repository.latest_resume(profile_id)
        if latest_resume is not None and _parse_timestamp(latest_resume["created_at"]) >= chosen_at:
            return None

        strategy = choice["payload"].get("strategy")
        catchup_days = choice["payload"].get("catchup_days")
        if strategy not in {"last_window", "all", "from_now"}:
            raise ValueError("Stored Research reactivation choice has an invalid strategy")
        if strategy == "last_window":
            if isinstance(catchup_days, bool) or not isinstance(catchup_days, int) or catchup_days < 1:
                raise ValueError("Stored Research catchup_days must be a positive integer")
        else:
            catchup_days = None

        if strategy == "from_now":
            profile = self.profile_registry.get(profile_id)
            if profile is None:
                raise LookupError("Research Profile '{}' does not exist".format(profile_id))
            queries = self.query_builder.build(profile)
            if all(
                (watermark := self.search_repository.get_state(
                    profile_id, query.lens_id, provider, query.query_key
                )) is not None
                and watermark.completed_through is not None
                and _parse_timestamp(watermark.completed_through) >= chosen_at
                for query in queries
                for provider in profile.providers.discovery
            ):
                return "all", None, None
            return "from_now", None, chosen_at
        return strategy, catchup_days, None

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
        timestamp = self._now() if now is None else _aware_utc(now, "now")
        with self.work_repository.write_transaction():
            if strategy == "from_now":
                queries = self.query_builder.build(profile)
                self.watermarks.skip_profile_to_now(profile, timestamp, queries)
                self.control_event_repository.create(
                    profile_id,
                    "watermark_skip",
                    {"strategy": "from_now"},
                    timestamp,
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
        if not profile.ai_analysis.enabled:
            raise ValueError("Research AI Analysis is disabled")
        profile_state = self.profile_state_repository.get(profile_id)
        if (
            profile_state is not None
            and profile_state.paused_until is not None
            and _parse_timestamp(profile_state.paused_until) > queued_at
        ):
            raise ValueError("Research Profile is paused")
        if self.candidate_service.remaining_capacity(profile) <= 0:
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
            resume_strategy, catchup_days_override = self._scheduled_resume_options(
                profile.id, state
            )
            return self._run_profile_locked(
                profile_id=profile.id,
                trigger="scheduled",
                request_id=None,
                manual_range=None,
                lens_overrides=None,
                resume_strategy=resume_strategy,
                now=now,
                catchup_days_override=catchup_days_override,
            )
        finally:
            self.global_lock.release()

    def _most_overdue_profile(self, now: datetime) -> Optional[ResearchProfile]:
        eligible = []
        for profile in self.profile_registry.profiles:
            if (
                not profile.enabled
                or not profile.ai_analysis.enabled
                or profile.schedule.mode == "manual"
            ):
                continue
            if not any(lens.enabled for lens in profile.lenses):
                continue
            state = self.profile_state_repository.get(profile.id)
            if state is not None and state.paused_until is not None:
                if _parse_timestamp(state.paused_until) > now:
                    continue
            if self.candidate_service.remaining_capacity(profile) <= 0:
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

    def _scheduled_resume_options(self, profile_id: str, state) -> tuple[str, Optional[int]]:
        event = self.control_event_repository.latest_resume(profile_id)
        if event is None:
            return "all", None
        last_success = (
            _parse_timestamp(state.last_successful_scheduled_run_at)
            if state is not None and state.last_successful_scheduled_run_at is not None
            else None
        )
        event_at = _parse_timestamp(event["created_at"])
        if last_success is not None and event_at <= last_success:
            return "all", None
        payload = event["payload"]
        catchup_days = payload.get("catchup_days")
        if payload.get("strategy") == "catch_up" and catchup_days is not None:
            return "last_window", catchup_days
        return "all", None

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
        reactivation_effective_at = None
        if trigger == "scheduled" or manual_incremental:
            policy = self.resolve_effective_resume_policy(profile_id, profile_hash)
            if policy is not None:
                resume_strategy, catchup_days_override, reactivation_effective_at = policy
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
        if not profile.ai_analysis.enabled:
            return self._create_finished_run(
                profile,
                profile_hash,
                effective_config,
                trigger,
                request_id,
                "skipped_ai_disabled",
                now,
            )

        profile_state = self.profile_state_repository.get_or_create(profile.id, now)
        if (
            profile_state.paused_until is not None
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
        if self.candidate_service.remaining_capacity(profile) <= 0:
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
        if resume_strategy == "from_now" and manual_range is None:
            if reactivation_effective_at is None:
                self.watermarks.skip_profile_to_now(profile, now, queries)
                return self.run_repository.finish(
                    run.id, "success", {}, None, self._now()
                )
            skip_queries = {
                (query.lens_id, query.query_key): query
                for query in (*self.query_builder.build(canonical_profile), *queries)
            }
            self.watermarks.skip_profile_to_now(
                canonical_profile,
                reactivation_effective_at,
                tuple(skip_queries.values()),
            )
            # The durable from_now choice has moved stale watermarks to its fixed
            # publish-time boundary; this Run now uses the ordinary overlap window.
            resume_strategy = "all"

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
            for query in queries:
                lens = _lens_for(profile, query)
                for provider_name in profile.providers.discovery:
                    if terminal_status is not None:
                        break
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
                        manual_incremental=manual_incremental,
                    )
                    if plan.watermark_skip_required:
                        continue
                    provider_incomplete = False
                    for search_slice in plan.slices:
                        if terminal_status is not None or provider_incomplete:
                            break
                        if self.candidate_service.remaining_capacity(profile) <= 0:
                            terminal_status = "capacity_reached"
                            break
                        if not plan.manual:
                            self.watermarks.mark_attempt(plan, search_slice, self._now())
                        complete_slice, slice_status = self._process_slice(
                            run,
                            profile,
                            query,
                            lens,
                            provider_name,
                            provider,
                            plan,
                            search_slice,
                            stats,
                            errors,
                            warnings,
                            discovery_provider_failures,
                            unavailable_discovery_providers,
                            enrichment_provider_failures,
                            unavailable_enrichment_providers,
                            analysis_breaker,
                        )
                        if slice_status is not None:
                            terminal_status = slice_status
                        if complete_slice and not plan.manual:
                            self.watermarks.complete_slice(plan, search_slice, self._now())
                        else:
                            provider_incomplete = True
                    if terminal_status is not None:
                        break

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

    def _process_slice(
        self,
        run: ResearchRunRecord,
        profile: ResearchProfile,
        query: ResearchQuery,
        lens,
        provider_name: str,
        provider: ResearchProvider,
        plan: ResearchSearchPlan,
        search_slice,
        stats: dict,
        errors: list[str],
        warnings: list[str],
        discovery_provider_failures: dict[str, int],
        unavailable_discovery_providers: set[str],
        enrichment_provider_failures: dict[str, int],
        unavailable_enrichment_providers: set[str],
        analysis_breaker: ResearchAnalysisCircuitBreaker,
    ) -> tuple[bool, Optional[ResearchRunStatus]]:
        provider_summary = _provider_stats(stats, provider_name)
        cursor = None
        seen_cursors = set()
        while True:
            remaining_inbox = self.candidate_service.remaining_capacity(profile)
            current_run = self.run_repository.get(run.id)
            remaining_analysis_budget = (
                profile.search.max_analyses_per_run
                - current_run.analysis_attempt_count
            )
            remaining_candidate_budget = (
                profile.search.max_candidates_per_run - current_run.surfaced_count
            )
            if remaining_inbox <= 0:
                errors.append("Inbox capacity reached before the slice completed")
                return False, "capacity_reached"
            if remaining_analysis_budget <= 0:
                warnings.append(
                    "Analysis budget reached; the current search slice remains incomplete and its watermark was not advanced."
                )
            if remaining_candidate_budget <= 0:
                warnings.append(
                    "Candidate budget reached; the current search slice remains incomplete and its watermark was not advanced."
                )
            if remaining_analysis_budget <= 0 or remaining_candidate_budget <= 0:
                return False, "success"
            request_limit = self.profile_registry.global_config.runtime.discovery_page_size
            provider_summary["requests"] += 1
            try:
                page = provider.search(
                    query.text,
                    search_slice.start_at,
                    search_slice.end_at,
                    cursor,
                    limit=request_limit,
                )
            except ResearchProviderError as error:
                provider_summary["errors"] += 1
                discovery_provider_failures[provider_name] += 1
                errors.append("{}: {}".format(provider_name, str(error)[:240]))
                if (
                    discovery_provider_failures[provider_name]
                    >= self.provider_failure_threshold
                ):
                    unavailable_discovery_providers.add(provider_name)
                    provider_summary["circuit_open"] = True
                return False, None

            discovery_provider_failures[provider_name] = 0
            provider_summary["pages"] += 1
            if not isinstance(page, ProviderPage):
                errors.append("{}: adapter returned an invalid page".format(provider_name))
                provider_summary["errors"] += 1
                return False, None
            if len(page.works) > request_limit:
                errors.append(
                    "{}: adapter returned more Works than the requested limit".format(
                        provider_name
                    )
                )
                provider_summary["errors"] += 1
                return False, None
            provider_summary["works"] += len(page.works)
            complete_page = True
            eligible_works = []
            for index, provider_work in enumerate(page.works):
                if self.candidate_service.remaining_capacity(profile) <= 0:
                    errors.append("Inbox capacity reached before the slice completed")
                    return False, "capacity_reached"
                self.run_repository.update_progress(run.id, fetched_count=1)
                if not isinstance(provider_work, ProviderWork):
                    raise ValueError("Provider page contained an invalid Work")
                ingested = self.deduplicator.record_discovery(
                    profile.id,
                    query.lens_id,
                    query.query_key,
                    query.text,
                    provider_work,
                    discovered_at=self._now(),
                )
                if ingested.created_work:
                    self.run_repository.update_progress(run.id, new_work_count=1)
                else:
                    self.run_repository.update_progress(run.id, duplicate_count=1)
                screened = self.screening.screen(
                    ingested.work,
                    profile,
                    query,
                    search_slice,
                    self._now(),
                )
                if not screened.eligible:
                    self.run_repository.update_progress(
                        run.id, deterministic_filtered_count=1
                    )
                    continue

                if screened.pre_rank is None:
                    raise RuntimeError("Eligible Work is missing its Pre-Rank score")
                eligible_works.append(
                    (screened.pre_rank.score, index, ingested.work, provider_work.provider)
                )

            if not complete_page:
                return False, None

            eligible_works.sort(key=lambda item: (-item[0], item[1]))
            analysis_budget_reached = False
            for _, _, eligible_work, discovery_provider in eligible_works:
                work = eligible_work
                try:
                    context_pack = self.context_builder.build(
                        work,
                        profile,
                        lens,
                        keywords=(query.text,),
                    )
                    analysis_hash = self.analysis_service.input_hash(
                        work, profile, lens, context_pack
                    )
                    analysis = self.work_repository.get_analysis(
                        work.id, profile.id, analysis_hash
                    )
                    if analysis is None:
                        if profile.ai_analysis.enabled:
                            current_attempt_count = self.run_repository.get(
                                run.id
                            ).analysis_attempt_count
                            if (
                                current_attempt_count
                                >= profile.search.max_analyses_per_run
                            ):
                                analysis_budget_reached = True
                                continue
                            if analysis_breaker.analysis_disabled_for_run:
                                errors.append(
                                    "DeepSeek analysis circuit opened for this run"
                                )
                                return False, None
                            work = self._enrich_work(
                                work,
                                profile,
                                stats,
                                discovery_provider,
                                warnings,
                                enrichment_provider_failures,
                                unavailable_enrichment_providers,
                            )
                            if work != eligible_work:
                                context_pack = self.context_builder.build(
                                    work,
                                    profile,
                                    lens,
                                    keywords=(query.text,),
                                )
                                analysis_hash = self.analysis_service.input_hash(
                                    work, profile, lens, context_pack
                                )
                                analysis = self.work_repository.get_analysis(
                                    work.id, profile.id, analysis_hash
                                )
                            if analysis is None:
                                analysis_attempted = False

                                def record_analysis_attempt():
                                    nonlocal analysis_attempted
                                    self.run_repository.update_progress(
                                        run.id, analysis_attempt_count=1
                                    )
                                    analysis_attempted = True

                                analysis = self.analysis_service.analyze(
                                    work,
                                    profile,
                                    lens,
                                    context_pack,
                                    circuit_breaker=analysis_breaker,
                                    on_attempt=record_analysis_attempt,
                                )
                                if analysis_attempted:
                                    current_attempt_count = self.run_repository.get(
                                        run.id
                                    ).analysis_attempt_count
                                    analysis_budget_reached = (
                                        current_attempt_count
                                        >= profile.search.max_analyses_per_run
                                    )
                                    if analysis is not None:
                                        self.run_repository.update_progress(
                                            run.id, analyzed_count=1
                                        )
                    if analysis is None:
                        if analysis_breaker.analysis_disabled_for_run:
                            errors.append("DeepSeek analysis circuit opened for this run")
                            return False, None
                        continue

                    generated = self.candidate_service.generate(analysis, profile, lens)
                    if generated.outcome == "inbox_full":
                        errors.append("Inbox capacity reached before the slice completed")
                        return False, "capacity_reached"
                    if generated.outcome == "created":
                        self.run_repository.update_progress(run.id, surfaced_count=1)
                        if self.candidate_service.remaining_capacity(profile) <= 0:
                            errors.append("Inbox capacity reached before the slice completed")
                            return False, "capacity_reached"
                        if (
                            self.run_repository.get(run.id).surfaced_count
                            >= profile.search.max_candidates_per_run
                        ):
                            warnings.append(
                                "Candidate budget reached; the current search slice remains incomplete and its watermark was not advanced."
                            )
                            return False, "success"
                except AIGatewayError as error:
                    errors.append("DeepSeek: {}".format(str(error)[:240]))
                    complete_page = False
                    break
                except Exception:
                    raise

            if not complete_page:
                return False, None
            if analysis_budget_reached:
                warnings.append(
                    "Analysis budget reached; the current search slice remains incomplete and its watermark was not advanced."
                )
                return False, "success"
            if page.next_cursor is None:
                return True, None
            if page.next_cursor in seen_cursors or page.next_cursor == cursor:
                errors.append("{}: pagination cursor did not advance".format(provider_name))
                provider_summary["errors"] += 1
                return False, None
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor

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


def _profile_can_discover(profile: ResearchProfile) -> bool:
    return (
        profile.enabled
        and profile.ai_analysis.enabled
        and profile.schedule.mode != "manual"
        and any(lens.enabled for lens in profile.lenses)
        and bool(profile.providers.discovery)
    )
