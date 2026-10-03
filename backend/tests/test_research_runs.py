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


def test_disabled_ai_skips_scheduled_and_rejects_manual_queue_without_advancing_watermark(
    tmp_path,
):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    base_profile = _profile()
    profile = base_profile.model_copy(
        update={
            "ai_analysis": base_profile.ai_analysis.model_copy(
                update={"enabled": False}
            )
        }
    )
    service, run_repository, _, ai_client = _service(
        tmp_path, connection, provider, profile=profile
    )

    assert service.tick() is None
    assert provider.calls == 0
    assert service.profile_state_repository.get(profile.id) is None

    with pytest.raises(ValueError, match="Research AI Analysis is disabled"):
        service.queue_manual_run(profile.id)

    assert provider.calls == 0
    assert ai_client.calls == []
    assert service.profile_state_repository.get(profile.id) is None
    assert connection.execute("SELECT COUNT(*) FROM research_search_state").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM research_run_requests").fetchone()[0] == 0
    assert run_repository.list_for_profile(profile.id) == []
    connection.close()


@pytest.mark.parametrize(
    ("blocker", "message"),
    [
        ("profile_disabled", "Research Profile is disabled"),
        ("ai_disabled", "Research AI Analysis is disabled"),
        ("paused", "Research Profile is paused"),
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
    elif blocker == "ai_disabled":
        profile = base_profile.model_copy(
            update={
                "ai_analysis": base_profile.ai_analysis.model_copy(
                    update={"enabled": False}
                )
            }
        )
    else:
        profile = base_profile
    if blocker == "inbox_full":
        _seed_existing_new_candidate(connection, profile)
    service, _, _, _ = _service(tmp_path, connection, FakeProvider([]), profile=profile)
    if blocker == "paused":
        service.pause_profile(profile.id, _NOW + timedelta(days=1))

    with pytest.raises(ValueError, match=message):
        service.queue_manual_run(profile.id)

    assert connection.execute("SELECT COUNT(*) FROM research_run_requests").fetchone()[0] == 0
    connection.close()


def test_queued_manual_run_rechecks_pause_before_discovery(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    service, _, _, _ = _service(tmp_path, connection, provider)
    request = service.queue_manual_run("continual-learning")
    service.pause_profile("continual-learning", _NOW + timedelta(days=1))

    run = service.tick()

    assert run is not None and run.status == "skipped_paused"
    assert run.request_id == request.id
    assert service.run_request_repository.get(request.id).status == "completed"
    assert provider.calls == 0
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
    assert provider.limit_requests == [1]
    state = search_repository.get_state(
        profile.id, "regularization", "arxiv", _query_key(service)
    )
    assert state is not None
    assert state.completed_through is None
    assert state.last_attempt_at is not None
    connection.close()


def test_provider_request_is_bounded_by_one_remaining_inbox_slot(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=(_provider_work(),))])
    profile = _profile(max_new_candidates=2)
    _seed_existing_new_candidate(connection, profile)
    service, _, _, _ = _service(tmp_path, connection, provider, profile=profile)

    run = service.run_profile(profile.id)

    assert run is not None and run.status == "capacity_reached"
    assert run.surfaced_count == 1
    assert provider.limit_requests == [1]
    assert provider.calls == 1
    connection.close()


def test_per_run_candidate_limit_succeeds_without_advancing_incomplete_slice(
    tmp_path,
):
    connection = connect_database(":memory:")
    first_work = _provider_work()
    second_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2402.00001",
        title="A second Fisher Information study on parameter importance",
        abstract="Fisher information offers a distinct measure of parameter importance.",
        authors=("Grace Hopper",),
        year=2026,
        published_at="2026-10-03",
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
                update={"max_candidates_per_run": 1}
            )
        }
    )
    service, _, search_repository, _ = _service(
        tmp_path, connection, provider, profile=profile
    )
    now = [_NOW]
    service.clock = lambda: now[0]

    first_run = service.tick()

    assert first_run is not None and first_run.status == "success"
    assert first_run.surfaced_count == 1
    assert service.candidate_service.remaining_capacity(profile) == 9
    assert provider.calls == 1
    state = search_repository.get_state(
        profile.id, "regularization", "arxiv", _query_key(service)
    )
    assert state is not None and state.completed_through is None
    assert service.tick() is None
    assert provider.calls == 1

    now[0] = _NOW + timedelta(days=1)
    second_run = service.tick()

    assert second_run is not None and second_run.status == "success"
    assert second_run.surfaced_count == 1
    assert provider.calls == 2
    state = search_repository.get_state(
        profile.id, "regularization", "arxiv", _query_key(service)
    )
    assert state is not None and state.completed_through is None
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
    assert run.analyzed_count == 2
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
    assert run.analyzed_count == 1
    assert run.surfaced_count == 2
    assert ai_client.calls == ["research_candidate_analysis"]
    assert service.candidate_repository.count_new(profile.id) == 2
    state = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert state is not None and state.completed_through is None
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
    assert run.analyzed_count == 1
    assert ai_client.calls == ["research_candidate_analysis"]
    state = search_repository.get_state(
        profile.id, query.lens_id, "arxiv", query.query_key
    )
    assert state is not None and state.completed_through == _NOW.isoformat()
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
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()
    assert second.acquire() is True
    second.release()


