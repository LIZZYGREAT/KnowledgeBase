"""Bounded, Focus-aware Term Discovery over the existing local corpus."""

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import uuid
from typing import Callable, Optional
from urllib.parse import urlsplit

from backend.app.domain.ai import TermDiscoveryOutput
from backend.app.domain.term_discovery import (
    DiscoveryLane,
    TermDiscoveryRun,
    TermDiscoveryRunItem,
    TermDiscoverySettings,
    TermDiscoveryState,
)
from backend.app.domain.term_runtime import (
    TermCandidateEvidenceInput,
    TermDiscoveryAssessment,
    TermOriginType,
)
from backend.app.domain.document import DocumentMetadata
from backend.app.repositories.term_discovery_repository import TermDiscoveryRepository
from backend.app.services.ai_client import AIResponseError
from backend.app.services.knowledge_state_service import KnowledgeStateService
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.resolution import normalize_key
from backend.app.services.source_registry import SourceRegistry
from backend.app.services.term_candidate_service import (
    TermCandidateConflict,
    TermCandidateService,
)
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver
from backend.app.services.vocabulary_mining import mine_vocabulary
from backend.app.services.wikipedia_discovery import (
    MAX_RESULTS as MAX_EXTERNAL_RESULTS,
    ExternalDiscoveryResult,
    WikipediaDiscovery,
)


DISCOVERY_ANALYSIS_VERSION = 4
GLOBAL_OPEN_CAPACITY = 12
MAX_SOURCES_PER_RUN = 3
MAX_TEXT_CHARS_PER_REQUEST = 12_000
MAX_VOCABULARY_OPTIONS = 20
MAX_DOCUMENTS_PER_RUN = 3
MAX_DOCUMENT_BYTES = 2_000_000
MAX_RECENT_DOCUMENTS = 12
MAX_EXTERNAL_QUERY_FOCUS_ITEMS = 4
MAX_TERM_LEARNING_CONTEXT_CHARS = 6000
MAX_TERM_CONTEXT_SOURCES = 20
MAX_TERM_PREFERENCE_ITEMS = 12
_LANE_ORDER: tuple[DiscoveryLane, ...] = ("concept", "entity", "vocabulary")


@dataclass(frozen=True)
class DiscoveryCorpus:
    origin_type: TermOriginType
    origin_id: str
    origin: object
    text: str
    text_hash: str
    analysis_id: str
    lanes: tuple[DiscoveryLane, ...]
    is_pdf: bool = False


@dataclass(frozen=True)
class _DocumentContext:
    id: str
    title: str
    domains: tuple[str, ...]
    topics: tuple[str, ...]
    authors: tuple[str, ...] = ()
    year: Optional[int] = None


