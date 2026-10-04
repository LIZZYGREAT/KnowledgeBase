from datetime import datetime, timedelta, timezone

import pytest

from backend.app.db.connection import connect_database
from backend.app.domain.research import ResearchGlobalConfig, ResearchProfile
from backend.app.repositories.research_search_repository import ResearchSearchRepository
from backend.app.services.research_query_builder import ResearchQueryBuilder
from backend.app.services.research_watermark import ResearchWatermarkService


_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def test_cold_start_uses_initial_lookback_and_splits_into_daily_slices():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        plan = service.build_plan(profile, query, "arxiv", _NOW, global_config)

        assert plan.manual is False
        assert plan.previous_watermark is None
        assert len(plan.slices) == 30
        assert plan.slices[0].start_at == _NOW - timedelta(days=30)
        assert plan.slices[-1].end_at == _NOW
        assert all(item.end_at - item.start_at <= timedelta(days=1) for item in plan.slices)
        assert repository.get_state(
            profile.id, query.lens_id, "arxiv", query.query_key
        ) is None
    finally:
        connection.close()


def test_incremental_search_starts_at_watermark_minus_overlap():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        watermark = _NOW - timedelta(days=1)
        _seed_watermark(repository, profile, query, "arxiv", watermark)

        plan = service.build_plan(profile, query, "arxiv", _NOW, global_config)

        assert plan.previous_watermark == watermark
        assert plan.slices[0].start_at == watermark - timedelta(hours=48)
        assert plan.slices[-1].end_at == _NOW
        assert len(plan.slices) == 3
    finally:
        connection.close()


def test_from_now_overlap_floor_prevents_reopening_skipped_history():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        _seed_watermark(
            repository, profile, query, "arxiv", _NOW - timedelta(days=3)
        )

        service.skip_profile_to_now(profile, _NOW)

        state = repository.get_state(
            profile.id, query.lens_id, "arxiv", query.query_key
        )
        assert state.completed_through == _NOW.isoformat()
        assert state.overlap_floor == _NOW.isoformat()
        next_plan = service.build_plan(
            profile, query, "arxiv", _NOW + timedelta(days=1), global_config
        )
        assert next_plan.slices[0].start_at == _NOW

        changed_lens = profile.lenses[0].model_copy(
            update={"queries": ["a newly added query"]}
        )
        changed_profile = profile.model_copy(
            update={"lenses": [changed_lens, *profile.lenses[1:]]}
        )
        new_query = service.query_builder.build(changed_profile)[0]
        new_query_plan = service.build_plan(
            changed_profile, new_query, "arxiv", _NOW, global_config
        )
        assert new_query_plan.previous_watermark is None
        assert new_query_plan.slices[0].start_at == _NOW - timedelta(days=30)
    finally:
        connection.close()


def test_manual_incremental_uses_watermark_window_without_advancing_it():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        watermark = _NOW - timedelta(days=1)
        _seed_watermark(repository, profile, query, "arxiv", watermark)
        state_before = repository.get_state(
            profile.id, query.lens_id, "arxiv", query.query_key
        )

        plan = service.build_plan(
            profile,
            query,
            "arxiv",
            _NOW,
            global_config,
            manual_incremental=True,
        )

        assert plan.manual is True
        assert plan.previous_watermark == watermark
        assert plan.slices[0].start_at == watermark - timedelta(hours=48)
        assert plan.slices[-1].end_at == _NOW
        with pytest.raises(ValueError, match="do not update scheduled watermarks"):
            service.mark_attempt(plan, plan.slices[0], _NOW)
        with pytest.raises(ValueError, match="do not update scheduled watermarks"):
            service.complete_slice(plan, plan.slices[0], _NOW)
        state_after = repository.get_state(
            profile.id, query.lens_id, "arxiv", query.query_key
        )
        assert state_after == state_before
    finally:
        connection.close()


def test_watermark_advances_only_after_a_slice_is_completed():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        plan = service.build_plan(profile, query, "arxiv", _NOW, global_config)
        first_slice, second_slice = plan.slices[:2]

        attempted = service.mark_attempt(plan, first_slice, _NOW)
        assert attempted.completed_through is None
        first_completed = service.complete_slice(plan, first_slice, _NOW)
        assert first_completed.completed_through == first_slice.end_at.isoformat()

        service.mark_attempt(plan, second_slice, _NOW + timedelta(hours=1))
        after_failed_second_slice = repository.get_state(
            profile.id, query.lens_id, "arxiv", query.query_key
        )
        assert after_failed_second_slice.completed_through == first_slice.end_at.isoformat()

        second_completed = service.complete_slice(
            plan, second_slice, _NOW + timedelta(hours=2)
        )
        assert second_completed.completed_through == second_slice.end_at.isoformat()
        assert second_completed.last_success_at == (_NOW + timedelta(hours=2)).isoformat()
    finally:
        connection.close()


def test_manual_historical_search_is_sliced_without_touching_scheduled_state():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        start = datetime(2016, 1, 1, tzinfo=timezone.utc)
        end = datetime(2018, 1, 1, tzinfo=timezone.utc)
        plan = service.build_plan(
            profile,
            query,
            "arxiv",
            _NOW,
            global_config,
            manual_range=(start, end),
        )

        assert plan.manual is True
        assert plan.slices[0].start_at == start
        assert plan.slices[-1].end_at == end
        assert len(plan.slices) == 731
        with pytest.raises(ValueError, match="do not update scheduled watermarks"):
            service.mark_attempt(plan, plan.slices[0], _NOW)
        assert repository.get_state(profile.id, query.lens_id, "arxiv", query.query_key) is None
    finally:
        connection.close()