def test_global_research_lock_exclusive_acquire_rejects_existing_owner(tmp_path):
    lock = GlobalResearchLock(tmp_path / "runtime" / "research.lock")
    assert lock.acquire() is True
    try:
        assert lock.acquire_exclusive() is False
    finally:
        lock.release()


def test_reactivation_review_requires_a_choice_for_stale_watermarks(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile().model_copy(update={"enabled": False})
    service, _, search_repository, _ = _service(
        tmp_path, connection, FakeProvider([]), profile=profile
    )
    query = service.query_builder.build(profile)[0]
    stale = _NOW - timedelta(days=90)
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

    candidate = profile.model_copy(update={"enabled": True})
    review = service.reactivation_review(candidate)

    assert review == {
        "required": True,
        "triggers": ["profile_enabled"],
        "max_catchup_days": profile.search.max_catchup_days,
        "strategies": ["last_window", "all", "from_now"],
    }

    service.pause_profile(profile.id, _NOW + timedelta(days=5), _NOW)
    state_before = service.profile_state_repository.get(profile.id)
    service.apply_reactivation_strategy(
        profile.id, "last_window", now=_NOW
    )
    state_after = service.profile_state_repository.get(profile.id)
    assert state_after.paused_until == state_before.paused_until
    assert service.control_event_repository.latest_resume(profile.id)["payload"] == {
        "strategy": "catch_up",
        "catchup_days": profile.search.max_catchup_days,
    }
    connection.close()


def test_reactivation_review_covers_a_lens_enabled_on_an_active_profile(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile()
    disabled_lens = profile.lenses[0].model_copy(
        update={"id": "replay", "title": "Replay", "enabled": False, "queries": ["experience replay"]}
    )
    current = profile.model_copy(update={"lenses": [*profile.lenses, disabled_lens]})
    candidate = current.model_copy(
        update={
            "lenses": [
                profile.lenses[0],
                disabled_lens.model_copy(update={"enabled": True}),
            ]
        }
    )
    service, _, search_repository, _ = _service(
        tmp_path, connection, FakeProvider([]), profile=current
    )
    query = service.query_builder.build(candidate)[1]
    stale = _NOW - timedelta(days=90)
    search_repository.record_attempt(
        candidate.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        query.text,
        stale.isoformat(),
    )
    search_repository.complete_slice(
        candidate.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        stale.isoformat(),
        stale.isoformat(),
    )

    review = service.reactivation_review(candidate)

    assert review["required"] is True
    assert review["triggers"] == ["lens_enabled:replay"]
    connection.close()


def test_reactivation_review_covers_a_lens_enabled_on_an_active_profile(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile()
    disabled_lens = profile.lenses[0].model_copy(
        update={"id": "replay", "title": "Replay", "enabled": False, "queries": ["experience replay"]}
    )
    current = profile.model_copy(update={"lenses": [*profile.lenses, disabled_lens]})
    candidate = current.model_copy(
        update={
            "lenses": [
                profile.lenses[0],
                disabled_lens.model_copy(update={"enabled": True}),
            ]
        }
    )
    service, _, search_repository, _ = _service(
        tmp_path, connection, FakeProvider([]), profile=current
    )
    query = service.query_builder.build(candidate)[1]
    stale = _NOW - timedelta(days=90)
    search_repository.record_attempt(
        candidate.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        query.text,
        stale.isoformat(),
    )
    search_repository.complete_slice(
        candidate.id,
        query.lens_id,
        "arxiv",
        query.query_key,
        stale.isoformat(),
        stale.isoformat(),
    )

    review = service.reactivation_review(candidate)

    assert review["required"] is True
    assert review["triggers"] == ["lens_enabled:replay"]
    connection.close()


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
    service, _, _, _ = _service(tmp_path, connection, provider)
    service.resume_profile(
        "continual-learning", strategy="catch_up", catchup_days=7, now=_NOW
    )

    run = service.tick()

    assert run is not None and run.status == "success"
    assert run.effective_config["resume_strategy"] == "last_window"
    assert run.effective_config["catchup_days_override"] == 7
    connection.close()


class FakeProvider:
    def __init__(self, pages, name="arxiv", error=False):
        self.name = name
        self.pages = list(pages)
        self.error = error
        self.calls = 0
        self.limit_requests = []
        self.before_search = None

    def search(self, query, start_at, end_at, cursor=None, limit=None):
        self.calls += 1
        self.limit_requests.append(limit)
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