class TermDiscoveryService:
    def __init__(
        self,
        repository_root: Path,
        repository: TermDiscoveryRepository,
        pdf_corpus_service,
        candidate_service: TermCandidateService,
        ai_gateway,
        knowledge_state_service: Optional[KnowledgeStateService] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        external_discovery=None,
        learning_context_service=None,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.repository = repository
        self.pdf_corpus_service = pdf_corpus_service
        self.candidate_service = candidate_service
        self.ai_gateway = ai_gateway
        self.clock = clock
        self.external_discovery = (
            external_discovery if external_discovery is not None else WikipediaDiscovery()
        )
        self._lock = self.candidate_service.discovery_lock
        self.knowledge_state = knowledge_state_service or KnowledgeStateService(
            self.repository_root, repository.connection, clock
        )
        self.learning_context = learning_context_service

    def get_settings(self) -> TermDiscoverySettings:
        return self.repository.get_settings()

    def update_settings(self, settings: TermDiscoverySettings) -> TermDiscoveryState:
        if not isinstance(settings, TermDiscoverySettings):
            settings = TermDiscoverySettings.model_validate(settings)
        self.repository.save_settings(settings, self._now())
        return self.get_state()

    def get_state(self) -> TermDiscoveryState:
        settings = self.repository.get_settings()
        opened = self.repository.open_candidate_count()
        lane_open = self.repository.open_candidate_count_by_lane()
        now = self._datetime()
        window_start = _daily_window_start(now)
        daily_remaining = max(
            0, settings.daily_max_new - self.repository.daily_candidate_count(window_start)
        )
        runs = self.repository.list_runs(limit=1)
        return TermDiscoveryState(
            settings=settings,
            open_count=opened,
            global_capacity=GLOBAL_OPEN_CAPACITY,
            daily_remaining=daily_remaining,
            lane_open=lane_open,
            lane_capacity=settings.lane_capacities,
            last_run=runs[0] if runs else None,
        )

    def list_runs(self, limit: int = 20) -> list[TermDiscoveryRun]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("Discovery Run limit must be between 1 and 100")
        return self.repository.list_runs(limit)

    def get_run(self, run_id: str) -> TermDiscoveryRun:
        run = self.repository.get_run(run_id)
        if run is None:
            raise LookupError("Term Discovery Run '{}' does not exist".format(run_id))
        return run

    def run(
        self, trigger: str = "manual", discovery_mode: Optional[str] = None
    ) -> TermDiscoveryRun:
        if trigger not in {"manual", "scheduled"}:
            raise ValueError("Term Discovery trigger must be manual or scheduled")
        if discovery_mode is None:
            discovery_mode = (
                "personalized" if self.learning_context is not None else "general"
            )
        if discovery_mode not in {"personalized", "general"}:
            raise ValueError("Term Discovery mode must be personalized or general")
        started_at = self._now()
        run_id = uuid.uuid4().hex
        if not self._lock.try_acquire():
            return self._finish_run(
                run_id,
                trigger,
                "partial",
                started_at,
                {},
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                0,
                [],
                "Another Term Discovery Run is already active",
                discovery_mode,
            )
        try:
            return self._run_locked(trigger, started_at, run_id, discovery_mode)
        except Exception as error:
            return self._finish_run(
                run_id,
                trigger,
                "failed",
                started_at,
                {},
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                0,
                [],
                str(error)[:500],
                discovery_mode,
            )
        finally:
            self._lock.release()

    def scheduled_check(self) -> Optional[TermDiscoveryRun]:
        now = self._datetime()
        window_start = _daily_window_start(now)
        if self.repository.has_scheduled_run_since(window_start):
            return None
        settings = self.repository.get_settings()
        core_lanes = [
            lane for lane in _LANE_ORDER[:2] if lane in settings.enabled_lanes
        ]
        has_note = False
        focus: list[str] = []
        focus_snapshot: dict = {}
        if core_lanes or settings.external_enabled:
            base_focus = _focus_context(self.repository_root, settings)
            preferences = self._learning_preferences()
            context_seed = _learning_context_query(
                base_focus, preferences, settings.focus_override
            )
            learning_context = self._learning_context(
                context_seed.split(), preferences
            )
            explicit_focus = _term_focus_seed(
                base_focus,
                preferences,
                [item["title"] for item in learning_context["topics"]],
                settings.focus_override,
            )
            focus_snapshot = self.knowledge_state.build_snapshot(explicit_focus)
            focus = _discovery_focus(
                explicit_focus, focus_snapshot, settings.focus_override
            )
            learning_context["current_focus"] = focus[:20]
        if core_lanes:
            focus_hash = _term_discovery_focus_hash(
                focus, focus_snapshot, learning_context
            )
            registry = TermRegistry.load(
                self.repository_root / "knowledge" / "terms"
            )
            selected_scope = _selected_document_scope(
                learning_context, "personalized"
            )
            selected_documents = _select_documents(
                self.repository_root,
                self.repository,
                core_lanes,
                focus,
                focus_snapshot,
                focus_hash,
                registry,
                selected_scope,
            )
            has_note = bool(selected_documents)
        if not has_note:
            return None
        return self.run(trigger="scheduled", discovery_mode="personalized")

    def _run_locked(
        self, trigger: str, started_at: str, run_id: str, discovery_mode: str
    ) -> TermDiscoveryRun:
        settings = self.repository.get_settings()
        open_count = self.repository.open_candidate_count()
        window_start = _daily_window_start(datetime.fromisoformat(started_at))
        daily_remaining = max(
            0, settings.daily_max_new - self.repository.daily_candidate_count(window_start)
        )
        enabled_lanes = [lane for lane in _LANE_ORDER if lane in settings.enabled_lanes]

        if open_count >= GLOBAL_OPEN_CAPACITY:
            return self._finish_run(
                run_id,
                trigger,
                "skipped_capacity",
                started_at,
                {},
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                0,
                [],
                None,
                discovery_mode,
            )
        if not enabled_lanes:
            return self._finish_run(
                run_id,
                trigger,
                "skipped_disabled",
                started_at,
                {},
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                0,
                [],
                None,
                discovery_mode,
            )

        open_by_lane = self.repository.open_candidate_count_by_lane()
        run_allowance = _dynamic_allowance(open_count)
        global_remaining = max(0, GLOBAL_OPEN_CAPACITY - open_count)
        total_budget = min(run_allowance, daily_remaining, global_remaining)
        budgets = _allocate_lane_budgets(
            enabled_lanes,
            total_budget,
            settings.lane_capacities,
            open_by_lane,
        )
        if not any(budgets.values()):
            return self._finish_run(
                run_id,
                trigger,
                "skipped_capacity",
                started_at,
                {},
                budgets,
                {lane: 0 for lane in _LANE_ORDER},
                {lane: 0 for lane in _LANE_ORDER},
                0,
                [],
                None,
                discovery_mode,
            )

        allocated_budgets = dict(budgets)
        remaining_budgets = dict(budgets)

        sync_status = None
        sync_if_stale = getattr(self.learning_context, "sync_if_stale", None)
        if callable(sync_if_stale):
            sync_status = sync_if_stale()

        base_focus = _focus_context(self.repository_root, settings)
        preferences = self._learning_preferences()
        context_seed = _learning_context_query(
            base_focus, preferences, settings.focus_override
        )
        learning_context = self._learning_context(context_seed.split(), preferences)
        explicit_focus = _term_focus_seed(
            base_focus,
            preferences,
            [
                *(item["title"] for item in learning_context["topics"]),
                learning_context["user_direction"],
            ],
            settings.focus_override,
        )
        snapshot = self.knowledge_state.build_snapshot(explicit_focus)
        snapshot["discovery_mode"] = discovery_mode
        focus = _discovery_focus(explicit_focus, snapshot, settings.focus_override)
        learning_context["current_focus"] = focus[:20]
        snapshot["effective_focus"] = focus[:20]
        focus_hash = _term_discovery_focus_hash(focus, snapshot, learning_context)
        snapshot["learning_context"] = {
            "included_source_ids": [
                item["id"] for item in learning_context["included_sources"]
            ],
            "matched_topic_ids": [item["id"] for item in learning_context["topics"]],
            "context_hash": _json_hash(learning_context),
        }
        if isinstance(sync_status, dict):
            snapshot["learning_context"]["sync_status"] = {
                key: sync_status.get(key)
                for key in ("state", "stale", "used_previous_context", "message")
            }
        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        resolver = TermResolver(registry)
        source_registry = SourceRegistry.load(
            self.repository_root / "knowledge" / "sources"
        )
        sources = (
            _select_sources(
                source_registry,
                settings.source_preferences,
                focus,
                self.repository_root,
                self.repository,
                self.pdf_corpus_service,
                enabled_lanes,
                focus_hash,
            )
            if discovery_mode == "general"
            else []
        )
        documents = _select_documents(
            self.repository_root,
            self.repository,
            enabled_lanes,
            focus,
            snapshot,
            focus_hash,
            registry,
            _selected_document_scope(learning_context, discovery_mode),
        )
        self.repository.retain_vocabulary_sources(
            {
                source.id
                for source in source_registry.sources
                if source.attachments.local_pdf
            }
        )
        raw_counts = {lane: 0 for lane in _LANE_ORDER}
        filtered_counts = {lane: 0 for lane in _LANE_ORDER}
        items: list[TermDiscoveryRunItem] = []
        errors: list[str] = []
        if isinstance(sync_status, dict) and sync_status.get("used_previous_context"):
            errors.append(
                sync_status.get(
                    "message",
                    "学习上下文同步未完成；本次使用上次保存的上下文。",
                )
            )
        created_count = 0

        created_count += self._process_additional_corpora(
            documents,
            run_id,
            snapshot,
            focus,
            learning_context,
            registry,
            resolver,
            focus_hash,
            remaining_budgets,
            raw_counts,
            filtered_counts,
            items,
            errors,
        )

        for source in sources:
            if not any(remaining_budgets.values()):
                break
            try:
                corpus = self.pdf_corpus_service.ensure(source.id)
            except Exception as error:
                errors.append("{}: {}".format(source.id, str(error)[:200]))
                for lane in _LANE_ORDER:
                    if remaining_budgets[lane] > 0:
                        filtered_counts[lane] += 1
                continue
            if corpus.status != "ready" or not corpus.text or not corpus.text_hash:
                for lane in _LANE_ORDER:
                    if remaining_budgets[lane] > 0:
                        filtered_counts[lane] += 1
                if corpus.status in {"failed", "unavailable"}:
                    errors.append(
                        "{}: {}".format(source.id, corpus.error_message or "PDF extraction failed")
                    )
                continue
            created_count += self._process_additional_corpora(
                [
                    DiscoveryCorpus(
                        "source",
                        source.id,
                        source,
                        corpus.text,
                        corpus.text_hash,
                        source.id,
                        tuple(_LANE_ORDER),
                        is_pdf=True,
                    )
                ],
                run_id,
                snapshot,
                focus,
                learning_context,
                registry,
                resolver,
                focus_hash,
                remaining_budgets,
                raw_counts,
                filtered_counts,
                items,
                errors,
            )

        external_corpora: list[DiscoveryCorpus] = []
        external_lanes = tuple(
            lane
            for lane in enabled_lanes
            if lane in {"concept", "entity"} and remaining_budgets[lane] > 0
        )
        external_query = _external_query(focus)
        if (
            discovery_mode == "general"
            and settings.external_enabled
            and external_lanes
            and external_query
            and self.repository.open_candidate_count() < GLOBAL_OPEN_CAPACITY
        ):
            try:
                results = self.external_discovery.search(
                    external_query, limit=MAX_EXTERNAL_RESULTS
                )
                for result in results[:MAX_EXTERNAL_RESULTS]:
                    if not isinstance(result, ExternalDiscoveryResult):
                        continue
                    if not _is_wikipedia_result_url(result.url):
                        continue
                    title = " ".join(result.title.split())[:200]
                    text = " ".join(result.snippet.split())[:600]
                    if not title or not text:
                        continue
                    context = _DocumentContext(
                        id=result.url,
                        title=title,
                        domains=(),
                        topics=(),
                    )
                    external_corpora.append(
                        DiscoveryCorpus(
                            "external",
                            result.url,
                            context,
                            text,
                            sha256(text.encode("utf-8")).hexdigest(),
                            "external:{}".format(sha256(result.url.encode("utf-8")).hexdigest()),
                            external_lanes,
                        )
                    )
            except Exception as error:
                errors.append("Wikipedia discovery: {}".format(str(error)[:200]))
        created_count += self._process_additional_corpora(
            external_corpora,
            run_id,
            snapshot,
            focus,
            learning_context,
            registry,
            resolver,
            focus_hash,
            remaining_budgets,
            raw_counts,
            filtered_counts,
            items,
            errors,
        )

        status = "partial" if errors else "success"
        return self._finish_run(
            run_id,
            trigger,
            status,
            started_at,
            snapshot,
            allocated_budgets,
            raw_counts,
            filtered_counts,
            created_count,
            items,
            "; ".join(errors[:6]) or None,
            discovery_mode,
        )

    def _process_additional_corpora(
        self,
        corpora: list[DiscoveryCorpus],
        run_id: str,
        snapshot: dict,
        focus: list[str],
        learning_context: dict,
        registry: TermRegistry,
        resolver: TermResolver,
        focus_hash: str,
        remaining_budgets: dict[str, int],
        raw_counts: dict[str, int],
        filtered_counts: dict[str, int],
        items: list[TermDiscoveryRunItem],
        errors: list[str],
    ) -> int:
        created_count = 0
        for corpus in corpora:
            if not any(remaining_budgets.values()):
                break
            if corpus.is_pdf:
                statistics = mine_vocabulary(corpus.text)
                self.repository.replace_vocabulary_source_statistics(
                    corpus.origin_id, corpus.text_hash, statistics, self._now()
                )
            lane_created_counts = {lane: 0 for lane in _LANE_ORDER}
            for lane in corpus.lanes:
                if remaining_budgets[lane] <= 0:
                    continue
                state = self.repository.get_analysis_state(corpus.analysis_id, lane)
                if (
                    state is not None
                    and state["text_hash"] == corpus.text_hash
                    and state["focus_hash"] == focus_hash
                    and state["analysis_version"] == DISCOVERY_ANALYSIS_VERSION
                ):
                    filtered_counts[lane] += 1
                    continue
                try:
                    suggestions = self._discover_for_lane(
                        lane,
                        corpus.origin,
                        corpus.text,
                        snapshot,
                        focus,
                        learning_context,
                        registry,
                        resolver,
                    )
                except Exception as error:
                    errors.append(
                        "{} {}: {}".format(corpus.origin_id, lane, str(error)[:220])
                    )
                    continue

                raw_counts[lane] += len(suggestions)
                for suggestion in suggestions:
                    if (
                        suggestion.term_type != lane
                        or suggestion.mention.casefold() not in corpus.text.casefold()
                        or suggestion.mention.casefold()
                        not in suggestion.context_excerpt.casefold()
                        or suggestion.context_excerpt not in corpus.text
                    ):
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id,
                                lane,
                                corpus.origin_id,
                                suggestion,
                                "filtered",
                                None,
                            )
                        )
                        continue
                    if (
                        suggestion.existing_term_id
                        and registry.get(suggestion.existing_term_id) is None
                    ):
                        errors.append(
                            "{} {} referenced unknown Term id {}".format(
                                corpus.origin_id, lane, suggestion.existing_term_id
                            )
                        )
                        filtered_counts[lane] += 1
                        continue
                    if _excluded_by_preferences(
                        suggestion.mention, learning_context["preferences"]
                    ) or _covered_by_learning_context(
                        suggestion.mention, learning_context, resolver
                    ):
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id,
                                lane,
                                corpus.origin_id,
                                suggestion,
                                "filtered",
                                None,
                            )
                        )
                        continue
                    if suggestion.recommendation_level == "stretch":
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id,
                                lane,
                                corpus.origin_id,
                                suggestion,
                                "stretch",
                                None,
                            )
                        )
                        continue
                    if lane_created_counts[lane] >= remaining_budgets[lane]:
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id,
                                lane,
                                corpus.origin_id,
                                suggestion,
                                "filtered",
                                None,
                            )
                        )
                        continue
                    if self.repository.open_candidate_count() >= GLOBAL_OPEN_CAPACITY:
                        filtered_counts[lane] += 1
                        continue

                    normalized = normalize_key(suggestion.mention)
                    registry_match = resolver.resolve(suggestion.mention)
                    if registry_match.status == "ambiguous":
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id,
                                lane,
                                corpus.origin_id,
                                suggestion,
                                "filtered",
                                None,
                            )
                        )
                        continue
                    if (
                        suggestion.existing_term_id
                        and registry_match.status == "resolved"
                        and registry_match.entity_id != suggestion.existing_term_id
                    ):
                        errors.append(
                            "{} suggested an Existing Term id inconsistent with the Registry".format(
                                suggestion.mention
                            )
                        )
                        filtered_counts[lane] += 1
                        continue
                    existing_term_id = (
                        registry_match.entity_id
                        if registry_match.status == "resolved"
                        else suggestion.existing_term_id
                    )
                    candidate_repository = self.candidate_service.repository
                    if candidate_repository.has_accepted_candidate_evidence(
                        normalized, corpus.origin_type, corpus.origin_id
                    ) or (
                        corpus.origin_type != "external"
                        and existing_term_id is not None
                        and candidate_repository.has_relation(
                            corpus.origin_type, corpus.origin_id, existing_term_id
                        )
                    ):
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id,
                                lane,
                                corpus.origin_id,
                                suggestion,
                                "duplicate",
                                None,
                            )
                        )
                        continue
                    existing_open = candidate_repository.find_open_candidate(normalized)
                    if existing_open is not None and existing_open.suggested_type != lane:
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id,
                                lane,
                                corpus.origin_id,
                                suggestion,
                                "duplicate",
                                existing_open.id,
                            )
                        )
                        continue
                    evidence = TermCandidateEvidenceInput(
                        origin_type=corpus.origin_type,
                        origin_id=corpus.origin_id,
                        mention=suggestion.mention,
                        origin_title=(
                            getattr(corpus.origin, "title", None)
                            if corpus.origin_type == "external"
                            else None
                        ),
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
                        candidate = self.candidate_service.create_candidate(
                            suggestion.mention,
                            lane,
                            [evidence],
                            preferred_term_id=suggestion.existing_term_id,
                            discovery_assessment=assessment,
                        )
                    except (TermCandidateConflict, ValueError):
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id,
                                lane,
                                corpus.origin_id,
                                suggestion,
                                "rejected",
                                None,
                            )
                        )
                        continue
                    if existing_open is None:
                        outcome = "created"
                        lane_created_counts[lane] += 1
                        created_count += 1
                    else:
                        outcome = "duplicate"
                        filtered_counts[lane] += 1
                    items.append(
                        self._item(
                            run_id,
                            lane,
                            corpus.origin_id,
                            suggestion,
                            outcome,
                            candidate.id,
                        )
                    )
                self.repository.save_analysis_state(
                    corpus.analysis_id,
                    corpus.text_hash,
                    focus_hash,
                    lane,
                    DISCOVERY_ANALYSIS_VERSION,
                    self._now(),
                )
                remaining_budgets[lane] = max(
                    0,
                    remaining_budgets[lane] - lane_created_counts[lane],
                )
        return created_count

    def _discover_for_lane(
        self,
        lane: DiscoveryLane,
        source,
        corpus_text: str,
        snapshot: dict,
        focus: list[str],
        learning_context: dict,
        registry: TermRegistry,
        resolver: TermResolver,
    ) -> list:
        context = {
            "lane": lane,
            "focus": focus,
            "knowledge_state": {
                "focus": {"explicit": focus[:20]},
                "knowledge": {
                    "established": snapshot.get("knowledge", {}).get(
                        "established", []
                    )[:40]
                },
            },
            "learning_context": learning_context,
            "term_registry": [
                {"id": term.id, "title": term.title, "aliases": list(term.aliases[:8]), "type": term.type}
                for term in registry.terms[:200]
            ],
            "source": {
                "id": source.id,
                "title": source.title,
                "authors": list(getattr(source, "authors", ())[:3]),
                "year": getattr(source, "year", None),
                "domains": list(getattr(source, "domains", ())),
                "topics": list(getattr(source, "topics", ())),
            },
        }
        if lane == "vocabulary":
            counts = self.repository.vocabulary_candidates(limit=80)
            eligible = []
            for item in counts:
                if item["display_term"].casefold() not in corpus_text.casefold():
                    continue
                match = resolver.resolve(item["display_term"])
                if match.status in {"resolved", "ambiguous"}:
                    continue
                if self.candidate_service.repository.is_rejected(
                    normalize_key(item["display_term"]), "global"
                ):
                    continue
                eligible.append(item)
            context["vocabulary_candidates"] = [
                {
                    "term": item["display_term"],
                    "total_count": item["total_count"],
                    "document_frequency": item["document_frequency"],
                    "example_context": _term_excerpt(corpus_text, item["display_term"]),
                }
                for item in eligible[:MAX_VOCABULARY_OPTIONS]
            ]
            if not context["vocabulary_candidates"]:
                return []
        else:
            context["source_text_excerpt"] = _select_relevant_excerpt(corpus_text, focus)
        output = self.ai_gateway.run("discover_terms", context)
        if not isinstance(output, TermDiscoveryOutput):
            raise AIResponseError("Term Discovery returned an unexpected output model")
        if lane == "vocabulary":
            requested = {
                normalize_key(item["term"])
                for item in context["vocabulary_candidates"]
            }
            if any(normalize_key(item.mention) not in requested for item in output.candidates):
                raise AIResponseError("Vocabulary Discovery returned a term outside mined corpus candidates")
        return output.candidates

    def _learning_preferences(self) -> dict:
        if self.learning_context is None:
            return _empty_learning_preferences()
        return self.learning_context.get_preferences()

    def _learning_context(self, focus: list[str], preferences: dict) -> dict:
        if self.learning_context is None:
            raw = {
                "included_sources": [],
                "selected_source_ids": None,
                "preferences": preferences,
                "active": "",
                "important": "",
                "user_direction": "",
                "topics": [],
            }
        else:
            raw = self.learning_context.get_context(
                focus=" ".join(focus),
                include_important=True,
                max_chars=MAX_TERM_LEARNING_CONTEXT_CHARS,
            )
        bounded = {
            "included_sources": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "type": item["type"],
                }
                for item in raw.get("included_sources", [])[:MAX_TERM_CONTEXT_SOURCES]
            ],
            "selected_source_ids": (
                list(raw.get("selected_source_ids", []))
                if self.learning_context is not None
                else None
            ),
            "preferences": _bounded_term_preferences(
                raw.get("preferences", preferences)
            ),
            "active": raw.get("active", "")[:MAX_TERM_LEARNING_CONTEXT_CHARS],
            "important": raw.get("important", "")[:MAX_TERM_LEARNING_CONTEXT_CHARS],
            "user_direction": raw.get("user_direction", "")[:1000],
            "topics": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "markdown": item["markdown"][:MAX_TERM_LEARNING_CONTEXT_CHARS],
                }
                for item in raw.get("topics", [])[:3]
            ],
        }
        bounded["covered_term_headings"] = _learning_context_headings(bounded)
        return bounded

    def _item(self, run_id, lane, source_id, suggestion, outcome, candidate_id):
        return TermDiscoveryRunItem(
            id=uuid.uuid4().hex,
            run_id=run_id,
            lane=lane,
            source_id=source_id,
            mention=suggestion.mention,
            outcome=outcome,
            candidate_id=candidate_id,
            assessment=TermDiscoveryAssessment(
                readiness=suggestion.readiness,
                recommendation_level=suggestion.recommendation_level,
                known_prerequisites=suggestion.known_prerequisites,
                missing_prerequisites=suggestion.missing_prerequisites,
                why_now=suggestion.why_now,
            ),
            rationale=suggestion.rationale,
            context_excerpt=suggestion.context_excerpt,
            created_at=self._now(),
        )

    def _finish_run(
        self,
        run_id,
        trigger,
        status,
        started_at,
        snapshot,
        budgets,
        raw_counts,
        filtered_counts,
        candidate_count,
        items,
        error_summary,
        discovery_mode="general",
    ) -> TermDiscoveryRun:
        snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
        snapshot.setdefault("discovery_mode", discovery_mode)
        run = TermDiscoveryRun(
            id=run_id,
            trigger=trigger,
            status=status,
            snapshot=snapshot,
            lane_budgets=budgets,
            raw_counts=raw_counts,
            filtered_counts=filtered_counts,
            candidate_count=candidate_count,
            started_at=started_at,
            finished_at=self._now(),
            error_summary=error_summary,
            items=items,
        )
        self.repository.save_run(run)
        return run

    def _datetime(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Term Discovery clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def _now(self) -> str:
        return self._datetime().isoformat(timespec="seconds")


def _dynamic_allowance(open_count: int) -> int:
    if open_count <= 3:
        return 5
    if open_count <= 7:
        return 3
    if open_count <= 11:
        return 1
    return 0


def _daily_window_start(now: datetime) -> str:
    return (now - timedelta(hours=24)).isoformat(timespec="seconds")


def _allocate_lane_budgets(
    enabled_lanes: list[DiscoveryLane],
    total_budget: int,
    capacities: dict[str, int],
    open_by_lane: dict[str, int],
) -> dict[str, int]:
    remaining = {
        lane: max(0, capacities[lane] - open_by_lane.get(lane, 0))
        if lane in enabled_lanes
        else 0
        for lane in _LANE_ORDER
    }
    budgets = {lane: 0 for lane in _LANE_ORDER}
    left = total_budget
    while left > 0:
        progressed = False
        for lane in _LANE_ORDER:
            if lane not in enabled_lanes or remaining[lane] <= 0:
                continue
            budgets[lane] += 1
            remaining[lane] -= 1
            left -= 1
            progressed = True
            if left == 0:
                break
        if not progressed:
            break
    return budgets


def _focus_context(repository_root: Path, settings: TermDiscoverySettings) -> list[str]:
    focus = []
    if settings.focus_override:
        focus.append(settings.focus_override)
    profiles_dir = repository_root / "config" / "research" / "profiles"
    if profiles_dir.is_dir():
        try:
            from backend.app.services.research_profile_registry import ResearchProfileRegistry

            profiles = ResearchProfileRegistry.load(repository_root).profiles
            for profile in profiles:
                if not profile.enabled:
                    continue
                focus.append(profile.title)
                for lens in profile.lenses:
                    if lens.enabled:
                        focus.append(lens.title)
                        focus.extend(lens.queries[:4])
        except (OSError, ValueError):
            # A malformed Research configuration should not stop local Term Discovery;
            # an explicit override remains available as a bounded Focus.
            pass
    return list(dict.fromkeys(item.strip() for item in focus if item.strip()))[:20]


def _empty_learning_preferences() -> dict:
    return {
        "fixed_direction": "",
        "keywords": [],
        "exclude_keywords": [],
        "exploration_directions": [],
        "important_anchors": [],
    }


def _bounded_term_preferences(value: dict) -> dict:
    defaults = _empty_learning_preferences()
    if not isinstance(value, dict):
        value = {}
    fixed_direction = value.get("fixed_direction", "")
    defaults["fixed_direction"] = (
        " ".join(fixed_direction.split())[:300]
        if isinstance(fixed_direction, str)
        else ""
    )
    for field in (
        "keywords",
        "exclude_keywords",
        "exploration_directions",
        "important_anchors",
    ):
        entries = value.get(field, [])
        if not isinstance(entries, list):
            continue
        seen = set()
        for entry in entries:
            if not isinstance(entry, str):
                continue
            cleaned = " ".join(entry.split())[:160]
            folded = cleaned.casefold()
            if cleaned and folded not in seen:
                defaults[field].append(cleaned)
                seen.add(folded)
            if len(defaults[field]) >= MAX_TERM_PREFERENCE_ITEMS:
                break
    return defaults


def _term_focus_seed(
    base_focus: list[str],
    preferences: dict,
    matched_topics: Optional[list[str]] = None,
    focus_override: Optional[str] = None,
) -> list[str]:
    values = [focus_override or "", preferences.get("fixed_direction", "")]
    values.extend(preferences.get("keywords", [])[:MAX_TERM_PREFERENCE_ITEMS])
    values.extend(matched_topics or [])
    values.extend(base_focus)
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        cleaned = " ".join(value.split())
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= 40:
            break
    return result


def _learning_context_query(
    base_focus: list[str], preferences: dict, focus_override: Optional[str]
) -> str:
    values = [focus_override or "", preferences.get("fixed_direction", "")]
    values.extend(preferences.get("keywords", [])[:MAX_TERM_PREFERENCE_ITEMS])
    if not any(isinstance(value, str) and value.strip() for value in values):
        values = base_focus[:4]
    return " ".join(
        dict.fromkeys(
            " ".join(value.split())
            for value in values
            if isinstance(value, str) and value.strip()
        )
    )[:1200]


def _learning_context_headings(learning_context: dict) -> list[str]:
    from backend.app.services.learning_context_sync_entries import entry_blocks

    markdown_files = [
        learning_context.get("active", ""),
        learning_context.get("important", ""),
        *[
            item.get("markdown", "")
            for item in learning_context.get("topics", [])
            if isinstance(item, dict)
        ],
    ]
    selected_source_ids = learning_context.get("selected_source_ids")
    selected_source_ids = (
        {item for item in selected_source_ids if isinstance(item, str)}
        if isinstance(selected_source_ids, list)
        else set()
    )
    if not selected_source_ids:
        return []
    headings = []
    seen = set()
    for markdown in markdown_files:
        if not isinstance(markdown, str):
            continue
        for block in entry_blocks(markdown):
            metadata = block["metadata"]
            if (
                metadata.get("entry_id") == "current-learning-focus"
                or metadata.get("support_state") in {"needs_review", "source_removed"}
            ):
                continue
            source_headings = metadata.get("source_headings", {})
            if not isinstance(source_headings, dict):
                continue
            supported_sources = set(source_headings) & selected_source_ids
            source_summaries = metadata.get("source_summaries")
            if isinstance(source_summaries, dict):
                evidence = [
                    source_summaries[source_id]
                    for source_id in sorted(supported_sources & set(source_summaries))
                    if isinstance(source_summaries.get(source_id), str)
                ]
            else:
                # A legacy merged summary cannot be attributed safely if any
                # of its sources are outside the selected evidence scope.
                if not supported_sources or set(source_headings) - selected_source_ids:
                    continue
                summary = metadata.get("summary", "")
                evidence = [summary] if isinstance(summary, str) else []
            if not supported_sources or not evidence:
                continue

            entry_headings = [metadata.get("title", "")]
            for summary in evidence:
                entry_headings.extend(
                    match.group(1).strip()
                    for line in summary.splitlines()
                    if (
                        match := re.match(
                            r"^\s{0,3}#{3,6}\s+(.+?)\s*#*\s*$", line
                        )
                    )
                )
            for title in entry_headings:
                key = _normalized_term_phrase(title)
                if key and key not in seen:
                    headings.append(title[:200])
                    seen.add(key)
                if len(headings) >= 40:
                    return headings
    return headings


def _term_name_variants(value: str) -> set[str]:
    if not isinstance(value, str):
        return set()
    variants = {value}
    aliases = re.findall(r"\(([^()]*)\)", value)
    base = re.sub(r"\s*\([^()]*\)", " ", value).strip()
    if base:
        variants.add(base)
    variants.update(alias.strip() for alias in aliases if alias.strip())
    return {
        normalized
        for normalized in (_normalized_term_phrase(item) for item in variants)
        if normalized
    }


def _normalized_term_phrase(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(
        re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", value.casefold())
    )


def _contains_term_phrase(text: str, phrase: str) -> bool:
    normalized_text = _normalized_term_phrase(text)
    normalized_phrase = _normalized_term_phrase(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    return " {} ".format(normalized_phrase) in " {} ".format(normalized_text)


def _excluded_by_preferences(mention: str, preferences: dict) -> bool:
    return any(
        _contains_term_phrase(mention, item)
        for item in preferences.get("exclude_keywords", [])
        if isinstance(item, str)
    )


def _covered_by_learning_context(
    mention: str, learning_context: dict, resolver: Optional[TermResolver] = None
) -> bool:
    mention_variants = _term_name_variants(mention)
    if not mention_variants:
        return False
    if resolver is not None:
        resolution = resolver.resolve(mention)
        if resolution.status == "resolved":
            term = resolver.registry.get(resolution.entity_id)
            if term is not None:
                for value in (term.title, *term.aliases):
                    mention_variants.update(_term_name_variants(value))

    if any(
        bool(mention_variants & _term_name_variants(heading))
        for heading in learning_context.get("covered_term_headings", [])
    ):
        return True

    return False


def _selected_document_scope(
    learning_context: dict, discovery_mode: str = "personalized"
) -> Optional[set[str]]:
    if discovery_mode == "general":
        return None
    selected_source_ids = learning_context.get("selected_source_ids")
    if not isinstance(selected_source_ids, list):
        return set()
    selected = {
        source_id
        for source_id in selected_source_ids
        if isinstance(source_id, str) and source_id.strip()
    }
    return selected


def _discovery_focus(
    explicit_focus: list[str], snapshot: dict, focus_override: Optional[str] = None
) -> list[str]:
    profile_focus = list(explicit_focus)
    override = " ".join((focus_override or "").split())
    if (
        override
        and profile_focus
        and " ".join(profile_focus[0].split()).casefold() == override.casefold()
    ):
        profile_focus = profile_focus[1:]
    # Recent opens, links, and PDF exposure remain separate Knowledge State
    # signals. They are not evidence for this reader's learning direction.
    focus = ([override] if override else []) + profile_focus
    return list(dict.fromkeys(value.strip() for value in focus if value.strip()))[:40]


def _term_document_analysis_hash(metadata: DocumentMetadata, body: str) -> str:
    encoded = json.dumps(
        {
            "title": metadata.title,
            "type": metadata.type,
            "domains": metadata.domains,
            "topics": metadata.topics,
            "body": _normalize_term_analysis_markdown(body),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_term_analysis_markdown(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    literals = []
    literal_tokens = set()

    def save_literal(value):
        index = len(literals)
        literals.append(value)
        token = "\x00TERM_ANALYSIS_LITERAL_{}\x00".format(index)
        literal_tokens.add(token)
        return token

    def protect(pattern):
        nonlocal text

        def replace(match):
            return save_literal(match.group(0))

        text = pattern.sub(replace, text)

    def protect_fenced_code():
        nonlocal text
        protected_lines = []
        code_lines = []
        fence_char = None
        min_fence_length = 0
        for line in text.splitlines(keepends=True):
            if fence_char is None:
                opening = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
                if opening and not (
                    opening.group(1).startswith("`")
                    and "`" in opening.group(2)
                ):
                    marker = opening.group(1)
                    fence_char = marker[0]
                    min_fence_length = len(marker)
                    code_lines = [line]
                else:
                    protected_lines.append(line)
                continue

            code_lines.append(line)
            closing = re.match(r"^ {0,3}(`+|~+)[ \t]*(?:\n)?$", line)
            if (
                closing
                and closing.group(1)[0] == fence_char
                and len(closing.group(1)) >= min_fence_length
            ):
                block = "".join(code_lines)
                trailing_newline = "\n" if block.endswith("\n") else ""
                if trailing_newline:
                    block = block[:-1]
                protected_lines.append(save_literal(block) + trailing_newline)
                code_lines = []
                fence_char = None
                min_fence_length = 0

        if code_lines:
            protected_lines.append(save_literal("".join(code_lines)))
        text = "".join(protected_lines)

    protect_fenced_code()
    protect(
        re.compile(
            r"(?m)(?:^(?: {4}|\t).*(?:\n|$))+(?:^[ \t]*\n"
            r"(?: {4}|\t).*(?:\n|$))*"
        )
    )
    protect(
        re.compile(
            r"(?s)\\\[.*?\\\]|\\\(.*?\\\)|"
            r"(?<!\\)\$\$.*?(?<!\\)\$\$|"
            r"(?<!\\)\$(?!\$)[^$\n]+(?<!\\)\$"
        )
    )
    protect(re.compile(r"(?s)(?P<ticks>`+)(?!`).*?(?<!`)(?P=ticks)(?!`)"))

    emphasis_operator = re.compile(r"[=<>≤≥≠^+*/×÷∑∏∫−\\]")

    def remove_emphasis(match):
        content = match.group(match.lastindex)
        return match.group(0) if emphasis_operator.search(content) else content

    text = re.sub(
        r"(?<!\w)(\*\*|__)(?!\s)(.+?)(?<!\s)\1(?!\w)",
        remove_emphasis,
        text,
    )
    text = re.sub(
        r"(?<![\w*])\*(?!\*)(?!\s)(.+?)(?<!\s)\*(?!\*)",
        remove_emphasis,
        text,
    )
    text = re.sub(
        r"(?<![\w_])_(?!_)(?!\s)(.+?)(?<!\s)_(?![\w_])",
        remove_emphasis,
        text,
    )

    normalized_lines = []
    for line in text.split("\n"):
        leading = re.match(r"^[ \t]*", line).group(0)
        content = line[len(leading) :]
        normalized_lines.append(leading + re.sub(r"[ \t]+", " ", content).rstrip())

    blocks = []
    paragraph_lines = []

    def flush_paragraph():
        if paragraph_lines:
            blocks.append(" ".join(paragraph_lines))
            paragraph_lines.clear()

    structural_line = re.compile(
        r"^(?: {0,3}#{1,6}(?:\s|$)| {0,3}(?:[-*+]|\d+[.)])\s|"
        r" {0,3}>| {0,3}\|| {0,3}<| {4}|\t|[-*_]{3,}\s*$)"
    )
    for line in normalized_lines:
        if not line.strip():
            flush_paragraph()
        elif structural_line.match(line) or line.strip() in literal_tokens:
            flush_paragraph()
            blocks.append(line.rstrip())
        else:
            paragraph_lines.append(line.strip())
    flush_paragraph()

    text = "\n\n".join(blocks)
    for index, literal in enumerate(literals):
        text = text.replace("\x00TERM_ANALYSIS_LITERAL_{}\x00".format(index), literal)
    return text


def _select_documents(
    repository_root: Path,
    repository: TermDiscoveryRepository,
    enabled_lanes: list[DiscoveryLane],
    focus: list[str],
    snapshot: dict,
    focus_hash: str,
    registry: TermRegistry,
    selected_document_ids: Optional[set[str]] = None,
) -> list[DiscoveryCorpus]:
    note_lanes = tuple(
        lane for lane in enabled_lanes if lane in {"concept", "entity"}
    )
    if not note_lanes:
        return []
    documents_root = (repository_root / "knowledge" / "documents").resolve()
    if not documents_root.is_dir():
        return []
    focus_tokens = set(_tokens(" ".join(focus)))
    recent_rank = {
        item["id"]: index
        for index, item in enumerate(snapshot.get("activity", {}).get("recent_documents", []))
    }
    resolver = TermResolver(registry)
    candidates = []
    for path in documents_root.rglob("*.md"):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(documents_root):
                continue
            modified_at = path.stat().st_mtime
            payload = path.read_bytes()
            content = payload.decode("utf-8")
            parsed = parse_markdown(content)
            metadata = DocumentMetadata.model_validate(parsed.frontmatter)
            if path.stem != metadata.id:
                continue
            if (
                selected_document_ids is not None
                and metadata.id not in selected_document_ids
            ):
                continue
            relative = path.relative_to(documents_root)
            expected_directory = {
                "paper-note": "papers",
                "learning-note": "learning",
                "course-note": "courses",
            }[metadata.type]
            if len(relative.parts) != 2 or relative.parts[0] != expected_directory:
                continue
            body = "\n".join(
                content.splitlines()[parsed.frontmatter_end_line or 0 :]
            ).strip()
            if not any(
                not re.match(r"^\s{0,3}#{1,6}(?:\s|$)", line)
                and re.search(r"\w", line)
                for line in body.splitlines()
            ):
                continue
        except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError):
            continue

        analysis_id = "document:{}".format(metadata.id)
        states = [
            repository.get_analysis_state(analysis_id, lane) for lane in note_lanes
        ]
        text_hash = _term_document_analysis_hash(metadata, body)
        if all(
            state is not None
            and state["text_hash"] == text_hash
            and state["focus_hash"] == focus_hash
            and state["analysis_version"] == DISCOVERY_ANALYSIS_VERSION
            for state in states
        ):
            continue
        linked_terms = []
        for link in parsed.wiki_links:
            resolution = resolver.resolve(link.target)
            if resolution.status == "resolved":
                term = registry.get(resolution.entity_id)
                if term is not None:
                    linked_terms.append(term.title)
        searchable = " ".join(
            [metadata.title, *metadata.domains, *metadata.topics, *linked_terms]
        )
        relevance = len(focus_tokens & set(_tokens(searchable)))
        context = _DocumentContext(
            id=metadata.id,
            title=metadata.title,
            domains=tuple(metadata.domains),
            topics=tuple(metadata.topics),
        )
        candidates.append(
            (
                -relevance,
                recent_rank.get(metadata.id, MAX_RECENT_DOCUMENTS + 1),
                -modified_at,
                metadata.id,
                DiscoveryCorpus(
                    "document",
                    metadata.id,
                    context,
                    body,
                    text_hash,
                    analysis_id,
                    note_lanes,
                ),
            )
        )
    candidates.sort(key=lambda item: item[:4])
    return [item[4] for item in candidates[:MAX_DOCUMENTS_PER_RUN]]


def _select_sources(
    registry,
    preferences,
    focus,
    repository_root,
    repository,
    pdf_corpus_service,
    enabled_lanes,
    focus_hash,
):
    preferred_rank = {source_id: index for index, source_id in enumerate(preferences)}
    focus_tokens = set(_tokens(" ".join(focus)))
    sources = []
    for source in registry.sources:
        if not source.attachments.local_pdf:
            continue
        path = repository_root / "storage" / "papers" / "{}.pdf".format(source.id)
        if not path.is_file():
            continue
        corpus = pdf_corpus_service.get(source.id)
        pending = corpus is None
        if corpus is not None:
            try:
                current_hash = sha256(path.read_bytes()).hexdigest()
            except OSError:
                current_hash = ""
            pending = current_hash != corpus.pdf_hash or corpus.status == "failed"
            if corpus.status == "unavailable" and current_hash == corpus.pdf_hash:
                continue
            if corpus.status == "ready" and current_hash == corpus.pdf_hash:
                pending = any(
                    (
                        (state := repository.get_analysis_state(source.id, lane)) is None
                        or state["text_hash"] != corpus.text_hash
                        or state["focus_hash"] != focus_hash
                        or state["analysis_version"] != DISCOVERY_ANALYSIS_VERSION
                    )
                    for lane in enabled_lanes
                )
        title_tokens = set(_tokens("{} {}".format(source.title, " ".join(source.authors))))
        overlap = len(focus_tokens & title_tokens)
        preference_rank = preferred_rank.get(source.id, len(preferences) + 1)
        sources.append((source, int(not pending), preference_rank, overlap))
    sources.sort(
        key=lambda item: (
            item[1],
            item[2],
            -item[3],
            item[0].year or 0,
            item[0].id,
        )
    )
    return [item[0] for item in sources[:MAX_SOURCES_PER_RUN]]


def _select_relevant_excerpt(text: str, focus: list[str]) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return text[:MAX_TEXT_CHARS_PER_REQUEST]
    focus_tokens = set(_tokens(" ".join(focus)))
    ranked = sorted(
        enumerate(paragraphs),
        key=lambda item: (
            -len(focus_tokens & set(_tokens(item[1]))),
            item[0],
        ),
    )
    selected = []
    used = 0
    for _, paragraph in ranked:
        excerpt = paragraph[:1800]
        if used + len(excerpt) + 2 > MAX_TEXT_CHARS_PER_REQUEST:
            continue
        selected.append(excerpt)
        used += len(excerpt) + 2
        if used >= MAX_TEXT_CHARS_PER_REQUEST:
            break
    if not selected:
        selected = [paragraphs[0][:MAX_TEXT_CHARS_PER_REQUEST]]
    return "\n\n".join(selected)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", text.casefold())


def _json_hash(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _term_discovery_focus_hash(focus: list[str], snapshot: dict, learning_context: dict) -> str:
    return _json_hash(
        {
            "focus": focus,
            "knowledge": snapshot.get("knowledge", {}),
            "reviewed_scopes": [
                item
                for item in snapshot.get("registry", [])
                if item.get("state") == "established" and item.get("content_excerpt")
            ][:20],
            "term_states": snapshot.get("term_states", {}),
            "learning_context": learning_context,
        }
    )


def _external_query(focus: list[str]) -> str:
    phrases = []
    for value in focus:
        normalized = " ".join(value.split())
        if normalized and normalized not in phrases:
            phrases.append(normalized)
        if len(phrases) >= MAX_EXTERNAL_QUERY_FOCUS_ITEMS:
            break
    return " ".join(phrases)[:180]


def _is_wikipedia_result_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.netloc == "en.wikipedia.org"
        and parsed.path.startswith("/wiki/")
        and not parsed.query
        and not parsed.fragment
    )


def _term_excerpt(text: str, term: str, maximum: int = 300) -> str:
    match = re.search(re.escape(term), text, flags=re.IGNORECASE)
    if match is None:
        return ""
    start = max(0, match.start() - maximum // 2)
    end = min(len(text), match.end() + maximum // 2)
    return text[start:end].strip()