def test_last_window_and_all_catchup_options_and_audited_from_now_skip():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        old_watermark = _NOW - timedelta(days=74)
        _seed_watermark(repository, profile, query, "arxiv", old_watermark)
        choices = service.resume_options(profile, None, _NOW)
        assert choices == ("last_window", "all", "from_now")

        last_window = service.build_plan(
            profile,
            query,
            "arxiv",
            _NOW,
            global_config,
            resume_strategy="last_window",
        )
        all_history = service.build_plan(
            profile,
            query,
            "arxiv",
            _NOW,
            global_config,
            resume_strategy="all",
        )
        skip_plan = service.build_plan(
            profile,
            query,
            "arxiv",
            _NOW,
            global_config,
            resume_strategy="from_now",
        )
        assert last_window.slices[0].start_at == _NOW - timedelta(days=30)
        assert all_history.slices[0].start_at == old_watermark - timedelta(hours=48)
        assert skip_plan.slices == ()
        assert skip_plan.watermark_skip_required is True

        skipped_states = service.skip_profile_to_now(profile, _NOW)
        assert len(skipped_states) == 4  # two enabled queries x two discovery providers
        assert all(state.completed_through == _NOW.isoformat() for state in skipped_states)
        seeded_state = next(
            state
            for state in skipped_states
            if state.provider == "arxiv" and state.query_key == query.query_key
        )
        assert seeded_state.last_success_at == old_watermark.isoformat()
        assert sum(state.last_success_at is None for state in skipped_states) == 3
        events = repository.list_control_events(profile.id)
        assert len(events) == 1
        assert events[0]["event_type"] == "watermark_skip"
        assert events[0]["payload"]["strategy"] == "from_now"
    finally:
        connection.close()


def test_last_window_uses_the_choice_time_and_keeps_its_floor_after_an_incomplete_run():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        chosen_at = _NOW
        floor = chosen_at - timedelta(days=30)
        service.advance_streams_to_floor(profile, floor, queries=(query,))
        run_at = chosen_at + timedelta(days=3)

        first_plan = service.build_plan(
            profile,
            query,
            "arxiv",
            run_at,
            global_config,
            resume_strategy="last_window",
            catchup_days_override=30,
            catchup_effective_at=chosen_at,
        )

        assert first_plan.slices[0].start_at == floor
        service.mark_attempt(first_plan, first_plan.slices[0], run_at)
        state_after_incomplete_slice = repository.get_state(
            profile.id, query.lens_id, "arxiv", query.query_key
        )
        assert state_after_incomplete_slice.completed_through == floor.isoformat()
        assert state_after_incomplete_slice.overlap_floor == floor.isoformat()

        retry_at = chosen_at + timedelta(days=4)
        retry_plan = service.build_plan(
            profile, query, "arxiv", retry_at, global_config
        )

        assert retry_plan.slices[0].start_at == floor
    finally:
        connection.close()


def test_provider_watermarks_are_independent_and_future_watermarks_never_move_back():
    connection, repository, service, profile, query, global_config = _setup()
    try:
        future = _NOW + timedelta(days=2)
        _seed_watermark(repository, profile, query, "arxiv", future)
        openalex_plan = service.build_plan(profile, query, "openalex", _NOW, global_config)
        arxiv_plan = service.build_plan(profile, query, "arxiv", _NOW, global_config)
        assert openalex_plan.previous_watermark is None
        assert arxiv_plan.previous_watermark == future
        assert arxiv_plan.slices == ()

        service.skip_profile_to_now(profile, _NOW)
        state = repository.get_state(profile.id, query.lens_id, "arxiv", query.query_key)
        assert state.completed_through == future.isoformat()
    finally:
        connection.close()


def test_rejects_naive_clock_and_manual_future_ranges():
    connection, _, service, profile, query, global_config = _setup()
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            service.build_plan(profile, query, "arxiv", datetime(2026, 10, 3), global_config)
        with pytest.raises(ValueError, match="cannot end in the future"):
            service.build_plan(
                profile,
                query,
                "arxiv",
                _NOW,
                global_config,
                manual_range=(_NOW - timedelta(days=1), _NOW + timedelta(days=1)),
            )
    finally:
        connection.close()


def _setup():
    connection = connect_database(":memory:")
    repository = ResearchSearchRepository(connection)
    builder = ResearchQueryBuilder()
    service = ResearchWatermarkService(repository, builder)
    profile = ResearchProfile.model_validate(_profile_data())
    query = builder.build(profile)[0]
    global_config = ResearchGlobalConfig.model_validate(_global_config())
    return connection, repository, service, profile, query, global_config


def _seed_watermark(repository, profile, query, provider, watermark):
    timestamp = watermark.isoformat()
    repository.record_attempt(
        profile.id,
        query.lens_id,
        provider,
        query.query_key,
        query.text,
        timestamp,
    )
    repository.complete_slice(
        profile.id,
        query.lens_id,
        provider,
        query.query_key,
        timestamp,
        timestamp,
    )


def _profile_data():
    return {
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
                "queries": ["EWC methods", "regularization continual learning"],
                "include_terms": ["fisher information"],
                "exclude_terms": [],
            },
            {
                "id": "replay",
                "title": "Replay",
                "enabled": False,
                "priority": "medium",
                "queries": ["experience replay"],
                "include_terms": [],
                "exclude_terms": [],
            },
        ],
        "exclude_terms": [],
        "providers": {"discovery": ["arxiv", "openalex"], "enrichment": []},
        "context": {
            "collections": [],
            "documents": [],
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
        "ai_analysis": {"enabled": True, "provider": "deepseek"},
    }


def _global_config():
    return {
        "schema_version": 1,
        "providers": {"timeout_seconds": 20, "max_retries": 3},
        "runtime": {
            "slice_days": 1,
            "overlap_hours": 48,
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
