from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.app.db.connection import connect_database
from backend.app.domain.research import ResearchGlobalConfig, ResearchProfile
from backend.app.domain.research_runtime import (
    ResearchCandidateRecord,
    ResearchContextPack,
    ResearchRunRecord,
    ResearchWorkRecord,
)
from backend.app.repositories.research_candidate_repository import (
    ResearchCandidateRepository,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.repositories.research_run_repository import ResearchRunRepository
from backend.app.repositories.research_run_request_repository import (
    ResearchRunRequestRepository,
)
from backend.app.repositories.research_search_repository import ResearchSearchRepository
from backend.app.services.ai_client import MockDeepSeekClient
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
from backend.app.services.research_service import ResearchService
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
    assert (run.fetched_count, run.new_work_count, run.analyzed_count, run.surfaced_count) == (
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
    state = search_repository.get_state(
        profile.id, "regularization", "arxiv", _query_key(service)
    )
    assert state is not None
    assert state.completed_through is None
    assert state.last_attempt_at is not None
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
    assert first.analyzed_count == restarted.analyzed_count == 1
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
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()
    assert second.acquire() is True
    second.release()


def test_provider_failures_open_a_run_local_circuit_and_other_provider_continues(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile(
        discovery=("arxiv", "openalex"),
        queries=("fisher information", "parameter importance", "regularization"),
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
    assert succeeding.calls == 3
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


def test_tick_does_not_claim_request_when_another_process_holds_global_lock(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    service, _, _, _ = _service(tmp_path, connection, provider)
    request = service.queue_manual_run("continual-learning")
    competing_lock = GlobalResearchLock(service.global_lock.path)
    assert competing_lock.acquire() is True
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


class FakeProvider:
    def __init__(self, pages, name="arxiv", error=False):
        self.name = name
        self.pages = list(pages)
        self.error = error
        self.calls = 0
        self.before_search = None

    def search(self, query, start_at, end_at, cursor=None):
        self.calls += 1
        if self.before_search is not None:
            self.before_search()
        if self.error:
            raise ResearchProviderError(self.name, "temporary failure", retryable=True)
        if self.pages:
            return self.pages.pop(0)
        return ProviderPage(works=())


class FakeEnrichmentProvider(FakeProvider):
    def __init__(self, fail=False):
        super().__init__([], name="openalex")
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
            doi="10.1000/enriched",
            arxiv_id=work.arxiv_id,
            openalex_id="W123456",
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
    ai_client = MockDeepSeekClient(
        {"research_candidate_analysis": analysis_output or _analysis_output()}
    )
    analysis_service = ResearchAnalysisService(
        research_repository,
        AIGateway(ai_client),
        clock=lambda: _NOW,
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
            "runtime": {"slice_days": 1, "overlap_hours": 0},
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


def _assert_running_run_exists(run_repository):
    runs = run_repository.list_for_profile("continual-learning")
    assert runs and runs[0].status == "running"


def _query_key(service, query_index=0):
    queries = service.query_builder.build(
        service.profile_registry.get("continual-learning")
    )
    return queries[query_index].query_key


def uuid_counter():
    uuid_counter.value += 1
    return uuid_counter.value


uuid_counter.value = 0
