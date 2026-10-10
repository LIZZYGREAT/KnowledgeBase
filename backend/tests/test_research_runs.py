from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from backend.app.db.connection import connect_database
from backend.app.domain.research import ResearchGlobalConfig, ResearchProfile, ResearchProviders
from backend.app.domain.research_runtime import (
    ResearchCandidateRecord,
    ResearchContextPack,
    ResearchRunRecord,
    ResearchWorkRecord,
)
from backend.app.domain.term_runtime import TermCandidateEvidenceInput
from backend.app.domain.source import SourceMetadata
from backend.app.repositories.research_candidate_repository import (
    ResearchCandidateRepository,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.repositories.research_run_repository import ResearchRunRepository
from backend.app.repositories.research_run_request_repository import (
    ResearchRunRequestRepository,
)
from backend.app.repositories.research_search_repository import ResearchSearchRepository
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.services.ai_client import AIGatewayError, MockDeepSeekClient
from backend.app.services.ai_gateway import AIGateway
from backend.app.services.research_analysis_service import ResearchAnalysisService
from backend.app.services.research_candidate_service import ResearchCandidateService
from backend.app.services.research_profile_registry import ResearchProfileRegistry
from backend.app.services.research_providers.base import (
    ProviderPage,
    ProviderWork,
    ResearchProviderError,
)
from backend.app.services.research_lock import GlobalResearchLock
from backend.app.services.term_candidate_service import TermCandidateService
from backend.app.services.research_service import (
    MAX_ANALYSIS_BACKLOG_PER_RUN,
    ResearchService,
)
from backend.app.services.source_registry import SourceRegistry


_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def test_run_is_persisted_before_provider_and_completed_slice_advances_watermark(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, run_repository, search_repository, ai_client = _service(
        tmp_path, connection, provider
    )
    provider.before_search = lambda: _assert_running_run_exists(run_repository)

    run = service.run_profile("continual-learning")

    assert run is not None
    assert run.status == "success"
    assert (
        run.fetched_count,
        run.new_work_count,
        run.analysis_attempt_count,
        run.analyzed_count,
        run.surfaced_count,
    ) == (
        1,
        1,
        1,
        1,
        1,
    )
    assert provider.calls == 1
    assert ai_client.calls == ["research_candidate_analysis"]
    state = search_repository.get_state(
        "continual-learning", "regularization", "arxiv", _query_key(service)
    )
    assert state is not None
    assert state.completed_through == "2026-10-03T12:00:00+00:00"
    assert ResearchCandidateRepository(connection).count_new("continual-learning") == 1
    connection.close()


def test_identity_conflict_skips_only_that_work_and_keeps_processing_the_page(tmp_path):
    connection = connect_database(":memory:")
    normal_a = _provider_work().model_copy(
        update={
            "provider_record_id": "arrival-a",
            "doi": "10.1000/identity-a",
        }
    )
    conflict = _provider_work().model_copy(
        update={
            "provider_record_id": "arrival-b-conflict",
            "doi": "10.1000/identity-b",
            "arxiv_id": "2401.12345",
        }
    )
    normal_c = _provider_work().model_copy(
        update={
            "provider_record_id": "arrival-c",
            "doi": "10.1000/identity-c",
            "arxiv_id": "2401.67890",
        }
    )
    provider = FakeProvider(
        [ProviderPage(works=(normal_a, conflict, normal_c))]
    )
    service, _, _, ai_client = _service(tmp_path, connection, provider)
    work_a, work_b = _seed_identity_collision(service)
    before_b_discoveries = len(
        ResearchRepository(connection).list_discoveries_for_work(work_b.id)
    )

    run = service.run_profile("continual-learning")

    assert run is not None and run.status == "partial"
    assert (run.fetched_count, run.new_work_count, run.duplicate_count) == (3, 1, 1)
    assert run.analysis_attempt_count == 2
    assert run.analyzed_count == 2
    assert ai_client.calls == [
        "research_candidate_analysis",
        "research_candidate_analysis",
    ]
    assert "Research identity conflicts count=1" in (run.error_summary or "")
    assert "arrival-b-conflict" in (run.error_summary or "")
    assert ResearchRepository(connection).get_work(work_a.id) is not None
    assert len(ResearchRepository(connection).list_discoveries_for_work(work_b.id)) == (
        before_b_discoveries
    )
    assert len(ResearchRepository(connection).list_discoveries_for_work(work_a.id)) == 2
    connection.close()


def test_identity_conflict_does_not_advance_later_slices_or_block_other_streams(
    tmp_path,
):
    connection = connect_database(":memory:")
    conflict = _provider_work().model_copy(
        update={
            "provider_record_id": "slice-conflict",
            "doi": "10.1000/identity-b",
            "arxiv_id": "2401.12345",
        }
    )
    profile = _profile(queries=("fisher information", "parameter importance"))
    profile = profile.model_copy(
        update={
            "search": profile.search.model_copy(
                update={"initial_lookback_days": 3}
            )
        }
    )
    provider = FakeProvider(
        [
            ProviderPage(works=(conflict,)),
            ProviderPage(works=()),
            ProviderPage(works=()),
            ProviderPage(works=()),
        ]
    )
    service, _, search_repository, _ = _service(
        tmp_path, connection, provider, profile=profile
    )
    _seed_identity_collision(service)
    queries = service.query_builder.build(profile)

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "partial"
    assert provider.calls == 4
    conflicted_state = search_repository.get_state(
        profile.id, queries[0].lens_id, "arxiv", queries[0].query_key
    )
    other_state = search_repository.get_state(
        profile.id, queries[1].lens_id, "arxiv", queries[1].query_key
    )
    assert conflicted_state is not None
    assert conflicted_state.completed_through is None
    assert other_state is not None and other_state.completed_through == _NOW.isoformat()
    connection.close()


def test_identity_conflict_slice_retries_and_advances_after_provider_data_is_fixed(
    tmp_path,
):
    connection = connect_database(":memory:")
    conflict = _provider_work().model_copy(
        update={
            "provider_record_id": "retry-conflict",
            "doi": "10.1000/identity-b",
            "arxiv_id": "2401.12345",
        }
    )
    profile = _profile().model_copy(
        update={
            "search": _profile().search.model_copy(
                update={"initial_lookback_days": 2}
            )
        }
    )
    provider = FakeProvider([ProviderPage(works=(conflict,))])
    service, _, search_repository, _ = _service(
        tmp_path, connection, provider, profile=profile
    )
    _seed_identity_collision(service)
    query = service.query_builder.build(profile)[0]

    first_run = service.run_profile(profile.id)
    first_state = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert first_run is not None and first_run.status == "partial"
    assert first_state is not None and first_state.completed_through is None

    provider.pages = [
        ProviderPage(
            works=(
                conflict.model_copy(
                    update={"provider_record_id": "retry-fixed", "arxiv_id": None}
                ),
            )
        ),
        ProviderPage(works=()),
    ]
    second_run = service.run_profile(profile.id)

    assert second_run is not None and second_run.status == "success"
    assert provider.calls == 3
    retried_state = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert retried_state is not None and retried_state.completed_through == _NOW.isoformat()
    connection.close()


def test_many_identity_conflicts_keep_run_diagnostics_bounded(tmp_path):
    connection = connect_database(":memory:")
    conflicts = tuple(
        _provider_work().model_copy(
            update={
                "provider_record_id": "conflict-{}".format(index),
                "doi": "10.1000/identity-b",
                "arxiv_id": "2401.12345",
            }
        )
        for index in range(20)
    )
    provider = FakeProvider([ProviderPage(works=conflicts)])
    service, _, _, _ = _service(tmp_path, connection, provider)
    _seed_identity_collision(service)

    run = service.run_profile("continual-learning")

    assert run is not None and run.status == "partial"
    assert run.fetched_count == 20
    assert run.new_work_count == 0
    assert run.duplicate_count == 0
    assert len(run.error_summary or "") <= 1_000
    assert "Research identity conflicts count=20" in (run.error_summary or "")
    assert "additional conflicts=" in (run.error_summary or "")
    connection.close()


@pytest.mark.parametrize("invalid_only", [False, True])
def test_research_invalid_term_evidence_keeps_main_analysis(tmp_path, invalid_only):
    connection = connect_database(":memory:")
    output = _analysis_output()
    valid = {
        "mention": "parameter importance", "term_type": "concept",
        "existing_term_id": None, "confidence": 0.86,
        "rationale": "Central to the method.",
        "context_excerpt": "Fisher information measures parameter importance.",
        "readiness": "medium", "recommendation_level": "next",
        "known_prerequisites": [], "missing_prerequisites": [],
        "why_now": "Connects to the selected context.",
    }
    output["term_candidates"] = [dict(valid, context_excerpt="Invented evidence.")]
    if not invalid_only:
        output["term_candidates"].append(valid)
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, _runs, _search, client = _service(
        tmp_path, connection, provider, analysis_output=output
    )
    run = service.run_profile("continual-learning")
    assert run.status == "success"
    assert run.analyzed_count == 1
    assert len(service.candidate_repository.list_for_profile("continual-learning")) == 1
    assert len(service.term_candidate_service.list_candidates("pending")) == (0 if invalid_only else 1)
    service.run_profile("continual-learning", trigger="manual")
    assert client.calls == ["research_candidate_analysis"]
    connection.close()


def test_research_analysis_adds_term_evidence_without_coupling_candidate_lifecycles(tmp_path):
    connection = connect_database(":memory:")
    output = _analysis_output()
    output["term_candidates"] = [
        {
            "mention": "parameter importance",
            "term_type": "concept",
            "existing_term_id": None,
            "confidence": 0.86,
            "rationale": "It is central to the paper's method.",
            "context_excerpt": "Fisher information measures parameter importance.",
            "readiness": "medium",
            "recommendation_level": "core_gap",
            "known_prerequisites": ["Fisher information"],
            "missing_prerequisites": [],
            "why_now": "It connects an established concept to this paper's method.",
        }
    ]
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, _runs, _search, ai_client = _service(
        tmp_path, connection, provider, analysis_output=output
    )

    run = service.run_profile("continual-learning")

    assert run is not None and run.status == "success"
    assert ai_client.calls == ["research_candidate_analysis"]
    research_candidate = service.candidate_repository.list_for_profile(
        "continual-learning"
    )[0]
    term_candidate = service.term_candidate_service.list_candidates("pending")[0]
    evidence = service.term_candidate_service.repository.get_evidence(term_candidate.id)[0]
    assert term_candidate.display_name == "parameter importance"
    assert term_candidate.discovery_assessment.readiness == "medium"
    assert evidence.origin_type == "research_work"
    assert evidence.origin_id == research_candidate.work_id
    assert evidence.context_excerpt == "Fisher information measures parameter importance."
    assert service.term_candidate_service.repository.count_for_research_works(
        [research_candidate.work_id]
    ) == {research_candidate.work_id: 1}

    service.candidate_service.dismiss(research_candidate.id, reason="not_interested")
    assert service.term_candidate_service.get_candidate(term_candidate.id).status == "pending"
    service.term_candidate_service.reject_candidate(
        term_candidate.id,
        scope="local",
        reason="Not a current term",
        origin_type="research_work",
        origin_id=research_candidate.work_id,
    )
    assert service.candidate_repository.get(research_candidate.id).status == "dismissed"
    assert service.term_candidate_service.get_candidate(term_candidate.id).status == "rejected"
    connection.close()


def test_research_term_suggestion_enriches_an_existing_open_candidate(tmp_path):
    connection = connect_database(":memory:")
    output = _analysis_output()
    output["term_candidates"] = [
        {
            "mention": "parameter importance",
            "term_type": "concept",
            "existing_term_id": None,
            "confidence": 0.86,
            "rationale": "It is central to the paper's method.",
            "context_excerpt": "Fisher information measures parameter importance.",
            "readiness": "medium",
            "recommendation_level": "core_gap",
            "known_prerequisites": ["Fisher information"],
            "missing_prerequisites": [],
            "why_now": "It connects an established concept to this paper's method.",
        }
    ]
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, _runs, _search, _client = _service(
        tmp_path, connection, provider, analysis_output=output
    )
    prior = service.term_candidate_service.create_candidate(
        "parameter importance",
        "concept",
        [
            TermCandidateEvidenceInput(
                origin_type="external",
                origin_id="existing-research-notes",
                mention="parameter importance",
            )
        ],
    )

    run = service.run_profile("continual-learning")

    assert run is not None and run.status == "success"
    pending = service.term_candidate_service.list_candidates("pending")
    assert [candidate.id for candidate in pending] == [prior.id]
    evidence = service.term_candidate_service.repository.get_evidence(prior.id)
    assert {item.origin_type for item in evidence} == {"external", "research_work"}
    research_candidate = service.candidate_repository.list_for_profile(
        "continual-learning"
    )[0]
    assert any(
        item.origin_type == "research_work"
        and item.origin_id == research_candidate.work_id
        for item in evidence
    )
    connection.close()


def test_search_rounds_rank_across_providers_and_prioritize_high_lenses(tmp_path):
    connection = connect_database(":memory:")
    base_profile = _profile(discovery=("arxiv", "openalex"))
    profile_data = base_profile.model_dump(mode="json")
    profile_data["lenses"] = [
        {
            "id": "low-focus",
            "title": "Low Focus",
            "enabled": True,
            "priority": "low",
            "queries": ["low priority methods"],
            "include_terms": [],
            "exclude_terms": [],
        },
        {
            "id": "high-focus",
            "title": "High Focus",
            "enabled": True,
            "priority": "high",
            "queries": ["fisher information"],
            "include_terms": [],
            "exclude_terms": [],
        },
    ]
    profile_data["search"]["max_analyses_per_run"] = 1
    profile = ResearchProfile.model_validate(profile_data)

    class QueryAwareProvider:
        def __init__(self, name, works_by_query):
            self.name = name
            self.works_by_query = works_by_query
            self.calls = []
            self.before_search = None

        def search(self, query, start_at, end_at, cursor=None, limit=None):
            self.calls.append((query, cursor))
            if self.before_search is not None:
                self.before_search()
            work = self.works_by_query[query]
            return ProviderPage(works=(work,))

    low_query = "low priority methods"
    high_query = "fisher information"
    arxiv = QueryAwareProvider(
        "arxiv",
        {
            low_query: ProviderWork(
                provider="arxiv",
                provider_record_id="2401.11111",
                arxiv_id="2401.11111",
                title="A Study of Older Methods",
                abstract="An unrelated study.",
                authors=("Ada Lovelace",),
                year=2026,
                published_at="2026-10-02",
                url="https://arxiv.org/abs/2401.11111",
            ),
            high_query: ProviderWork(
                provider="arxiv",
                provider_record_id="2401.22222",
                arxiv_id="2401.22222",
                title="A Study of Older Methods",
                abstract="An unrelated study.",
                authors=("Ada Lovelace",),
                year=2026,
                published_at="2026-10-02",
                url="https://arxiv.org/abs/2401.22222",
            ),
        },
    )
    openalex = QueryAwareProvider(
        "openalex",
        {
            low_query: ProviderWork(
                provider="openalex",
                provider_record_id="W-LOW",
                openalex_id="W-LOW",
                title="A Study of Older Methods",
                abstract="An unrelated study.",
                authors=("Ada Lovelace",),
                year=2026,
                published_at="2026-10-02",
                url="https://openalex.org/W-LOW",
            ),
            high_query: ProviderWork(
                provider="openalex",
                provider_record_id="W-HIGH",
                openalex_id="W-HIGH",
                title="Fisher Information for Continual Learning",
                abstract="Fisher information helps estimate parameter importance.",
                authors=("Ada Lovelace",),
                year=2026,
                published_at="2026-10-02",
                url="https://openalex.org/W-HIGH",
            ),
        },
    )
    service, _, _, ai_client = _service(
        tmp_path,
        connection,
        arxiv,
        profile=profile,
        additional_providers={"openalex": openalex},
        analysis_output={
            **_analysis_output(),
            "matched_lenses": ["high-focus"],
        },
    )
    arxiv.before_search = lambda: _assert_no_ai_calls(ai_client)
    openalex.before_search = lambda: _assert_no_ai_calls(ai_client)

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "success"
    assert run.analysis_attempt_count == 1 and run.surfaced_count == 1
    assert [query for query, _ in arxiv.calls] == [high_query, low_query]
    assert [query for query, _ in openalex.calls] == [high_query, low_query]
    work_rows = [
        tuple(row)
        for row in connection.execute(
            "SELECT id, title, arxiv_id, openalex_id FROM research_works ORDER BY title"
        ).fetchall()
    ]
    high_work_id = connection.execute(
        "SELECT id FROM research_works WHERE openalex_id = 'w-high'"
    ).fetchone()
    assert high_work_id is not None, (run, work_rows)
    high_work_id = high_work_id[0]
    candidate = service.candidate_repository.get_for_work(high_work_id, profile.id)
    assert candidate is not None and candidate.primary_lens_id == "high-focus"
    assert len(ai_client.calls) == 1
    connection.close()


def test_manual_incremental_run_keeps_scheduled_watermark_unchanged(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([])
    service, _, search_repository, _ = _service(tmp_path, connection, provider)
    profile = service.profile_registry.get("continual-learning")
    query = service.query_builder.build(profile)[0]
    watermark = _NOW - timedelta(days=1)
    search_repository.record_attempt(
        profile.id, query.lens_id, "arxiv", query.query_key, query.text,
        watermark.isoformat(),
    )
    search_repository.complete_slice(
        profile.id, query.lens_id, "arxiv", query.query_key,
        watermark.isoformat(), watermark.isoformat(),
    )
    before = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )

    run = service.run_profile(
        profile.id, trigger="manual", manual_incremental=True
    )

    after = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert run is not None and run.status == "success"
    assert run.effective_config["manual_incremental"] is True
    assert after == before
    assert provider.calls > 0
    connection.close()


def test_direct_manual_run_without_override_keeps_scheduled_watermark_unchanged(
    tmp_path,
):
    connection = connect_database(":memory:")
    provider = FakeProvider([])
    service, _, search_repository, _ = _service(tmp_path, connection, provider)
    profile = service.profile_registry.get("continual-learning")
    query = service.query_builder.build(profile)[0]
    watermark = _NOW - timedelta(hours=12)
    search_repository.record_attempt(
        profile.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        query.text,
        watermark.isoformat(),
    )
    search_repository.complete_slice(
        profile.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        watermark.isoformat(),
        watermark.isoformat(),
    )
    before = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )

    run = service.run_profile(profile.id, trigger="manual")

    after = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert run is not None and run.status == "success"
    assert after == before
    assert provider.calls > 0
    connection.close()


def test_queued_manual_run_without_range_keeps_scheduled_watermark_unchanged(
    tmp_path,
):
    connection = connect_database(":memory:")
    service, _, search_repository, _ = _service(
        tmp_path, connection, FakeProvider([])
    )
    profile = service.profile_registry.get("continual-learning")
    query = service.query_builder.build(profile)[0]
    watermark = _NOW - timedelta(hours=12)
    search_repository.record_attempt(
        profile.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        query.text,
        watermark.isoformat(),
    )
    search_repository.complete_slice(
        profile.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        watermark.isoformat(),
        watermark.isoformat(),
    )
    before = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    service.queue_manual_run(profile.id)

    run = service.tick()

    after = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert run is not None and run.trigger == "manual" and run.status == "success"
    assert after == before
    connection.close()


def test_full_inbox_skips_before_provider_or_deepseek_calls(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([])
    profile = _profile(max_new_candidates=1)
    _seed_existing_new_candidate(connection, profile)
    service, run_repository, _, ai_client = _service(
        tmp_path, connection, provider, profile=profile
    )

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "skipped_inbox_full"
    assert provider.calls == 0
    assert ai_client.calls == []
    assert run_repository.list_for_profile(profile.id)[0].id == run.id
    connection.close()


def test_disabled_ai_keeps_discovery_and_enrichment_without_context_or_candidates(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider(
        [ProviderPage(works=(_provider_work().model_copy(update={"doi": "10.1000/original"}),))]
    )
    enrichment = FakeEnrichmentProvider()
    base_profile = _profile()
    profile = base_profile.model_copy(
        update={
            "providers": ResearchProviders.model_validate(
                {**base_profile.providers.model_dump(), "enrichment": ["openalex"]}
            ),
            "ai_analysis": base_profile.ai_analysis.model_copy(
                update={"enabled": False}
            )
        }
    )
    service, run_repository, search_repository, ai_client = _service(
        tmp_path,
        connection,
        provider,
        profile=profile,
        additional_providers={"openalex": enrichment},
    )
    context_builder = RecordingContextBuilder(service.context_builder)
    service.context_builder = context_builder

    run = service.tick()

    assert run is not None and run.status == "success"
    assert (run.fetched_count, run.new_work_count, run.analysis_attempt_count, run.surfaced_count) == (1, 1, 0, 0)
    assert provider.calls == 1
    assert enrichment.enrichment_calls == 1
    assert ai_client.calls == []
    assert context_builder.work_titles == []
    assert connection.execute("SELECT COUNT(*) FROM research_works").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM research_discoveries").fetchone()[0] == 1
    assert ResearchCandidateRepository(connection).count_new(profile.id) == 0
    query = service.query_builder.build(profile)[0]
    state = search_repository.get_state(profile.id, query.lens_id, "arxiv", query.query_key)
    assert state is not None and state.completed_through == _NOW.isoformat()
    work_id = connection.execute("SELECT id FROM research_works").fetchone()[0]
    enriched_work = service.work_repository.get_work(work_id)
    assert enriched_work is not None and enriched_work.venue == "Journal of Learning"

    request = service.queue_manual_run(profile.id)
    assert service.run_request_repository.get(request.id).status == "pending"
    manual_run = service.tick()
    assert manual_run is not None and manual_run.trigger == "manual"
    assert manual_run.status == "success"
    assert service.run_request_repository.get(request.id).status == "completed"
    assert len(run_repository.list_for_profile(profile.id)) == 2
    connection.close()


def test_disabled_ai_keeps_discovery_running_when_inbox_is_full(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile(max_new_candidates=1).model_copy(
        update={
            "ai_analysis": _profile().ai_analysis.model_copy(update={"enabled": False})
        }
    )
    _seed_existing_new_candidate(connection, profile)
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, _, _, ai_client = _service(
        tmp_path, connection, provider, profile=profile
    )

    run = service.tick()

    assert run is not None and run.status == "success"
    assert run.fetched_count == 1 and provider.calls == 1
    assert ai_client.calls == []
    assert connection.execute("SELECT COUNT(*) FROM research_discoveries").fetchone()[0] == 1
    connection.close()


@pytest.mark.parametrize(
    ("blocker", "message"),
    [
        ("profile_disabled", "Research Profile is disabled"),
        ("inbox_full", "Research Inbox is full"),
    ],
)
def test_manual_queue_rejects_profiles_that_cannot_discover(
    tmp_path, blocker, message
):
    connection = connect_database(":memory:")
    base_profile = _profile(max_new_candidates=1 if blocker == "inbox_full" else 20)
    if blocker == "profile_disabled":
        profile = base_profile.model_copy(update={"enabled": False})
    else:
        profile = base_profile
    if blocker == "inbox_full":
        _seed_existing_new_candidate(connection, profile)
    service, _, _, _ = _service(tmp_path, connection, FakeProvider([]), profile=profile)
    with pytest.raises(ValueError, match=message):
        service.queue_manual_run(profile.id)

    assert connection.execute("SELECT COUNT(*) FROM research_run_requests").fetchone()[0] == 0
    connection.close()


def test_reenabling_ai_analyzes_saved_discovery_backlog_with_a_per_run_bound(tmp_path):
    connection = connect_database(":memory:")
    filtered_works = tuple(
        _provider_work().model_copy(
            update={
                "provider_record_id": "2401.filtered-{}".format(index),
                "title": "Control Theory Revisited {}".format(index),
                "abstract": "A control systems paper unrelated to this Lens.",
                "arxiv_id": "2401.filtered-{}".format(index),
            }
        )
        for index in range(3)
    )
    eligible_works = tuple(
        _provider_work().model_copy(
            update={
                "provider_record_id": "2401.eligible-{}".format(index),
                "title": "Fisher Information for Continual Learning {}".format(index),
                "arxiv_id": "2401.eligible-{}".format(index),
            }
        )
        for index in range(12)
    )
    works = filtered_works + eligible_works
    provider = FakeProvider([ProviderPage(works=works), ProviderPage(works=())])
    base_profile = _profile(max_new_candidates=20)
    profile = base_profile.model_copy(
        update={
            "search": base_profile.search.model_copy(
                update={"max_candidates_per_run": 20}
            ),
            "ai_analysis": base_profile.ai_analysis.model_copy(
                update={"enabled": False}
            ),
        }
    )
    service, _, _, ai_client = _service(
        tmp_path, connection, provider, profile=profile
    )
    context_builder = RecordingContextBuilder(service.context_builder)
    service.context_builder = context_builder

    discovery_run = service.tick()

    assert discovery_run is not None and discovery_run.status == "success"
    assert discovery_run.new_work_count == 15
    assert discovery_run.analysis_attempt_count == 0
    assert connection.execute("SELECT COUNT(*) FROM research_discoveries").fetchone()[0] == 15

    enabled_profile = profile.model_copy(
        update={
            "ai_analysis": profile.ai_analysis.model_copy(update={"enabled": True})
        }
    )
    service.profile_registry = _profile_registry(enabled_profile)
    analysis_run = service.run_profile(enabled_profile.id, trigger="manual")

    assert analysis_run is not None and analysis_run.status == "success"
    assert analysis_run.analysis_attempt_count == MAX_ANALYSIS_BACKLOG_PER_RUN
    assert analysis_run.surfaced_count == MAX_ANALYSIS_BACKLOG_PER_RUN
    assert len(context_builder.work_titles) == MAX_ANALYSIS_BACKLOG_PER_RUN
    assert len(ai_client.calls) == MAX_ANALYSIS_BACKLOG_PER_RUN
    assert ResearchCandidateRepository(connection).count_new(profile.id) == MAX_ANALYSIS_BACKLOG_PER_RUN
    connection.close()


def test_analysis_backlog_scans_past_first_hundred_filtered_discoveries(tmp_path):
    connection = connect_database(":memory:")
    service, _, _, ai_client = _service(
        tmp_path, connection, FakeProvider([])
    )
    profile = service.profile_registry.get("continual-learning")
    query = service.query_builder.build(profile)[0]
    context_builder = RecordingContextBuilder(service.context_builder)
    service.context_builder = context_builder

    for index in range(101):
        eligible = index == 100
        work = _provider_work().model_copy(
            update={
                "provider_record_id": "2401.backlog-{}".format(index),
                "title": (
                    "Fisher Information for Continual Learning"
                    if eligible
                    else "Control Theory Revisited {}".format(index)
                ),
                "abstract": (
                    "Fisher information supports continual learning."
                    if eligible
                    else "A control systems paper unrelated to this Lens."
                ),
                "arxiv_id": "2401.backlog-{}".format(index),
            }
        )
        service.deduplicator.record_discovery(
            profile.id,
            query.lens_id,
            query.query_key,
            query.text,
            work,
            discovered_at=_NOW + timedelta(seconds=index),
        )

    run = service.run_profile(profile.id, trigger="manual")

    assert run is not None and run.status == "success"
    assert run.analysis_attempt_count == 1
    assert run.surfaced_count == 1
    assert context_builder.work_titles == ["Fisher Information for Continual Learning"]
    assert len(ai_client.calls) == 1
    connection.close()


def test_analysis_budget_reserves_a_slot_for_eligible_backlog(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile()
    profile = profile.model_copy(
        update={
            "search": profile.search.model_copy(update={"max_analyses_per_run": 3})
        }
    )
    new_works = tuple(
        _provider_work().model_copy(
            update={
                "provider_record_id": "2401.new-{}".format(index),
                "title": "Fisher Information for Continual Learning New {}".format(
                    index
                ),
                "doi": "10.1000/new-{}".format(index),
                "arxiv_id": "2401.new-{}".format(index),
            }
        )
        for index in range(5)
    )
    provider = FakeProvider([ProviderPage(works=new_works)])
    service, _, _, _ = _service(tmp_path, connection, provider, profile=profile)
    query = service.query_builder.build(profile)[0]
    backlog_work = _provider_work().model_copy(
        update={
            "provider_record_id": "2401.historical",
            "title": "Fisher Information Historical Study",
            "abstract": "Fisher information is discussed.",
            "year": 2010,
            "published_at": "2010-01-01",
            "arxiv_id": "2401.historical",
        }
    )
    service.deduplicator.record_discovery(
        profile.id,
        query.lens_id,
        query.query_key,
        query.text,
        backlog_work,
        discovered_at=_NOW - timedelta(days=30),
    )
    context_builder = RecordingContextBuilder(service.context_builder)
    service.context_builder = context_builder

    run = service.run_profile(profile.id, trigger="manual")

    assert run is not None and run.status == "success"
    assert run.analysis_attempt_count == 3
    assert "Fisher Information Historical Study" in context_builder.work_titles
    assert len(context_builder.work_titles) == 3
    connection.close()


def test_filtered_backlog_releases_unused_analysis_budget_to_new_works(tmp_path):
    connection = connect_database(":memory:")
    base_profile = _profile(enrichment=("openalex",))
    profile = base_profile.model_copy(
        update={
            "search": base_profile.search.model_copy(
                update={"max_analyses_per_run": 3}
            )
        }
    )
    new_works = tuple(
        _provider_work().model_copy(
            update={
                "provider_record_id": "2401.new-budget-{}".format(index),
                "title": "Fisher Information Study {}".format(index),
                "abstract": "Fisher information supports continual learning.",
                "doi": "10.1000/new-budget-{}".format(index),
                "arxiv_id": "2401.new-budget-{}".format(index),
                "venue": "Learning Systems Conference",
                "url": "https://example.org/new-budget-{}".format(index),
            }
        )
        for index in range(3)
    )
    discovery = FakeProvider([ProviderPage(works=new_works)])
    enrichment = FakeEnrichmentProvider()
    service, _, _, ai_client = _service(
        tmp_path,
        connection,
        discovery,
        profile=profile,
        additional_providers={"openalex": enrichment},
    )
    query = service.query_builder.build(profile)[0]
    backlog_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2401.old-filtered-backlog",
        title="Fisher Information Historical Study",
        abstract="Fisher information supports continual learning.",
        authors=("Ada Lovelace",),
        year=2010,
        published_at="2010-01-01",
        arxiv_id="2401.old-filtered-backlog",
        openalex_id="W-seed-backlog",
    )
    service.deduplicator.record_discovery(
        profile.id,
        query.lens_id,
        query.query_key,
        query.text,
        backlog_work,
        discovered_at=_NOW - timedelta(days=30),
    )
    service.screening.sources = SourceRegistry(
        (
            SourceMetadata.model_validate(
                {
                    "schema_version": 1,
                    "id": "already-published-source",
                    "type": "paper",
                    "title": "A paper already in the library",
                    "authors": ["Ada Lovelace"],
                    "year": 2010,
                    "identifiers": {"doi": "10.1000/enriched"},
                }
            ),
        )
    )
    context_builder = RecordingContextBuilder(service.context_builder)
    service.context_builder = context_builder

    run = service.run_profile(profile.id, trigger="manual")

    assert run is not None and run.status == "success"
    assert run.analysis_attempt_count == 3
    assert enrichment.enrichment_calls == 1
    assert len(context_builder.work_titles) == 3
    assert all("Historical Study" not in title for title in context_builder.work_titles)
    assert len(ai_client.calls) == 3
    connection.close()


def test_queued_manual_run_discovers_while_automatic_research_is_paused(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, _, _, _ = _service(tmp_path, connection, provider)
    service.pause_profile("continual-learning", _NOW + timedelta(days=1))
    request = service.queue_manual_run("continual-learning")

    run = service.tick()

    assert run is not None and run.status == "success"
    assert run.request_id == request.id
    assert service.run_request_repository.get(request.id).status == "completed"
    assert provider.calls == 1
    connection.close()


def test_capacity_reached_mid_slice_stops_pagination_without_advancing_watermark(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider(
        [ProviderPage(works=(_provider_work(),), next_cursor="page-2")]
    )
    profile = _profile(max_new_candidates=1)
    service, _, search_repository, _ = _service(
        tmp_path, connection, provider, profile=profile
    )

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "capacity_reached"
    assert run.surfaced_count == 1
    assert provider.calls == 1
    assert provider.limit_requests == [20]
    state = search_repository.get_state(
        profile.id, "regularization", "arxiv", _query_key(service)
    )
    assert state is not None
    assert state.completed_through is None
    assert state.last_attempt_at is not None
    connection.close()


def test_provider_request_uses_configured_page_size_with_one_remaining_inbox_slot(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    profile = _profile(max_new_candidates=2)
    _seed_existing_new_candidate(connection, profile)
    service, _, _, _ = _service(tmp_path, connection, provider, profile=profile)

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "capacity_reached"
    assert run.surfaced_count == 1
    assert provider.limit_requests == [20]
    assert provider.calls == 1
    connection.close()


def test_filling_inbox_during_a_bounded_page_does_not_request_the_next_page(tmp_path):
    connection = connect_database(":memory:")
    first_work = _provider_work()
    second_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2402.00001",
        title="Fisher Information and Parameter Importance",
        abstract="Fisher information measures parameter importance.",
        authors=("Grace Hopper",),
        year=2026,
        published_at="2026-10-03",
        arxiv_id="2402.00001",
    )
    provider = FakeProvider(
        [
            ProviderPage(works=(first_work,), next_cursor="page-two"),
            ProviderPage(works=(second_work,)),
        ]
    )
    profile = _profile(max_new_candidates=1)
    service, _, search_repository, _ = _service(
        tmp_path, connection, provider, profile=profile
    )

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "capacity_reached"
    assert run.surfaced_count == 1
    assert provider.calls == 1
    assert provider.limit_requests == [20]
    state = search_repository.get_state(
        profile.id, "regularization", "arxiv", _query_key(service)
    )
    assert state is not None and state.completed_through is None
    connection.close()


def test_per_run_candidate_limit_succeeds_without_advancing_incomplete_slice(
    tmp_path,
):
    connection = connect_database(":memory:")
    first_work = _provider_work().model_copy(
        update={"published_at": (_NOW - timedelta(days=7)).date().isoformat()}
    )
    second_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2402.00001",
        title="A second Fisher Information study on parameter importance",
        abstract="Fisher information offers a distinct measure of parameter importance.",
        authors=("Grace Hopper",),
        year=2026,
        published_at=(_NOW - timedelta(days=7)).date().isoformat(),
        arxiv_id="2402.00001",
        url="https://arxiv.org/abs/2402.00001",
    )
    provider = FakeProvider(
        [
            ProviderPage(works=(first_work,)),
            ProviderPage(works=(second_work,)),
        ]
    )
    profile = _profile(max_new_candidates=10)
    profile = profile.model_copy(
        update={
            "search": profile.search.model_copy(
                update={"max_candidates_per_run": 1, "max_catchup_days": 7}
            )
        }
    )
    service, _, search_repository, _ = _service(
        tmp_path, connection, provider, profile=profile
    )
    now = [_NOW]
    service.clock = lambda: now[0]
    query = service.query_builder.build(profile)[0]
    stale = _NOW - timedelta(days=90)
    search_repository.record_attempt(
        profile.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        query.text,
        stale.isoformat(),
    )
    search_repository.complete_slice(
        profile.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        stale.isoformat(),
        stale.isoformat(),
    )
    floor = _NOW - timedelta(days=7)

    first_run = service.tick()

    assert first_run is not None and first_run.status == "success"
    assert first_run.surfaced_count == 1
    assert "Candidate budget reached" in (first_run.error_summary or "")
    assert service.candidate_service.remaining_capacity(profile) == 9
    assert provider.calls == 1
    state = search_repository.get_state(
        profile.id, "regularization", "arxiv", _query_key(service)
    )
    assert state is not None and state.completed_through == floor.isoformat()
    assert state.overlap_floor == floor.isoformat()
    assert provider.search_ranges[0][0] == floor
    assert service.tick() is None
    assert provider.calls == 1

    now[0] = _NOW + timedelta(days=1)
    second_run_start_index = len(provider.search_ranges)
    second_run = service.tick()

    assert second_run is not None and second_run.status == "success"
    assert second_run.surfaced_count == 1
    assert provider.calls == 2
    state = search_repository.get_state(
        profile.id, "regularization", "arxiv", _query_key(service)
    )
    assert state is not None and state.completed_through == floor.isoformat()
    assert provider.search_ranges[second_run_start_index][0] == floor
    connection.close()


def test_page_pre_rank_orders_eligible_work_before_analysis(tmp_path):
    connection = connect_database(":memory:")
    lower_ranked = ProviderWork(
        provider="arxiv",
        provider_record_id="2402.00001",
        title="Fisher Information for Parameter Importance",
        abstract="Fisher information measures parameter importance.",
        authors=(),
        year=2026,
        published_at="2026-10-02",
        arxiv_id="2402.00001",
    )
    higher_ranked = _provider_work()
    provider = FakeProvider(
        [ProviderPage(works=(lower_ranked, higher_ranked))]
    )
    service, _, _, _ = _service(tmp_path, connection, provider)
    recording_context = RecordingContextBuilder(service.context_builder)
    service.context_builder = recording_context

    run = service.run_profile("continual-learning")

    assert run is not None and run.status == "success"
    assert recording_context.work_titles == [higher_ranked.title, lower_ranked.title]
    assert run.analysis_attempt_count == 2
    assert run.analyzed_count == 2
    connection.close()


def test_ambiguous_source_identity_is_reported_in_run_warning_and_work_is_retained(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, _, _, _ = _service(tmp_path, connection, provider)
    source_values = [
        {
            "schema_version": 1,
            "id": source_id,
            "type": "paper",
            "title": "Fisher Information for Continual Learning",
            "authors": ["Ada Lovelace"],
            "year": year,
            "identifiers": {},
        }
        for source_id, year in (("fisher-source-one", 2025), ("fisher-source-two", 2026))
    ]
    service.screening.sources = SourceRegistry(
        tuple(SourceMetadata.model_validate(value) for value in source_values)
    )

    run = service.run_profile("continual-learning")

    assert run is not None and run.status == "success"
    assert run.surfaced_count == 1
    assert "Warning: ambiguous_existing_source" in (run.error_summary or "")
    connection.close()


def test_analysis_budget_counts_new_deepseek_calls_not_cached_analyses(tmp_path):
    connection = connect_database(":memory:")
    cached_work = _provider_work()
    new_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2402.00001",
        title="Fisher Information for New Parameter Importance",
        abstract="Fisher information measures parameter importance.",
        authors=("Grace Hopper",),
        year=2026,
        published_at="2026-10-02",
        arxiv_id="2402.00001",
    )
    over_budget_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2403.00002",
        title="Fisher Information for Another Parameter Study",
        abstract="Fisher information measures parameter importance.",
        authors=(),
        year=2026,
        published_at="2026-10-02",
        arxiv_id="2403.00002",
    )
    provider = FakeProvider(
        [ProviderPage(works=(cached_work, new_work, over_budget_work))]
    )
    profile = _profile(max_new_candidates=10)
    profile = profile.model_copy(
        update={
            "search": profile.search.model_copy(
                update={"max_analyses_per_run": 1}
            )
        }
    )
    service, _, search_repository, ai_client = _service(
        tmp_path, connection, provider, profile=profile
    )
    query = service.query_builder.build(profile)[0]
    ingested = service.deduplicator.record_discovery(
        profile.id,
        query.lens_id,
        query.query_key,
        query.text,
        cached_work,
        discovered_at=_NOW,
    )
    context_pack = service.context_builder.build(
        ingested.work, profile, profile.lenses[0], keywords=(query.text,)
    )
    cached_analysis = service.analysis_service.analyze(
        ingested.work, profile, profile.lenses[0], context_pack
    )
    assert cached_analysis is not None
    ai_client.calls.clear()
    run = service.run_profile(profile.id)

    assert run is not None and run.status == "success"
    assert run.analysis_attempt_count == 1
    assert run.analyzed_count == 1
    assert run.surfaced_count == 2
    assert "Analysis budget reached" in (run.error_summary or "")
    assert ai_client.calls == ["research_candidate_analysis"]
    assert service.candidate_repository.count_new(profile.id) == 2
    state = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert state is not None and state.completed_through is None
    connection.close()


def test_run_counts_failed_ai_request_as_attempt_but_not_analysis(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, _, _, _ = _service(tmp_path, connection, provider)

    def fail_analysis(*args, **kwargs):
        raise AIGatewayError("analysis request failed")

    service.analysis_service.gateway.run = fail_analysis
    run = service.run_profile("continual-learning")

    assert run is not None
    assert run.analysis_counts_known is True
    assert run.analysis_attempt_count == 1
    assert run.analyzed_count == 0
    assert "analysis request failed" in (run.error_summary or "")
    connection.close()


def test_incomplete_manual_range_reuses_negative_analysis_on_restart(tmp_path):
    connection = connect_database(":memory:")
    page = ProviderPage(works=(_provider_work(),))
    provider = FakeProvider([page, page])
    service, _, _, ai_client = _service(
        tmp_path,
        connection,
        provider,
        analysis_output=_analysis_output(relevant=False),
    )
    manual_range = (
        datetime(2026, 10, 2, tzinfo=timezone.utc),
        datetime(2026, 10, 3, tzinfo=timezone.utc),
    )

    first = service.run_profile(
        "continual-learning", trigger="manual", manual_range=manual_range
    )
    restarted = service.run_profile(
        "continual-learning", trigger="manual", manual_range=manual_range
    )

    assert first is not None and first.status == "success"
    assert restarted is not None and restarted.status == "success"
    assert first.analysis_attempt_count == 1
    assert restarted.analysis_attempt_count == 0
    assert first.analyzed_count == 1
    assert restarted.analyzed_count == 0
    assert first.surfaced_count == restarted.surfaced_count == 0
    assert provider.calls == 2
    assert ai_client.calls == ["research_candidate_analysis"]
    assert connection.execute(
        "SELECT COUNT(*) FROM research_work_analyses"
    ).fetchone()[0] == 1
    connection.close()


def test_configured_enrichment_fills_work_metadata_before_analysis(tmp_path):
    connection = connect_database(":memory:")
    discovery_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2401.12345",
        title="Fisher Information for Continual Learning",
        abstract=None,
        authors=("Ada Lovelace",),
        year=2026,
        published_at="2026-10-02",
        doi="10.1000/enriched",
        arxiv_id="2401.12345",
    )
    discovery = FakeProvider([ProviderPage(works=(discovery_work,))])
    enrichment = FakeEnrichmentProvider()
    profile = _profile(enrichment=("openalex",))
    service, _, _, ai_client = _service(
        tmp_path,
        connection,
        discovery,
        profile=profile,
        additional_providers={"openalex": enrichment},
    )

    run = service.run_profile(profile.id)

    work_id = connection.execute("SELECT id FROM research_works").fetchone()["id"]
    enriched_work = ResearchRepository(connection).get_work(work_id)
    assert run is not None and run.status == "success"
    assert enrichment.enrichment_calls == 1
    assert run.provider_summary["openalex"]["works"] == 1
    assert enriched_work.abstract == "Enriched abstract with more detail."
    assert enriched_work.doi == "10.1000/enriched"
    assert ai_client.calls == ["research_candidate_analysis"]
    connection.close()


def test_enrichment_discovering_existing_source_skips_context_and_analysis(tmp_path):
    connection = connect_database(":memory:")
    discovery_work = _provider_work().model_copy(
        update={
            "doi": None,
            "openalex_id": "W123456",
            "venue": None,
        }
    )
    discovery = FakeProvider([ProviderPage(works=(discovery_work,))])
    enrichment = FakeEnrichmentProvider()
    profile = _profile(enrichment=("openalex",))
    service, _, _, ai_client = _service(
        tmp_path,
        connection,
        discovery,
        profile=profile,
        additional_providers={"openalex": enrichment},
    )
    service.screening.sources = SourceRegistry(
        (
            SourceMetadata.model_validate(
                {
                    "schema_version": 1,
                    "id": "existing-enriched-source",
                    "type": "paper",
                    "title": "A paper already in the library",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "identifiers": {"doi": "10.1000/enriched"},
                }
            ),
        )
    )
    context_builder = RecordingContextBuilder(service.context_builder)
    service.context_builder = context_builder

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "success"
    assert run.deterministic_filtered_count == 1
    assert run.analysis_attempt_count == 0
    assert run.surfaced_count == 0
    assert enrichment.enrichment_calls == 1
    assert context_builder.work_titles == []
    assert ai_client.calls == []
    connection.close()


def test_deterministically_filtered_work_skips_optional_enrichment(tmp_path):
    connection = connect_database(":memory:")
    unrelated = ProviderWork(
        provider="arxiv",
        provider_record_id="2401.98765",
        title="A Chemistry Spectroscopy Survey",
        abstract="This work studies spectroscopy without continual learning.",
        authors=("Grace Hopper",),
        year=2026,
        published_at="2026-10-02",
        doi="10.1000/unrelated",
        arxiv_id="2401.98765",
    )
    discovery = FakeProvider([ProviderPage(works=(unrelated,))])
    enrichment = FakeEnrichmentProvider(name="crossref")
    profile = _profile(enrichment=("crossref",))
    service, _, _, _ = _service(
        tmp_path,
        connection,
        discovery,
        profile=profile,
        additional_providers={"crossref": enrichment},
    )

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "success"
    assert run.deterministic_filtered_count == 1
    assert enrichment.enrichment_calls == 0
    assert run.provider_summary["crossref"]["requests"] == 0
    connection.close()


def test_optional_enrichment_failure_warns_but_completes_discovery_slice(tmp_path):
    connection = connect_database(":memory:")
    discovery_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2401.12345",
        title="Fisher Information for Continual Learning",
        abstract=None,
        authors=("Ada Lovelace",),
        year=2026,
        published_at="2026-10-02",
        doi="10.1000/enrichment-failure",
        arxiv_id="2401.12345",
    )
    discovery = FakeProvider([ProviderPage(works=(discovery_work,))])
    enrichment = FakeEnrichmentProvider(fail=True, name="crossref")
    profile = _profile(enrichment=("crossref",))
    service, _, search_repository, ai_client = _service(
        tmp_path,
        connection,
        discovery,
        profile=profile,
        additional_providers={"crossref": enrichment},
    )
    query = service.query_builder.build(profile)[0]

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "success"
    assert "Warning: crossref enrichment: enrichment failed" in run.error_summary
    assert run.provider_summary["crossref"]["requests"] == 1
    assert run.provider_summary["crossref"]["errors"] == 1
    assert enrichment.enrichment_calls == 1
    assert run.analysis_attempt_count == 1
    assert run.analyzed_count == 1
    assert ai_client.calls == ["research_candidate_analysis"]
    state = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert state is not None and state.completed_through == _NOW.isoformat()
    connection.close()


def test_enrichment_identity_conflict_warns_and_other_work_is_still_enriched(tmp_path):
    connection = connect_database(":memory:")
    conflict_work = _provider_work().model_copy(
        update={
            "provider_record_id": "enrichment-conflict",
            "doi": "10.1000/enrichment-conflict",
            "arxiv_id": None,
            "openalex_id": None,
            "abstract": None,
            "venue": None,
        }
    )
    clean_work = _provider_work().model_copy(
        update={
            "provider_record_id": "enrichment-clean",
            "doi": "10.1000/enrichment-clean",
            "arxiv_id": None,
            "openalex_id": None,
            "abstract": None,
            "venue": None,
        }
    )
    discovery = FakeProvider(
        [ProviderPage(works=(conflict_work, clean_work))]
    )

    class ConflictThenSuccessfulEnrichment(FakeEnrichmentProvider):
        def enrich(self, work):
            self.enrichment_calls += 1
            if work.doi == "10.1000/enrichment-conflict":
                return ProviderWork(
                    provider="openalex",
                    provider_record_id="W-occupied",
                    title=work.title,
                    abstract="Should not be applied.",
                    authors=work.authors,
                    year=work.year,
                    doi=work.doi,
                    openalex_id="W-occupied",
                    url="https://openalex.org/W-occupied",
                )
            return ProviderWork(
                provider="openalex",
                provider_record_id="W-clean",
                title=work.title,
                abstract="Clean enrichment.",
                authors=work.authors,
                year=work.year,
                doi=work.doi,
                openalex_id="W-clean",
                venue="Journal of Learning",
                url="https://openalex.org/W-clean",
            )

    enrichment = ConflictThenSuccessfulEnrichment()
    profile = _profile(enrichment=("openalex",))
    service, _, _, ai_client = _service(
        tmp_path,
        connection,
        discovery,
        profile=profile,
        additional_providers={"openalex": enrichment},
    )
    owner = ProviderWork(
        provider="openalex",
        provider_record_id="W-occupied",
        title="Different paper owning the OpenAlex identifier",
        authors=("Alan Turing",),
        year=2025,
        openalex_id="W-occupied",
    )
    service.deduplicator.record_discovery(
        profile.id,
        "regularization",
        "seed-openalex-owner",
        "fisher information",
        owner,
        discovered_at=_NOW,
    )

    run = service.run_profile(profile.id)

    repository = ResearchRepository(connection)
    retained = repository.find_by_identifiers({"doi": "10.1000/enrichment-conflict"})[0]
    enriched = repository.find_by_identifiers({"doi": "10.1000/enrichment-clean"})[0]
    assert run is not None and run.status == "success"
    assert "Warning: openalex enrichment identity conflict" in (run.error_summary or "")
    assert run.provider_summary["openalex"]["errors"] == 1
    assert run.provider_summary["openalex"]["works"] == 1
    assert enrichment.enrichment_calls == 2
    assert retained.openalex_id is None
    assert retained.abstract == conflict_work.abstract
    assert enriched.openalex_id == "w-clean"
    assert enriched.abstract == "Clean enrichment."
    assert run.analysis_attempt_count == 2
    assert ai_client.calls == [
        "research_candidate_analysis",
        "research_candidate_analysis",
    ]
    connection.close()


def test_crossref_enrichment_is_skipped_when_work_has_no_doi(tmp_path):
    connection = connect_database(":memory:")
    discovery = FakeProvider([ProviderPage(works=(_provider_work(),))])
    enrichment = FakeEnrichmentProvider(fail=True, name="crossref")
    profile = _profile(enrichment=("crossref",))
    service, _, _, _ = _service(
        tmp_path,
        connection,
        discovery,
        profile=profile,
        additional_providers={"crossref": enrichment},
    )

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "success"
    assert enrichment.enrichment_calls == 0
    assert run.provider_summary["crossref"]["requests"] == 0
    assert run.provider_summary["crossref"]["errors"] == 0
    assert run.error_summary is None
    connection.close()


def test_openalex_discovery_does_not_repeat_openalex_enrichment(tmp_path):
    connection = connect_database(":memory:")
    discovery_work = ProviderWork(
        provider="openalex",
        provider_record_id="W123456",
        title="Fisher Information for Continual Learning",
        abstract="Fisher information measures parameter importance.",
        authors=("Ada Lovelace",),
        year=2026,
        published_at="2026-10-02",
        venue="Journal of Learning",
        doi="10.1000/openalex-work",
        openalex_id="W123456",
        url="https://openalex.org/W123456",
    )
    profile = _profile(discovery=("openalex",), enrichment=("openalex",))
    provider = FakeProvider(
        [ProviderPage(works=(discovery_work,))], name="openalex"
    )
    service, _, _, _ = _service(tmp_path, connection, provider, profile=profile)

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "success"
    assert run.provider_summary["openalex"]["requests"] == 1
    assert run.provider_summary["openalex"]["errors"] == 0
    connection.close()


def test_run_repository_marks_old_running_run_interrupted(tmp_path):
    connection = connect_database(":memory:")
    run_repository = ResearchRunRepository(connection)
    started = _NOW - timedelta(hours=2)
    running = ResearchRunRecord(
        id="stale-run",
        profile_id="continual-learning",
        trigger="scheduled",
        status="running",
        profile_content_hash="profile-hash",
        effective_config={},
        provider_summary={},
        started_at=started.isoformat(),
    )
    run_repository.create(running)

    recovered = run_repository.mark_stale_interrupted(
        _NOW - timedelta(minutes=45), _NOW
    )

    assert len(recovered) == 1
    assert recovered[0].status == "interrupted"
    assert recovered[0].finished_at == _NOW.isoformat()
    assert run_repository.get(running.id).status == "interrupted"
    connection.close()


def test_global_research_lock_allows_only_one_owner(tmp_path):
    path = tmp_path / "runtime" / "research.lock"
    first = GlobalResearchLock(path)
    second = GlobalResearchLock(path)
    try:
        assert first.try_acquire() is True
        assert first.try_acquire() is False
        assert second.try_acquire() is False
    finally:
        first.release()
    assert second.try_acquire() is True
    second.release()


def test_global_research_lock_is_non_reentrant(tmp_path):
    lock = GlobalResearchLock(tmp_path / "runtime" / "research.lock")
    assert lock.try_acquire() is True
    try:
        assert lock.try_acquire() is False
    finally:
        lock.release()






def test_provider_failures_open_a_run_local_circuit_and_other_provider_continues(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile(
        discovery=("arxiv", "openalex"),
        queries=(
            "fisher information",
            "parameter importance",
            "regularization",
            "continual learning",
        ),
    )
    failing = FakeProvider([], name="arxiv", error=True)
    succeeding = FakeProvider([ProviderPage(works=())], name="openalex")
    service, _, search_repository, _ = _service(
        tmp_path,
        connection,
        failing,
        profile=profile,
        additional_providers={"openalex": succeeding},
    )

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "partial"
    assert failing.calls == 3
    assert succeeding.calls == 4
    assert run.provider_summary["arxiv"]["circuit_open"] is True
    assert run.provider_summary["openalex"]["errors"] == 0
    arxiv_state = search_repository.get_state(
        profile.id,
        "regularization",
        "arxiv",
        _query_key(service, query_index=0),
    )
    assert arxiv_state is not None and arxiv_state.completed_through is None
    connection.close()


def test_manual_run_request_is_atomically_claimed_and_finished_by_tick(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    service, _, _, _ = _service(tmp_path, connection, provider)
    request = service.queue_manual_run(
        "continual-learning",
        {"lens_overrides": {"regularization": True}},
    )

    run = service.tick()

    stored = service.run_request_repository.get(request.id)
    assert run is not None
    assert run.trigger == "manual"
    assert run.request_id == request.id
    assert run.status == "success"
    assert stored is not None and stored.status == "completed"
    assert stored.claimed_at == _NOW.isoformat()
    assert stored.completed_at == _NOW.isoformat()
    assert provider.calls == 1
    connection.close()


def test_manual_run_can_temporarily_enable_a_disabled_lens(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    profile = _profile()
    disabled_lens = profile.lenses[0].model_copy(update={"enabled": False})
    profile = profile.model_copy(update={"lenses": [disabled_lens]})
    service, _, _, _ = _service(tmp_path, connection, provider, profile=profile)
    request = service.queue_manual_run(
        profile.id, {"lens_overrides": {disabled_lens.id: True}}
    )

    run = service.tick()

    assert run is not None and run.status == "success"
    assert run.request_id == request.id
    assert run.effective_config["lens_overrides"] == {disabled_lens.id: True}
    assert provider.calls == 1
    connection.close()


def test_tick_does_not_claim_request_when_another_process_holds_global_lock(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    service, _, _, _ = _service(tmp_path, connection, provider)
    request = service.queue_manual_run("continual-learning")
    competing_lock = GlobalResearchLock(service.global_lock.path)
    assert competing_lock.try_acquire() is True
    try:
        assert service.tick() is None
    finally:
        competing_lock.release()

    stored = service.run_request_repository.get(request.id)
    assert stored is not None and stored.status == "pending"
    assert provider.calls == 0
    connection.close()


def test_manual_run_queue_rejects_unknown_lenses_and_invalid_ranges(tmp_path):
    connection = connect_database(":memory:")
    service, _, _, _ = _service(tmp_path, connection, FakeProvider([]))

    with pytest.raises(ValueError, match="unknown Lens"):
        service.queue_manual_run(
            "continual-learning", {"lens_overrides": {"missing": True}}
        )
    with pytest.raises(ValueError, match="timezone"):
        service.queue_manual_run(
            "continual-learning", {"manual_range": ["2026-10-01T00:00:00", "2026-10-02"]}
        )
    assert connection.execute("SELECT COUNT(*) FROM research_run_requests").fetchone()[0] == 0
    connection.close()


def test_manual_run_queue_claims_oldest_request_once(tmp_path):
    connection = connect_database(":memory:")
    repository = ResearchRunRequestRepository(connection)
    older = repository.enqueue(
        "continual-learning", {}, _NOW - timedelta(minutes=2), request_id="older"
    )
    repository.enqueue(
        "continual-learning", {}, _NOW - timedelta(minutes=1), request_id="newer"
    )

    claimed = repository.claim_next(_NOW)
    second_claim = repository.claim_next(_NOW)

    assert older.status == "pending"
    assert claimed is not None and claimed.id == "older" and claimed.status == "claimed"
    assert second_claim is not None and second_claim.id == "newer"
    assert repository.get("older").status == "claimed"
    connection.close()


def test_stale_claim_is_requeued_and_old_running_attempt_is_interrupted(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    service, run_repository, _, _ = _service(tmp_path, connection, provider)
    old_time = _NOW - timedelta(hours=2)
    request = service.run_request_repository.enqueue(
        "continual-learning", {}, old_time, request_id="stale-request"
    )
    service.run_request_repository.claim_next(old_time)
    old_run = ResearchRunRecord(
        id="stale-manual-run",
        profile_id="continual-learning",
        request_id=request.id,
        trigger="manual",
        status="running",
        profile_content_hash="profile-hash",
        effective_config={},
        provider_summary={},
        started_at=old_time.isoformat(),
    )
    run_repository.create(old_run)

    replacement = service.tick()

    assert replacement is not None and replacement.request_id == request.id
    assert run_repository.get(old_run.id).status == "interrupted"
    assert service.run_request_repository.get(request.id).status == "completed"
    assert provider.calls == 1
    connection.close()


def test_tick_selects_most_overdue_profile_and_skips_paused_profiles(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    service, _, _, _ = _service(tmp_path, connection, provider)
    first = _profile().model_copy(update={"id": "first-profile"})
    second = _profile().model_copy(update={"id": "second-profile"})
    registry = service.profile_registry
    service.profile_registry = type(registry)(
        registry.global_config,
        (first, second),
        {first.id: Path("first-profile.yaml"), second.id: Path("second-profile.yaml")},
        {first.id: "a" * 64, second.id: "b" * 64},
    )
    service.profile_state_repository.record_successful_scheduled_run(
        first.id, _NOW - timedelta(days=2)
    )
    service.profile_state_repository.record_successful_scheduled_run(
        second.id, _NOW - timedelta(days=5)
    )

    run = service.tick()

    assert run is not None and run.profile_id == second.id
    assert provider.calls == 1
    service.profile_state_repository.pause_until(
        first.id, _NOW + timedelta(days=1), _NOW
    )
    service.profile_state_repository.pause_until(
        second.id, _NOW + timedelta(days=1), _NOW
    )
    assert service.tick() is None
    assert provider.calls == 1
    connection.close()


def test_tick_skips_profiles_without_active_default_lenses(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    service, _, _, _ = _service(tmp_path, connection, provider)
    source_profile = _profile()
    profile = source_profile.model_copy(
        update={
            "lenses": [
                lens.model_copy(update={"enabled": False})
                for lens in source_profile.lenses
            ]
        }
    )
    service.profile_registry = _profile_registry(profile)

    assert service.tick() is None
    assert provider.calls == 0
    assert service.run_repository.list_for_profile(profile.id) == []

    reenabled = profile.model_copy(
        update={
            "lenses": [
                profile.lenses[0].model_copy(update={"enabled": True}),
                *profile.lenses[1:],
            ]
        }
    )
    service.profile_registry = _profile_registry(reenabled)

    run = service.tick()

    assert run is not None and run.status == "success"
    assert provider.calls == 1
    connection.close()


def test_scheduled_failures_wait_for_retry_cooldown_but_manual_runs_do_not(
    tmp_path,
):
    connection = connect_database(":memory:")
    provider = FakeProvider([], error=True)
    service, _, _, _ = _service(tmp_path, connection, provider)
    now = [_NOW]
    service.clock = lambda: now[0]

    first = service.tick()

    assert first is not None and first.status == "partial"
    assert first.trigger == "scheduled"
    assert provider.calls == 1

    now[0] = _NOW + timedelta(minutes=2)
    assert service.tick() is None
    assert provider.calls == 1

    service.queue_manual_run("continual-learning")
    manual = service.tick()
    assert manual is not None and manual.trigger == "manual"
    assert provider.calls == 2

    now[0] = _NOW + timedelta(minutes=59)
    assert service.tick() is None
    assert provider.calls == 2

    now[0] = _NOW + timedelta(minutes=60)
    retry = service.tick()
    assert retry is not None and retry.status == "partial"
    assert retry.trigger == "scheduled"
    assert provider.calls == 3
    connection.close()


def test_resume_catchup_days_are_applied_to_the_next_scheduled_run(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    service, _, search_repository, _ = _service(tmp_path, connection, provider)
    service.resume_profile(
        "continual-learning", strategy="catch_up", catchup_days=7, now=_NOW
    )

    run = service.tick()

    assert run is not None and run.status == "success"
    assert run.effective_config["resume_strategy"] == "last_window"
    assert run.effective_config["catchup_days_override"] == 7
    query = service.query_builder.build(service.profile_registry.get("continual-learning"))[0]
    state = search_repository.get_state(
        "continual-learning", query.lens_id, "arxiv", query.query_key
    )
    floor = _NOW - timedelta(days=7)
    assert state is not None and state.overlap_floor == floor.isoformat()
    assert provider.search_ranges[0][0] == floor
    connection.close()


def test_resume_catchup_defaults_to_profile_max_catchup_days(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    profile = _profile()
    profile = profile.model_copy(
        update={
            "search": profile.search.model_copy(update={"max_catchup_days": 12})
        }
    )
    service, _, search_repository, _ = _service(
        tmp_path, connection, provider, profile=profile
    )

    service.resume_profile("continual-learning", strategy="catch_up", now=_NOW)
    run = service.tick()

    assert run is not None and run.status == "success"
    assert run.effective_config["catchup_days_override"] == 12
    query = service.query_builder.build(service.profile_registry.get("continual-learning"))[0]
    state = search_repository.get_state(
        "continual-learning", query.lens_id, "arxiv", query.query_key
    )
    floor = _NOW - timedelta(days=12)
    assert state is not None and state.overlap_floor == floor.isoformat()
    assert provider.search_ranges[0][0] == floor
    connection.close()


def test_resume_from_now_floor_prevents_overlap_reopening_skipped_history(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([])
    service, _, search_repository, _ = _service(tmp_path, connection, provider)
    profile = service.profile_registry.get("continual-learning")
    query = service.query_builder.build(profile)[0]
    stale = _NOW - timedelta(days=10)
    search_repository.record_attempt(
        profile.id, query.lens_id, "arxiv", query.query_key, query.text, stale.isoformat()
    )
    search_repository.complete_slice(
        profile.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        stale.isoformat(),
        stale.isoformat(),
    )
    config = service.profile_registry.global_config
    service.profile_registry = replace(
        service.profile_registry,
        global_config=config.model_copy(
            update={
                "runtime": config.runtime.model_copy(update={"overlap_hours": 48})
            }
        ),
    )
    resume_at = _NOW + timedelta(hours=1)
    service.pause_profile(profile.id, resume_at + timedelta(days=1), now=_NOW)

    service.resume_profile(profile.id, strategy="from_now", now=resume_at)

    state = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert state.completed_through == resume_at.isoformat()
    assert state.overlap_floor == resume_at.isoformat()
    next_plan = service.watermarks.build_plan(
        profile,
        query,
        "arxiv",
        resume_at + timedelta(days=1),
        service.profile_registry.global_config,
    )
    assert next_plan.slices[0].start_at == resume_at
    connection.close()


class FakeProvider:
    def __init__(self, pages, name="arxiv", error=False):
        self.name = name
        self.pages = list(pages)
        self.error = error
        self.calls = 0
        self.limit_requests = []
        self.search_ranges = []
        self.before_search = None

    def search(self, query, start_at, end_at, cursor=None, limit=None):
        self.calls += 1
        self.limit_requests.append(limit)
        self.search_ranges.append((start_at, end_at))
        if self.before_search is not None:
            self.before_search()
        if self.error:
            raise ResearchProviderError(self.name, "temporary failure", retryable=True)
        if self.pages:
            page = self.pages.pop(0)
            if limit is not None and len(page.works) > limit:
                remainder = page.works[limit:]
                self.pages.insert(
                    0,
                    ProviderPage(
                        works=remainder,
                        next_cursor=page.next_cursor,
                        total_count=page.total_count,
                    ),
                )
                return ProviderPage(
                    works=page.works[:limit],
                    next_cursor="fake-page-{}".format(self.calls),
                    total_count=page.total_count,
                )
            return page
        return ProviderPage(works=())


class FakeEnrichmentProvider(FakeProvider):
    def __init__(self, fail=False, name="openalex"):
        super().__init__([], name=name)
        self.fail_enrichment = fail
        self.enrichment_calls = 0

    def enrich(self, work):
        self.enrichment_calls += 1
        if self.fail_enrichment:
            raise ResearchProviderError(
                self.name, "enrichment failed", retryable=True
            )
        return ProviderWork(
            provider="openalex",
            provider_record_id="W123456",
            title="A provider-preferred alternate title",
            abstract="Enriched abstract with more detail.",
            authors=("Ada Lovelace", "Alan Turing"),
            year=2026,
            published_at="2026-10-02",
            venue="Journal of Learning",
            doi=work.doi or "10.1000/enriched",
            arxiv_id=work.arxiv_id,
            openalex_id=work.openalex_id or "W123456",
            url="https://openalex.org/W123456",
        )


class FakeContextBuilder:
    def build(self, work, profile, matched_lens, keywords=()):
        return ResearchContextPack(
            focus_query="{} {}".format(work.title, work.abstract or "summary"),
            cards=(),
            budget=8,
            omitted_count=0,
        )


class RecordingContextBuilder:
    def __init__(self, delegate):
        self.delegate = delegate
        self.work_titles = []

    def build(self, work, profile, matched_lens, keywords=()):
        self.work_titles.append(work.title)
        return self.delegate.build(work, profile, matched_lens, keywords)


def _service(
    tmp_path,
    connection,
    provider,
    profile=None,
    additional_providers=None,
    analysis_output=None,
):
    root = tmp_path / "repo"
    (root / "knowledge" / "sources").mkdir(parents=True, exist_ok=True)
    profile = profile or _profile()
    registry = _profile_registry(profile)
    research_repository = ResearchRepository(connection)
    candidate_repository = ResearchCandidateRepository(connection)
    candidate_service = ResearchCandidateService(
        candidate_repository, clock=lambda: _NOW
    )
    term_candidate_service = TermCandidateService(
        root, TermCandidateRepository(connection)
    )
    ai_client = MockDeepSeekClient(
        {"research_candidate_analysis": analysis_output or _analysis_output()}
    )
    analysis_service = ResearchAnalysisService(
        research_repository,
        AIGateway(ai_client),
        clock=lambda: _NOW,
        repository_root=root,
    )
    providers = {provider.name: provider}
    providers.update(additional_providers or {})
    service = ResearchService(
        repository_root=root,
        connection=connection,
        profile_registry=registry,
        providers=providers,
        context_builder=FakeContextBuilder(),
        analysis_service=analysis_service,
        candidate_service=candidate_service,
        term_candidate_service=term_candidate_service,
        source_registry=SourceRegistry(()),
        global_lock=GlobalResearchLock(tmp_path / "runtime" / "research.lock"),
        clock=lambda: _NOW,
        id_factory=lambda: "test-{}".format(uuid_counter()),
    )
    return service, service.run_repository, service.search_repository, ai_client


def _profile_registry(profile):
    global_config = ResearchGlobalConfig.model_validate(
        {
            "schema_version": 1,
            "providers": {"timeout_seconds": 20, "max_retries": 3},
            "runtime": {
                "slice_days": 1,
                "overlap_hours": 0,
                "retry_cooldown_minutes": 60,
            },
            "analysis": {"max_context_entities": 8, "timeout_seconds": 60},
            "ranking": {
                "strict": {
                    "profile_relevance_weight": 0.5,
                    "knowledge_relevance_weight": 0.35,
                    "novelty_weight": 0.15,
                },
                "balanced": {
                    "profile_relevance_weight": 0.4,
                    "knowledge_relevance_weight": 0.3,
                    "novelty_weight": 0.3,
                },
                "explore": {
                    "profile_relevance_weight": 0.3,
                    "knowledge_relevance_weight": 0.2,
                    "novelty_weight": 0.5,
                },
            },
        }
    )
    return ResearchProfileRegistry(
        global_config,
        (profile,),
        {profile.id: Path("profile.yaml")},
        {profile.id: "a" * 64},
        {
            profile.id: yaml.safe_dump(
                profile.model_dump(mode="json"), allow_unicode=True, sort_keys=False
            )
        },
    )


def _profile(
    max_new_candidates=20,
    discovery=("arxiv",),
    queries=("fisher information",),
    enrichment=(),
):
    lenses = [
        {
            "id": "regularization",
            "title": "Regularization",
            "enabled": True,
            "priority": "high",
            "queries": [query],
            "include_terms": ["fisher information"],
            "exclude_terms": [],
        }
        for query in queries
    ]
    # Keep multiple query tests on one Lens while preserving stable query IDs.
    if len(lenses) > 1:
        lenses = [lenses[0] | {"queries": list(queries)}]
    return ResearchProfile.model_validate(
        {
            "schema_version": 1,
            "id": "continual-learning",
            "title": "Continual Learning",
            "enabled": True,
            "lenses": lenses,
            "exclude_terms": [],
            "providers": {
                "discovery": list(discovery),
                "enrichment": list(enrichment),
            },
            "context": {
                "collections": [],
                "documents": [],
                "dynamic_retrieval": {"enabled": False, "scope": "entire-library"},
            },
            "schedule": {"mode": "daily"},
            "search": {
                "breadth": "balanced",
                "initial_lookback_days": 1,
                "max_catchup_days": 30,
                "max_candidates_per_run": 10,
                "max_analyses_per_run": 30,
            },
            "inbox": {"max_new_candidates": max_new_candidates},
            "ai_analysis": {"enabled": True, "provider": "deepseek"},
        }
    )


def _provider_work():
    return ProviderWork(
        provider="arxiv",
        provider_record_id="2401.12345",
        title="Fisher Information for Continual Learning",
        abstract="Fisher information measures parameter importance.",
        authors=("Ada Lovelace",),
        year=2026,
        published_at="2026-10-02",
        arxiv_id="2401.12345",
        url="https://arxiv.org/abs/2401.12345",
    )


def _analysis_output(relevant=True):
    return {
        "relevant": relevant,
        "profile_relevance": 0.9,
        "knowledge_relevance": 0.8,
        "novelty_to_library": 0.7,
        "matched_lenses": ["regularization"],
        "matched_topics": ["parameter importance"],
        "summary": "The paper studies parameter importance.",
        "why_relevant": "It matches the current Research Lens.",
        "reading_reason": "It may add useful detail.",
        "summary_zh": "这篇论文研究参数重要性。",
        "why_relevant_zh": "这与当前 Research Lens 相符。",
        "reading_reason_zh": "它可能补充有用的细节。",
        "readiness": "high",
        "known_prerequisites": ["Fisher information"],
        "missing_prerequisites": [],
        "why_now": "It builds on the selected regularization context.",
        "term_candidates": [],
        "existing_relations": [],
        "suggested_collection": None,
        "suggested_section": None,
    }


def _seed_existing_new_candidate(connection, profile):
    work = ResearchRepository(connection)
    work.insert_work(
        ResearchWorkRecord(
            id="already-in-inbox",
            canonical_key="doi:10.1000/inbox",
            title="Existing Inbox Work",
            normalized_title="existing inbox work",
            created_at=_NOW.isoformat(),
            updated_at=_NOW.isoformat(),
        )
    )
    candidate = ResearchCandidateRecord(
        id="existing-candidate",
        work_id="already-in-inbox",
        profile_id=profile.id,
        status="new",
        analysis_id="analysis-id",
        created_at=_NOW.isoformat(),
        updated_at=_NOW.isoformat(),
    )
    ResearchCandidateRepository(connection).create_if_capacity(candidate, 5)


def _seed_identity_collision(service):
    first = service.deduplicator.record_discovery(
        "continual-learning",
        "regularization",
        "seed-identity-a",
        "fisher information",
        _provider_work().model_copy(
            update={
                "provider_record_id": "seed-identity-a",
                "doi": "10.1000/identity-a",
            }
        ),
        discovered_at=_NOW,
    )
    second = service.deduplicator.record_discovery(
        "continual-learning",
        "regularization",
        "seed-identity-b",
        "fisher information",
        _provider_work().model_copy(
            update={
                "provider_record_id": "seed-identity-b",
                "doi": "10.1000/identity-b",
                "arxiv_id": None,
            }
        ),
        discovered_at=_NOW,
    )
    return first.work, second.work


def _assert_running_run_exists(run_repository):
    runs = run_repository.list_for_profile("continual-learning")
    assert runs and runs[0].status == "running"


def _assert_no_ai_calls(ai_client):
    assert ai_client.calls == []


def _query_key(service, query_index=0):
    queries = service.query_builder.build(
        service.profile_registry.get("continual-learning")
    )
    return queries[query_index].query_key


def uuid_counter():
    uuid_counter.value += 1
    return uuid_counter.value


uuid_counter.value = 0
