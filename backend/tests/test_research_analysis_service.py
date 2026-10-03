from datetime import datetime, timezone

import pytest

from backend.app.db.connection import connect_database
from backend.app.domain.ai import ResearchCandidateAnalysisOutput
from backend.app.domain.research import ResearchProfile
from backend.app.domain.research_runtime import (
    ResearchContextCard,
    ResearchContextPack,
    ResearchWorkRecord,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.ai_client import (
    AIProviderError,
    AIResponseError,
    MockDeepSeekClient,
)
from backend.app.services.ai_gateway import AIGateway
from backend.app.services.research_analysis_service import (
    ResearchAnalysisCircuitBreaker,
    ResearchAnalysisService,
)


def test_research_analysis_is_structured_cached_and_profile_scoped():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    client = MockDeepSeekClient(
        {"research_candidate_analysis": _analysis_output()}
    )
    service = ResearchAnalysisService(
        repository,
        AIGateway(client),
        clock=lambda: datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc),
    )
    profile = _profile()
    pack = _context_pack()

    first = service.analyze(work, profile, profile.lenses[0], pack)
    second = service.analyze(work, profile, profile.lenses[0], pack)

    assert first is not None
    assert first.id == second.id
    assert first.outcome == "surface"
    assert first.provider == "mock"
    assert first.model == "mock"
    assert first.context_entity_ids == ("document:ewc",)
    assert isinstance(first.analysis, ResearchCandidateAnalysisOutput)
    assert client.calls == ["research_candidate_analysis"]
    assert connection.execute(
        "SELECT COUNT(*) FROM research_work_analyses"
    ).fetchone()[0] == 1
    connection.close()


def test_research_analysis_hash_tracks_context_and_disabled_consent_skips_ai():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    client = MockDeepSeekClient(
        {"research_candidate_analysis": _analysis_output()}
    )
    service = ResearchAnalysisService(repository, AIGateway(client))
    profile = _profile()
    pack = _context_pack()
    changed_pack = pack.model_copy(
        update={
            "cards": (
                pack.cards[0].model_copy(
                    update={
                        "relevant_sections": (
                            pack.cards[0].relevant_sections[0].model_copy(
                                update={"excerpt": "Updated context passage."}
                            ),
                        )
                    }
                ),
            )
        }
    )

    first = service.analyze(work, profile, profile.lenses[0], pack)
    changed = service.analyze(work, profile, profile.lenses[0], changed_pack)
    disabled_profile = profile.model_copy(
        update={
            "ai_analysis": profile.ai_analysis.model_copy(update={"enabled": False})
        }
    )
    skipped = service.analyze(work, disabled_profile, disabled_profile.lenses[0], pack)

    assert first is not None and changed is not None
    assert first.input_hash != changed.input_hash
    assert skipped is None
    assert client.calls == ["research_candidate_analysis", "research_candidate_analysis"]
    connection.close()


def test_research_analysis_rejects_relations_outside_the_context_pack():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    output = _analysis_output()
    output["existing_relations"] = [
        {
            "entity_type": "document",
            "entity_id": "not-in-context",
            "relation": "extends",
            "reason": "The model invented an entity.",
        }
    ]
    client = MockDeepSeekClient({"research_candidate_analysis": output})
    service = ResearchAnalysisService(repository, AIGateway(client))
    profile = _profile()

    with pytest.raises(AIResponseError, match="outside its Context Pack"):
        # The output is schema-valid but its entity reference must still be rejected.
        service.analyze(work, profile, profile.lenses[0], _context_pack())

    connection.close()


def test_research_analysis_schema_rejects_out_of_range_scores():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    output = _analysis_output()
    output["profile_relevance"] = 1.1
    client = MockDeepSeekClient({"research_candidate_analysis": output})
    service = ResearchAnalysisService(repository, AIGateway(client))
    profile = _profile()

    with pytest.raises(AIResponseError, match="JSON schema"):
        service.analyze(work, profile, profile.lenses[0], _context_pack())

    assert connection.execute(
        "SELECT COUNT(*) FROM research_work_analyses"
    ).fetchone()[0] == 0
    connection.close()


