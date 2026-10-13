"""Validated Research analysis with consent, caching, and run-local failure control."""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Callable, Optional
import uuid

from backend.app.domain.ai import (
    ResearchCandidateAnalysisAIOutput,
    ResearchCandidateAnalysisOutput,
)
from backend.app.domain.research import ResearchLens, ResearchProfile
from backend.app.domain.research_runtime import (
    ResearchContextPack,
    ResearchWorkAnalysisRecord,
    ResearchWorkRecord,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.ai_client import AIProviderError, AIResponseError
from backend.app.services.ai_gateway import AIGateway
from backend.app.services.knowledge_state_service import KnowledgeStateService
from backend.app.services.learning_context_service import LearningContextService
from backend.app.services.term_registry import TermRegistry


RESEARCH_ANALYSIS_PROMPT_VERSION = "research-candidate-analysis-v10"
RESEARCH_ANALYSIS_VERSION = 10
logger = logging.getLogger(__name__)


class ResearchAnalysisCircuitBreaker:
    """Stop Research AI calls after a run's consecutive transient failures."""

    def __init__(self, transient_failure_threshold: int = 3):
        if (
            isinstance(transient_failure_threshold, bool)
            or not isinstance(transient_failure_threshold, int)
            or transient_failure_threshold < 1
        ):
            raise ValueError("transient_failure_threshold must be a positive integer")
        self.transient_failure_threshold = transient_failure_threshold
        self.consecutive_transient_failures = 0
        self.analysis_disabled_for_run = False

    def call(self, operation: Callable[[], object]):
        if self.analysis_disabled_for_run:
            return None
        try:
            result = operation()
        except AIProviderError as error:
            if error.transient:
                self.consecutive_transient_failures += 1
                if self.consecutive_transient_failures >= self.transient_failure_threshold:
                    self.analysis_disabled_for_run = True
            else:
                self.consecutive_transient_failures = 0
            raise
        except Exception:
            self.consecutive_transient_failures = 0
            raise
        else:
            self.consecutive_transient_failures = 0
            return result


class ResearchAnalysisService:
    def __init__(
        self,
        repository: ResearchRepository,
        gateway: AIGateway,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        repository_root: Optional[Path] = None,
        learning_context_service: Optional[LearningContextService] = None,
    ):
        self.repository = repository
        self.gateway = gateway
        self.clock = clock
        self.repository_root = (
            Path(repository_root).expanduser().resolve()
            if repository_root is not None
            else None
        )
        self.learning_context_service = learning_context_service or (
            LearningContextService(self.repository_root)
            if self.repository_root is not None
            else None
        )

    def input_hash(
        self,
        work: ResearchWorkRecord,
        profile: ResearchProfile,
        matched_lens: ResearchLens,
        context_pack: ResearchContextPack,
        exploration_direction: Optional[str] = None,
    ) -> str:
        return _hash_analysis_input(
            self.build_analysis_input(
                work,
                profile,
                matched_lens,
                context_pack,
                exploration_direction=exploration_direction,
            )
        )

    def build_analysis_input(
        self,
        work: ResearchWorkRecord,
        profile: ResearchProfile,
        matched_lens: ResearchLens,
        context_pack: ResearchContextPack,
        exploration_direction: Optional[str] = None,
    ) -> dict:
        """Return the exact semantic payload sent to the Research analysis model."""
        _validate_lens(profile, matched_lens)
        breadth = profile.search.breadth
        readiness_context, term_registry = self._readiness_input(
            work, profile, matched_lens, context_pack
        )
        learning_progress_context = self._learning_progress_input(
            work, profile, matched_lens
        )
        return {
            "analysis_version": RESEARCH_ANALYSIS_VERSION,
            "prompt_version": RESEARCH_ANALYSIS_PROMPT_VERSION,
            "provider": self.gateway.provider,
            "model": self.gateway.model,
            "work": work.model_dump(
                mode="json", exclude={"created_at", "updated_at"}, exclude_none=True
            ),
            "profile": {
                "id": profile.id,
                "title": profile.title,
                "description": profile.description,
                "breadth": breadth,
                "breadth_policy": _breadth_policy(breadth),
                "allowed_collection_ids": list(profile.context.collections),
            },
            "matched_lens": matched_lens.model_dump(mode="json"),
            "knowledge_context": context_pack.model_dump(mode="json"),
            "readiness_context": readiness_context,
            "learning_progress_context": learning_progress_context,
            "query_scope": (
                {
                    "kind": "explicit_exploration",
                    "direction": exploration_direction,
                }
                if exploration_direction
                else {"kind": "profile"}
            ),
            "term_registry": term_registry,
        }

    def _learning_progress_input(self, work, profile, matched_lens):
        empty = {
            "included_source_count": 0,
            "included_sources": [],
            "preferences": {
                "fixed_direction": "",
                "keywords": [],
                "exclude_keywords": [],
                "exploration_directions": [],
                "important_anchors": [],
            },
            "active": "",
            "important": "",
            "topics": [],
        }
        if self.learning_context_service is None:
            return empty
        focus = "\n".join(
            value
            for value in (
                profile.title,
                profile.description or "",
                matched_lens.title,
                *matched_lens.queries,
                work.title,
                work.abstract or "",
            )
            if value
        )
        return self.learning_context_service.get_recommendation_context(focus)

    def _readiness_input(self, work, profile, matched_lens, context_pack):
        focus = [
            profile.title,
            profile.description or "",
            matched_lens.title,
            *matched_lens.queries,
            context_pack.focus_query,
        ]
        if self.repository_root is None:
            return {"explicit_focus": [value for value in focus if value][:12]}, []

        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        snapshot = KnowledgeStateService(
            self.repository_root, self.repository.connection
        ).build_snapshot(focus)
        selected_ids = {
            card.entity_id
            for card in context_pack.cards
            if card.entity_type == "term"
        }
        focus_tokens = set(_tokens(" ".join(focus + [work.title])))
        terms_by_state = {"established": [], "learning": [], "gaps": []}
        remaining_excerpt_slots = max(0, context_pack.budget - len(context_pack.cards))
        for term in snapshot["registry"]:
            term_tokens = set(_tokens(" ".join([term["title"], *term["aliases"]])))
            if term["id"] not in selected_ids and not (focus_tokens & term_tokens):
                continue
            state = term["state"]
            if state in {"established", "learning"}:
                if term["content_excerpt"]:
                    if term["id"] not in selected_ids:
                        if remaining_excerpt_slots <= 0:
                            continue
                        remaining_excerpt_slots -= 1
                    terms_by_state[state].append({"id": term["id"], "title": term["title"], "review_status": term["review_status"], "content_excerpt": term["content_excerpt"]})
            elif state in {"exposed", "unknown"}:
                terms_by_state["gaps"].append(
                    {"id": term["id"], "title": term["title"], "state": state}
                )
        readiness_context = {
            "explicit_focus": [value for value in focus if value][:12],
            "established_terms": terms_by_state["established"][:20],
            "learning_terms": terms_by_state["learning"][:20],
            "current_gaps": terms_by_state["gaps"][:20],
            "selected_term_ids": sorted(selected_ids)[:20],
        }
        term_registry = [
            {
                "id": term.id,
                "title": term.title,
                "aliases": list(term.aliases[:6]),
                "type": term.type,
            }
            for term in registry.terms[:200]
        ]
        return readiness_context, term_registry

    def analyze(
        self,
        work: ResearchWorkRecord,
        profile: ResearchProfile,
        matched_lens: ResearchLens,
        context_pack: ResearchContextPack,
        circuit_breaker: Optional[ResearchAnalysisCircuitBreaker] = None,
        on_attempt: Optional[Callable[[], None]] = None,
        exploration_direction: Optional[str] = None,
    ) -> Optional[ResearchWorkAnalysisRecord]:
        if not profile.ai_analysis.enabled:
            return None

        analysis_input = self.build_analysis_input(
            work,
            profile,
            matched_lens,
            context_pack,
            exploration_direction=exploration_direction,
        )
        input_hash = _hash_analysis_input(analysis_input)
        cached = self.repository.get_analysis(work.id, profile.id, input_hash)
        if cached is not None:
            return cached

        def invoke():
            if on_attempt is not None:
                on_attempt()
            return self.gateway.run("research_candidate_analysis", analysis_input)

        output = circuit_breaker.call(invoke) if circuit_breaker else invoke()
        if output is None:
            return None
        if not isinstance(output, ResearchCandidateAnalysisAIOutput):
            raise AIResponseError("Research analysis returned an unexpected output model")
        _validate_analysis_references(
            output,
            profile,
            matched_lens,
            context_pack,
            analysis_input["learning_progress_context"],
        )
        output = output.model_copy(update={
            "term_candidates": _validated_term_candidates(output, work, self.repository_root)
        })

        analyzed_at = self.clock()
        if analyzed_at.tzinfo is None or analyzed_at.utcoffset() is None:
            raise ValueError("Research analysis clock must return a timezone-aware datetime")
        analysis = ResearchWorkAnalysisRecord(
            id=uuid.uuid4().hex,
            work_id=work.id,
            profile_id=profile.id,
            input_hash=input_hash,
            outcome="surface" if output.relevant else "filtered",
            analysis=ResearchCandidateAnalysisOutput.model_validate(
                output.model_dump(mode="json")
            ),
            provider=self.gateway.provider,
            model=self.gateway.model,
            prompt_version=RESEARCH_ANALYSIS_PROMPT_VERSION,
            analysis_version=RESEARCH_ANALYSIS_VERSION,
            context_entity_ids=tuple(
                dict.fromkeys(
                    "{}:{}".format(card.entity_type, card.entity_id)
                    for card in context_pack.cards
                )
            ),
            input_context=analysis_input,
            analyzed_at=analyzed_at.astimezone(timezone.utc).isoformat(),
        )
        persisted, _ = self.repository.add_analysis_if_missing(analysis)
        return persisted


def _validate_lens(profile: ResearchProfile, matched_lens: ResearchLens) -> None:
    canonical = next(
        (lens for lens in profile.lenses if lens.id == matched_lens.id), None
    )
    if canonical is None or canonical != matched_lens:
        raise ValueError("Matched Lens does not belong to the Research Profile")


def _hash_analysis_input(analysis_input: dict) -> str:
    encoded = json.dumps(
        analysis_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _breadth_policy(breadth: str) -> str:
    return {
        "strict": (
            "Admit only work directly relevant to the selected Lens. "
            "Novelty alone or a merely adjacent topic is not sufficient."
        ),
        "balanced": (
            "Admit directly relevant work and clearly useful neighboring work. "
            "A neighboring topic must have a concrete connection to the selected Lens."
        ),
        "explore": (
            "Admit work with a clear connection to the selected Lens, including "
            "useful neighboring directions. Novelty alone never makes unrelated work relevant."
        ),
    }[breadth]


def _validate_analysis_references(
    output: ResearchCandidateAnalysisOutput,
    profile: ResearchProfile,
    matched_lens: ResearchLens,
    context_pack: ResearchContextPack,
    learning_progress_context: dict,
) -> None:
    profile_lenses = {lens.id for lens in profile.lenses}
    if any(lens_id not in profile_lenses for lens_id in output.matched_lenses):
        raise AIResponseError("Research analysis referenced an unknown Lens")
    if any(lens_id != matched_lens.id for lens_id in output.matched_lenses):
        raise AIResponseError(
            "Research analysis may reference only the selected Lens; other Lens hits remain Discovery provenance"
        )

    available_entities = {
        (card.entity_type, card.entity_id) for card in context_pack.cards
    }
    if any(
        (relation.entity_type, relation.entity_id) not in available_entities
        for relation in output.existing_relations
    ):
        raise AIResponseError("Research analysis referenced an entity outside its Context Pack")
    selected_sources = {
        (source["id"], source["title"])
        for source in learning_progress_context.get("included_sources", [])
    }
    source_references = [
        (source.id, source.title) for source in output.learning_context_sources
    ]
    if len(set(source_references)) != len(source_references) or any(
        source not in selected_sources for source in source_references
    ):
        raise AIResponseError(
            "Research analysis referenced a learning source outside the selected context"
        )

    allowed_collections = set(profile.context.collections)
    if (
        output.suggested_collection is not None
        and output.suggested_collection not in allowed_collections
    ):
        raise AIResponseError("Research analysis suggested a Collection outside the Profile context")
    if (
        output.suggested_collection is None
        and output.suggested_section is not None
    ):
        raise AIResponseError(
            "Research analysis suggested a Section without a Collection"
        )


def _validated_term_candidates(output, work, repository_root):
    registry = (
        TermRegistry.load(repository_root / "knowledge" / "terms")
        if repository_root is not None
        else None
    )
    work_text = " ".join((work.title, work.abstract or ""))
    normalized_work_text = " ".join(work_text.casefold().split())
    valid = []
    discarded = 0
    for candidate in output.term_candidates:
        excerpt = " ".join(candidate.context_excerpt.casefold().split())
        mention = " ".join(candidate.mention.casefold().split())
        if not excerpt or excerpt not in normalized_work_text or mention not in excerpt:
            reason = "evidence_not_in_work"
        elif candidate.existing_term_id and (
            registry is None or registry.get(candidate.existing_term_id) is None
        ):
            reason = "unknown_existing_term"
        else:
            valid.append(candidate)
            continue
        discarded += 1
        logger.warning("Research term discarded work_id=%s reason=%s count=%s",
                       work.id, reason, discarded)
    return valid


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", text.casefold())
