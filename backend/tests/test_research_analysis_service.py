from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from backend.app.db.connection import connect_database
from backend.app.domain.ai import ResearchCandidateAnalysisOutput
from backend.app.domain.research import ResearchLens, ResearchProfile
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
import backend.app.services.research_analysis_service as analysis_service_module


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
    attempts = []

    first = service.analyze(
        work, profile, profile.lenses[0], pack, on_attempt=lambda: attempts.append("call")
    )
    second = service.analyze(
        work, profile, profile.lenses[0], pack, on_attempt=lambda: attempts.append("call")
    )

    assert first is not None
    assert first.id == second.id
    assert first.outcome == "surface"
    assert first.provider == "mock"
    assert first.model == "mock"
    assert first.context_entity_ids == ("document:ewc",)
    assert isinstance(first.analysis, ResearchCandidateAnalysisOutput)
    assert first.analysis.summary_zh == "这篇论文研究参数重要性。"
    assert first.analysis.why_relevant_zh == "这与正则化研究主题相符。"
    assert first.analysis.reading_reason_zh == "这可能有助于理解巩固方法。"
    assert first.analysis.existing_relations[0].reason_zh == "它扩展了置顶的 EWC 笔记。"
    assert first.analysis_version == 6
    assert first.prompt_version == "research-candidate-analysis-v6"
    assert [
        (relation.entity_type, relation.entity_id)
        for relation in first.analysis.existing_relations
    ] == [("document", "ewc")]
    assert client.calls == ["research_candidate_analysis"]
    assert attempts == ["call"]
    sent_input = json.loads(client.messages[0][1]["content"])
    assert sent_input == service.build_analysis_input(
        work, profile, profile.lenses[0], pack
    )
    assert sent_input["profile"]["breadth"] == "balanced"
    assert sent_input["profile"]["breadth_policy"]
    assert sent_input["provider"] == first.provider
    assert sent_input["model"] == first.model
    assert first.input_context == sent_input
    assert second.input_context == sent_input
    assert json.loads(
        connection.execute(
            "SELECT input_context_json FROM research_work_analyses"
        ).fetchone()[0]
    ) == sent_input
    assert connection.execute(
        "SELECT COUNT(*) FROM research_work_analyses"
    ).fetchone()[0] == 1
    connection.close()


def test_research_analysis_with_empty_collection_context_sends_empty_allowlist():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    output = _analysis_output()
    output["suggested_collection"] = None
    output["suggested_section"] = None
    client = MockDeepSeekClient({"research_candidate_analysis": output})
    service = ResearchAnalysisService(repository, AIGateway(client))
    profile = _profile()
    profile = profile.model_copy(
        update={"context": profile.context.model_copy(update={"collections": []})}
    )

    analysis = service.analyze(work, profile, profile.lenses[0], _context_pack())

    assert analysis is not None
    sent_input = json.loads(client.messages[0][1]["content"])
    assert sent_input["profile"]["allowed_collection_ids"] == []
    assert analysis.analysis.suggested_collection is None
    assert analysis.analysis.suggested_section is None
    connection.close()


@pytest.mark.parametrize(
    ("collections", "suggested_collection", "suggested_section", "error"),
    [
        ([], "research-core", None, "outside the Profile context"),
        (["research-core"], "another-collection", None, "outside the Profile context"),
        (["research-core"], None, "Regularization", "Section without a Collection"),
    ],
)
def test_research_analysis_rejects_invalid_collection_suggestions(
    collections, suggested_collection, suggested_section, error
):
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    output = _analysis_output()
    output["suggested_collection"] = suggested_collection
    output["suggested_section"] = suggested_section
    client = MockDeepSeekClient({"research_candidate_analysis": output})
    service = ResearchAnalysisService(repository, AIGateway(client))
    profile = _profile()
    profile = profile.model_copy(
        update={
            "context": profile.context.model_copy(update={"collections": collections})
        }
    )

    with pytest.raises(AIResponseError, match=error):
        service.analyze(work, profile, profile.lenses[0], _context_pack())

    connection.close()


def test_research_analysis_accepts_a_suggested_collection_in_profile_context():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    output = _analysis_output()
    output["suggested_collection"] = "research-core"
    output["suggested_section"] = "Regularization"
    service = ResearchAnalysisService(
        repository,
        AIGateway(MockDeepSeekClient({"research_candidate_analysis": output})),
    )
    profile = _profile()

    analysis = service.analyze(work, profile, profile.lenses[0], _context_pack())

    assert analysis is not None
    assert analysis.analysis.suggested_collection == "research-core"
    assert analysis.analysis.suggested_section == "Regularization"
    connection.close()


