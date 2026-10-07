"""Bounded, Focus-aware Term Discovery over the existing local corpus."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import uuid
from typing import Callable, Optional

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
)
from backend.app.repositories.term_discovery_repository import TermDiscoveryRepository
from backend.app.services.ai_client import AIGatewayError, AIResponseError
from backend.app.services.knowledge_state_service import KnowledgeStateService
from backend.app.services.research_lock import GlobalResearchLock
from backend.app.services.resolution import normalize_key
from backend.app.services.source_registry import SourceRegistry
from backend.app.services.term_candidate_service import (
    TermCandidateConflict,
    TermCandidateService,
)
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver
from backend.app.services.vocabulary_mining import mine_vocabulary


DISCOVERY_ANALYSIS_VERSION = 1
GLOBAL_OPEN_CAPACITY = 12
MAX_SOURCES_PER_RUN = 3
MAX_TEXT_CHARS_PER_REQUEST = 12_000
MAX_VOCABULARY_OPTIONS = 20
_LANE_ORDER: tuple[DiscoveryLane, ...] = ("concept", "entity", "vocabulary")


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
    ):
        self.repository_root = Path(repository_root).resolve()
        self.repository = repository
        self.pdf_corpus_service = pdf_corpus_service
        self.candidate_service = candidate_service
        self.ai_gateway = ai_gateway
        self.clock = clock
        self._lock = GlobalResearchLock(
            self.repository_root / "runtime" / "term-discovery.lock"
        )
        self.knowledge_state = knowledge_state_service or KnowledgeStateService(
            self.repository_root, repository.connection, clock
        )

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
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        daily_remaining = max(
            0,
            settings.daily_max_new - self.repository.daily_candidate_count(day_start),
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

    def run(self, trigger: str = "manual") -> TermDiscoveryRun:
        if trigger not in {"manual", "scheduled"}:
            raise ValueError("Term Discovery trigger must be manual or scheduled")
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
            )
        try:
            return self._run_locked(trigger, started_at, run_id)
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
            )
        finally:
            self._lock.release()

    def scheduled_check(self) -> Optional[TermDiscoveryRun]:
        now = self._datetime()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        if self.repository.has_scheduled_run_since(day_start):
            return None
        source_registry = SourceRegistry.load(
            self.repository_root / "knowledge" / "sources"
        )
        if not any(
            source.attachments.local_pdf
            and (
                self.repository_root
                / "storage"
                / "papers"
                / "{}.pdf".format(source.id)
            ).is_file()
            for source in source_registry.sources
        ):
            return None
        return self.run(trigger="scheduled")

    def _run_locked(
        self, trigger: str, started_at: str, run_id: str
    ) -> TermDiscoveryRun:
        settings = self.repository.get_settings()
        open_count = self.repository.open_candidate_count()
        day_start = started_at[:10] + "T00:00:00+00:00"
        daily_remaining = max(
            0,
            settings.daily_max_new - self.repository.daily_candidate_count(day_start),
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
            )

        allocated_budgets = dict(budgets)
        remaining_budgets = dict(budgets)

        focus = _focus_context(self.repository_root, settings)
        snapshot = self.knowledge_state.build_snapshot(focus)
        focus = _discovery_focus(focus, snapshot)
        focus_hash = _json_hash(
            {
                "focus": focus,
                "knowledge": snapshot.get("knowledge", {}),
                "activity": snapshot.get("activity", {}),
                "term_states": snapshot.get("term_states", {}),
            }
        )
        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        resolver = TermResolver(registry)
        source_registry = SourceRegistry.load(
            self.repository_root / "knowledge" / "sources"
        )
        sources = _select_sources(
            source_registry,
            settings.source_preferences,
            focus,
            self.repository_root,
            self.repository,
            self.pdf_corpus_service,
            enabled_lanes,
            focus_hash,
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
        created_count = 0

        if not sources:
            return self._finish_run(
                run_id,
                trigger,
                "success",
                started_at,
                snapshot,
                budgets,
                raw_counts,
                filtered_counts,
                0,
                items,
                None,
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

            statistics = mine_vocabulary(corpus.text)
            self.repository.replace_vocabulary_source_statistics(
                source.id, corpus.text_hash, statistics, self._now()
            )
            for lane in _LANE_ORDER:
                if remaining_budgets[lane] <= 0:
                    continue
                state = self.repository.get_analysis_state(source.id, lane)
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
                        source,
                        corpus.text,
                        snapshot,
                        focus,
                        registry,
                        resolver,
                    )
                except AIGatewayError as error:
                    errors.append("{} {}: {}".format(source.id, lane, str(error)[:220]))
                    continue
                except Exception as error:
                    errors.append("{} {}: {}".format(source.id, lane, str(error)[:220]))
                    continue

                raw_counts[lane] += len(suggestions)
                lane_created = 0
                for suggestion in suggestions:
                    if suggestion.term_type != lane:
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id, lane, source.id, suggestion, "filtered", None
                            )
                        )
                        continue
                    if suggestion.mention.casefold() not in corpus.text.casefold():
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id, lane, source.id, suggestion, "filtered", None
                            )
                        )
                        continue
                    if (
                        suggestion.mention.casefold()
                        not in suggestion.context_excerpt.casefold()
                        or suggestion.context_excerpt not in corpus.text
                    ):
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id, lane, source.id, suggestion, "filtered", None
                            )
                        )
                        continue
                    if suggestion.existing_term_id and registry.get(suggestion.existing_term_id) is None:
                        errors.append(
                            "{} {} referenced unknown Term id {}".format(
                                source.id, lane, suggestion.existing_term_id
                            )
                        )
                        filtered_counts[lane] += 1
                        continue
                    assessment = TermDiscoveryAssessment(
                        readiness=suggestion.readiness,
                        recommendation_level=suggestion.recommendation_level,
                        known_prerequisites=suggestion.known_prerequisites,
                        missing_prerequisites=suggestion.missing_prerequisites,
                        why_now=suggestion.why_now,
                    )
                    if suggestion.recommendation_level == "stretch":
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id, lane, source.id, suggestion, "stretch", None
                            )
                        )
                        continue
                    if lane_created >= remaining_budgets[lane]:
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id, lane, source.id, suggestion, "filtered", None
                            )
                        )
                        continue
                    if self.repository.open_candidate_count() >= GLOBAL_OPEN_CAPACITY:
                        filtered_counts[lane] += 1
                        continue

                    normalized = normalize_key(suggestion.mention)
                    existing_open = self.candidate_service.repository.find_open_candidate(
                        normalized
                    )
                    registry_match = resolver.resolve(suggestion.mention)
                    if existing_open is not None and existing_open.suggested_type != lane:
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id, lane, source.id, suggestion, "duplicate", existing_open.id
                            )
                        )
                        continue
                    if registry_match.status == "ambiguous":
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id, lane, source.id, suggestion, "filtered", None
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
                    evidence = TermCandidateEvidenceInput(
                        origin_type="source",
                        origin_id=source.id,
                        mention=suggestion.mention,
                        context_excerpt=suggestion.context_excerpt,
                        confidence=suggestion.confidence,
                        rationale=suggestion.rationale,
                    )
                    try:
                        candidate = self.candidate_service.create_candidate(
                            suggestion.mention,
                            lane,
                            [evidence],
                            preferred_term_id=suggestion.existing_term_id,
                            discovery_assessment=assessment,
                        )
                    except (TermCandidateConflict, ValueError) as error:
                        filtered_counts[lane] += 1
                        items.append(
                            self._item(
                                run_id, lane, source.id, suggestion, "rejected", None
                            )
                        )
                        continue
                    if existing_open is None:
                        candidate_outcome = "created"
                        lane_created += 1
                        created_count += 1
                    else:
                        candidate_outcome = "duplicate"
                        filtered_counts[lane] += 1
                    items.append(
                        self._item(
                            run_id,
                            lane,
                            source.id,
                            suggestion,
                            candidate_outcome,
                            candidate.id,
                        )
                    )
                self.repository.save_analysis_state(
                    source.id,
                    corpus.text_hash,
                    focus_hash,
                    lane,
                    DISCOVERY_ANALYSIS_VERSION,
                    self._now(),
                )
                remaining_budgets[lane] = max(
                    0, remaining_budgets[lane] - lane_created
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
        )

    def _discover_for_lane(
        self,
        lane: DiscoveryLane,
        source,
        corpus_text: str,
        snapshot: dict,
        focus: list[str],
        registry: TermRegistry,
        resolver: TermResolver,
    ) -> list:
        context = {
            "lane": lane,
            "focus": focus,
            "knowledge_state": {
                "focus": snapshot.get("focus", {}),
                "knowledge": snapshot.get("knowledge", {}),
                "exposure": snapshot.get("exposure", {}),
                "activity": snapshot.get("activity", {}),
            },
            "term_registry": [
                {"id": term.id, "title": term.title, "aliases": list(term.aliases[:8]), "type": term.type}
                for term in registry.terms[:200]
            ],
            "source": {
                "id": source.id,
                "title": source.title,
                "authors": source.authors[:3],
                "year": source.year,
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
    ) -> TermDiscoveryRun:
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


def _discovery_focus(explicit_focus: list[str], snapshot: dict) -> list[str]:
    focus = list(explicit_focus)
    focus_state = snapshot.get("focus", {})
    focus.extend(focus_state.get("recent_topics", []))
    focus.extend(focus_state.get("recent_domains", []))
    focus.extend(
        item.get("title", "")
        for item in focus_state.get("recent_terms", [])
        if isinstance(item, dict)
    )
    return list(dict.fromkeys(value.strip() for value in focus if value.strip()))[:40]


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


def _term_excerpt(text: str, term: str, maximum: int = 300) -> str:
    match = re.search(re.escape(term), text, flags=re.IGNORECASE)
    if match is None:
        return ""
    start = max(0, match.start() - maximum // 2)
    end = min(len(text), match.end() + maximum // 2)
    return text[start:end].strip()
