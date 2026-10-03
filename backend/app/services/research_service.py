"""Single-profile Research pipeline with durable run and watermark boundaries."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Optional
import uuid

from backend.app.domain.research import ResearchProfile
from backend.app.domain.research_runtime import (
    ResearchContextPack,
    ResearchRunRecord,
    ResearchRunStatus,
    ResearchWorkRecord,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.repositories.research_run_repository import (
    ResearchProfileStateRepository,
    ResearchRunRepository,
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

    def run_profile(
        self,
        profile_id: str,
        trigger: str = "scheduled",
        request_id: Optional[str] = None,
        manual_range: Optional[tuple[datetime, datetime]] = None,
        lens_overrides: Optional[Mapping[str, bool]] = None,
        resume_strategy: ResumeStrategy = "all",
    ) -> Optional[ResearchRunRecord]:
        if trigger not in {"scheduled", "manual"}:
            raise ValueError("Research Run trigger must be scheduled or manual")
        if manual_range is not None and trigger != "manual":
            raise ValueError("Manual historical ranges require a manual Research Run")
        if not self.global_lock.acquire():
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
            )
        finally:
            self.global_lock.release()

    def _run_profile_locked(
        self,
        profile_id: str,
        trigger: str,
        request_id: Optional[str],
        manual_range: Optional[tuple[datetime, datetime]],
        lens_overrides: Optional[Mapping[str, bool]],
        resume_strategy: ResumeStrategy,
        now: datetime,
    ) -> Optional[ResearchRunRecord]:
        profile = self.profile_registry.get(profile_id)
        if profile is None:
            raise LookupError("Research Profile '{}' does not exist".format(profile_id))
        profile_hash = self.profile_registry.content_hash(profile_id)
        effective_config = _effective_config(
            profile, lens_overrides, manual_range, resume_strategy
        )

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

        queries = self.query_builder.build(profile, lens_overrides)
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
            self.watermarks.skip_profile_to_now(profile, now, queries)
            return self.run_repository.finish(
                run.id, "success", {}, None, self._now()
            )

        all_provider_names = tuple(
            dict.fromkeys(
                list(profile.providers.discovery) + list(profile.providers.enrichment)
            )
        )
        stats = _new_stats(all_provider_names)
        provider_failures = {name: 0 for name in all_provider_names}
        unavailable_providers: set[str] = set()
        analysis_breaker = ResearchAnalysisCircuitBreaker()
        errors: list[str] = []
        terminal_status: Optional[ResearchRunStatus] = None

        try:
            for query in queries:
                lens = _lens_for(profile, query)
                for provider_name in profile.providers.discovery:
                    if terminal_status is not None:
                        break
                    if provider_name in unavailable_providers:
                        continue
                    provider = self.providers.get(provider_name)
                    if provider is None:
                        unavailable_providers.add(provider_name)
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
                            provider_failures,
                            unavailable_providers,
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
        finished = self.run_repository.finish(
            run.id,
            status,
            summary,
            "; ".join(errors)[:1_000] or None,
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
        provider_failures: dict[str, int],
        unavailable_providers: set[str],
        analysis_breaker: ResearchAnalysisCircuitBreaker,
    ) -> tuple[bool, Optional[ResearchRunStatus]]:
        provider_summary = _provider_stats(stats, provider_name)
        cursor = None
        seen_cursors = set()
        while True:
            if self.candidate_service.remaining_capacity(profile) <= 0:
                errors.append("Inbox capacity reached before the slice completed")
                return False, "capacity_reached"
            provider_summary["requests"] += 1
            try:
                page = provider.search(
                    query.text,
                    search_slice.start_at,
                    search_slice.end_at,
                    cursor,
                )
            except ResearchProviderError as error:
                provider_summary["errors"] += 1
                provider_failures[provider_name] += 1
                errors.append("{}: {}".format(provider_name, str(error)[:240]))
                if provider_failures[provider_name] >= self.provider_failure_threshold:
                    unavailable_providers.add(provider_name)
                    provider_summary["circuit_open"] = True
                return False, None

            provider_failures[provider_name] = 0
            provider_summary["pages"] += 1
            if not isinstance(page, ProviderPage):
                errors.append("{}: adapter returned an invalid page".format(provider_name))
                provider_summary["errors"] += 1
                return False, None
            provider_summary["works"] += len(page.works)
            complete_page = True
            for index, provider_work in enumerate(page.works):
                if self.candidate_service.remaining_capacity(profile) <= 0:
                    errors.append("Inbox capacity reached before the slice completed")
                    return False, "capacity_reached"
                try:
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
                    work, enrichment_failed = self._enrich_work(
                        ingested.work,
                        profile,
                        stats,
                        errors,
                        provider_failures,
                        unavailable_providers,
                    )
                    if enrichment_failed:
                        complete_page = False
                        break

                    screened = self.screening.screen(
                        work,
                        profile,
                        query,
                        search_slice,
                        self._now(),
                        analysis_input_hash="",
                    )
                    if not screened.eligible:
                        self.run_repository.update_progress(
                            run.id, deterministic_filtered_count=1
                        )
                        continue

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
                        analysis = self.analysis_service.analyze(
                            work,
                            profile,
                            lens,
                            context_pack,
                            circuit_breaker=analysis_breaker,
                        )
                    if analysis is None:
                        if analysis_breaker.analysis_disabled_for_run:
                            errors.append("DeepSeek analysis circuit opened for this run")
                            return False, None
                        continue

                    self.run_repository.update_progress(run.id, analyzed_count=1)
                    generated = self.candidate_service.generate(analysis, profile, lens)
                    if generated.outcome == "inbox_full":
                        errors.append("Inbox capacity reached before the slice completed")
                        return False, "capacity_reached"
                    if generated.outcome == "created":
                        self.run_repository.update_progress(run.id, surfaced_count=1)
                        if self.candidate_service.remaining_capacity(profile) <= 0:
                            errors.append("Inbox capacity reached before the slice completed")
                            return False, "capacity_reached"
                        if self.run_repository.get(run.id).surfaced_count >= profile.search.max_candidates_per_run:
                            errors.append("Per-run Candidate limit reached before the slice completed")
                            return False, "capacity_reached"
                except AIGatewayError as error:
                    errors.append("DeepSeek: {}".format(str(error)[:240]))
                    complete_page = False
                    break
                except Exception:
                    raise

            if not complete_page:
                return False, None
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
        errors: list[str],
        provider_failures: dict[str, int],
        unavailable_providers: set[str],
    ) -> tuple[ResearchWorkRecord, bool]:
        failed = False
        enriched_work = work
        for provider_name in profile.providers.enrichment:
            if provider_name in unavailable_providers:
                failed = True
                continue
            provider = self.providers.get(provider_name)
            enrich = getattr(provider, "enrich", None) if provider is not None else None
            summary = _provider_stats(stats, provider_name)
            if not callable(enrich):
                summary["errors"] += 1
                errors.append("{}: enrichment adapter is not configured".format(provider_name))
                provider_failures[provider_name] = self.provider_failure_threshold
                unavailable_providers.add(provider_name)
                failed = True
                continue
            summary["requests"] += 1
            try:
                enriched = enrich(enriched_work)
            except ResearchProviderError as error:
                summary["errors"] += 1
                provider_failures[provider_name] += 1
                errors.append("{} enrichment: {}".format(provider_name, str(error)[:220]))
                if provider_failures[provider_name] >= self.provider_failure_threshold:
                    summary["circuit_open"] = True
                    unavailable_providers.add(provider_name)
                failed = True
                continue
            provider_failures[provider_name] = 0
            if enriched is None:
                continue
            if not isinstance(enriched, ProviderWork):
                raise ValueError("{} enrichment returned an invalid Work".format(provider_name))
            enriched_work = self.deduplicator.enrich_existing_work(
                enriched_work.id, enriched
            )
            summary["works"] += 1
        return enriched_work, failed

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


\n