def test_analysis_hash_uses_semantic_input_not_runtime_budgets_and_tracks_model(monkeypatch):
    connection = connect_database(":memory:")
    service = ResearchAnalysisService(
        ResearchRepository(connection),
        AIGateway(MockDeepSeekClient({"research_candidate_analysis": _analysis_output()})),
    )
    work = _work()
    profile = _profile()
    lens = profile.lenses[0]
    pack = _context_pack()
    original = service.input_hash(work, profile, lens, pack)

    runtime_only_change = profile.model_copy(
        update={
            "search": profile.search.model_copy(
                update={"max_analyses_per_run": 4, "max_candidates_per_run": 2}
            ),
            "inbox": profile.inbox.model_copy(update={"max_new_candidates": 3}),
        }
    )
    assert service.input_hash(work, runtime_only_change, lens, pack) == original

    service.gateway = SimpleNamespace(provider="deepseek", model="different-model")
    assert service.input_hash(work, profile, lens, pack) != original
    service.gateway = SimpleNamespace(provider="other-provider", model="mock")
    assert service.input_hash(work, profile, lens, pack) != original

    service.gateway = SimpleNamespace(provider="mock", model="mock")
    changed_lens = lens.model_copy(update={"queries": ["different query"]})
    changed_profile = profile.model_copy(update={"lenses": [changed_lens]})
    assert service.input_hash(work, changed_profile, changed_lens, pack) != original
    changed_breadth = profile.model_copy(
        update={"search": profile.search.model_copy(update={"breadth": "strict"})}
    )
    assert service.input_hash(work, changed_breadth, lens, pack) != original
    changed_pack = pack.model_copy(update={"omitted_count": 1})
    assert service.input_hash(work, profile, lens, changed_pack) != original

    monkeypatch.setattr(
        analysis_service_module,
        "RESEARCH_ANALYSIS_PROMPT_VERSION",
        "research-candidate-analysis-test",
    )
    assert service.input_hash(work, profile, lens, pack) != original
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
            "reason_zh": "模型编造了一个实体。",
        }
    ]
    client = MockDeepSeekClient({"research_candidate_analysis": output})
    service = ResearchAnalysisService(repository, AIGateway(client))
    profile = _profile()

    with pytest.raises(AIResponseError, match="outside its Context Pack"):
        # The output is schema-valid but its entity reference must still be rejected.
        service.analyze(work, profile, profile.lenses[0], _context_pack())

    connection.close()


def test_research_analysis_rejects_relation_with_matching_id_but_wrong_entity_type():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    output = _analysis_output()
    output["existing_relations"] = [
        {
            "entity_type": "term",
            "entity_id": "ewc",
            "relation": "related",
            "reason": "The identifier matches a context Document.",
            "reason_zh": "该标识与上下文中的文档相同。",
        }
    ]
    service = ResearchAnalysisService(
        repository,
        AIGateway(MockDeepSeekClient({"research_candidate_analysis": output})),
    )
    profile = _profile()
    work = _work()

    with pytest.raises(AIResponseError, match="outside its Context Pack"):
        service.analyze(work, profile, profile.lenses[0], _context_pack())

    assert connection.execute("SELECT COUNT(*) FROM research_work_analyses").fetchone()[0] == 0
    connection.close()


def test_research_analysis_accepts_empty_existing_relations():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    output = _analysis_output()
    output["existing_relations"] = []
    service = ResearchAnalysisService(
        repository,
        AIGateway(MockDeepSeekClient({"research_candidate_analysis": output})),
    )
    profile = _profile()

    analysis = service.analyze(work, profile, profile.lenses[0], _context_pack())

    assert analysis is not None
    assert analysis.analysis.existing_relations == []
    connection.close()


def test_research_analysis_rejects_a_different_profile_lens_as_matched():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    work = _work()
    repository.insert_work(work)
    profile = _profile()
    replay = ResearchLens.model_validate(
        {
            "id": "replay",
            "title": "Replay",
            "enabled": True,
            "priority": "medium",
            "queries": ["experience replay"],
            "include_terms": [],
            "exclude_terms": [],
        }
    )
    profile = profile.model_copy(update={"lenses": [*profile.lenses, replay]})
    output = _analysis_output()
    output["matched_lenses"] = ["replay"]
    service = ResearchAnalysisService(
        repository, AIGateway(MockDeepSeekClient({"research_candidate_analysis": output}))
    )

    with pytest.raises(AIResponseError, match="only the selected Lens"):
        service.analyze(work, profile, profile.lenses[0], _context_pack())

    assert connection.execute("SELECT COUNT(*) FROM research_work_analyses").fetchone()[0] == 0
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
        "summary_zh": "这篇论文研究参数重要性。",
        "why_relevant_zh": "这与正则化研究主题相符。",
        "reading_reason_zh": "这可能有助于理解巩固方法。",
        "existing_relations": [
            {
                "entity_type": "document",
                "entity_id": "ewc",
                "relation": "extends",
                "reason": "It extends the pinned EWC note.",
                "reason_zh": "它扩展了置顶的 EWC 笔记。",
            }
        ],
        "suggested_collection": "research-core",
        "suggested_section": "Regularization",
    }


def _raise_provider_error(transient):
    raise AIProviderError("provider failure", transient=transient)