def test_run_circuit_breaker_opens_after_three_transient_failures():
    breaker = ResearchAnalysisCircuitBreaker()
    calls = []

    def unavailable():
        calls.append("attempt")
        raise AIProviderError("temporary outage", transient=True)

    for _ in range(3):
        with pytest.raises(AIProviderError):
            breaker.call(unavailable)

    assert breaker.analysis_disabled_for_run is True
    assert breaker.consecutive_transient_failures == 3
    assert breaker.call(unavailable) is None
    assert len(calls) == 3


def test_non_transient_failure_breaks_a_transient_failure_streak():
    breaker = ResearchAnalysisCircuitBreaker()

    with pytest.raises(AIProviderError):
        breaker.call(lambda: _raise_provider_error(transient=True))
    with pytest.raises(AIProviderError):
        breaker.call(lambda: _raise_provider_error(transient=True))
    with pytest.raises(AIProviderError):
        breaker.call(lambda: _raise_provider_error(transient=False))

    assert breaker.consecutive_transient_failures == 0
    assert breaker.analysis_disabled_for_run is False


def _work():
    return ResearchWorkRecord(
        id="work-1",
        canonical_key="doi:10.1000/work-1",
        title="Fisher Information for Continual Learning",
        normalized_title="fisher information for continual learning",
        abstract="Parameter importance helps prevent forgetting.",
        authors=("Ada Lovelace",),
        year=2026,
        published_at="2026-10-01",
        doi="10.1000/work-1",
        created_at="2026-10-03T12:00:00+00:00",
        updated_at="2026-10-03T12:00:00+00:00",
    )


def _profile(enabled=True):
    return ResearchProfile.model_validate(
        {
            "schema_version": 1,
            "id": "continual-learning",
            "title": "Continual Learning",
            "enabled": True,
            "lenses": [
                {
                    "id": "regularization",
                    "title": "Regularization",
                    "enabled": True,
                    "priority": "high",
                    "queries": ["fisher information"],
                    "include_terms": ["fisher information"],
                    "exclude_terms": [],
                }
            ],
            "exclude_terms": [],
            "providers": {"discovery": ["arxiv"], "enrichment": []},
            "context": {
                "collections": ["research-core"],
                "documents": ["ewc"],
                "dynamic_retrieval": {"enabled": True, "scope": "entire-library"},
            },
            "schedule": {"mode": "daily"},
            "search": {
                "breadth": "balanced",
                "initial_lookback_days": 30,
                "max_catchup_days": 30,
                "max_candidates_per_run": 10,
                "max_analyses_per_run": 30,
            },
            "inbox": {"max_new_candidates": 20},
            "ai_analysis": {"enabled": enabled, "provider": "deepseek"},
        }
    )


def _context_pack():
    return ResearchContextPack(
        focus_query="Fisher Information for Continual Learning",
        cards=(
            ResearchContextCard(
                entity_type="document",
                entity_id="ewc",
                title="Elastic Weight Consolidation",
                review_status="approved",
                topics=("continual-learning",),
                domains=("artificial-intelligence",),
                relevant_sections=(
                    {"heading": "Fisher Information", "excerpt": "A short context passage."},
                ),
                metadata={},
                pinned=True,
                retrieval_score=0.0,
            ),
        ),
        budget=8,
        omitted_count=0,
    )


def _analysis_output():
    return {
        "relevant": True,
        "profile_relevance": 0.91,
        "knowledge_relevance": 0.84,
        "novelty_to_library": 0.72,
        "matched_lenses": ["regularization"],
        "matched_topics": ["parameter importance"],
        "summary": "The paper studies parameter importance.",
        "why_relevant": "It matches the regularization lens.",
        "reading_reason": "It may clarify consolidation methods.",
        "existing_relations": [
            {
                "entity_type": "document",
                "entity_id": "ewc",
                "relation": "extends",
                "reason": "It extends the pinned EWC note.",
            }
        ],
        "suggested_collection": "research-core",
        "suggested_section": "Regularization",
    }


def _raise_provider_error(transient):
    raise AIProviderError("provider failure", transient=transient)
