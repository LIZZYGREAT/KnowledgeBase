from datetime import datetime, timezone

import pytest

from backend.app.db.connection import connect_database
from backend.app.domain.ai import ResearchCandidateAnalysisOutput
from backend.app.domain.research import ResearchProfile
from backend.app.domain.research_runtime import (
    ResearchWorkAnalysisRecord,
    ResearchWorkRecord,
)
from backend.app.repositories.research_candidate_repository import (
    ResearchCandidateRepository,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.research_candidate_service import ResearchCandidateService


def test_surface_analysis_creates_one_candidate_per_work_and_profile():
    connection = connect_database(":memory:")
    work = _work("work-1")
    analysis = _analysis("work-1", relevant=True)
    _persist_work_and_analysis(connection, work, analysis)
    repository = ResearchCandidateRepository(connection)
    service = ResearchCandidateService(repository, clock=_clock)
    profile = _profile(max_new_candidates=3)

    first = service.generate(analysis, profile, profile.lenses[0])
    repeated = service.generate(analysis, profile, profile.lenses[0])

    assert first.outcome == "created"
    assert first.candidate is not None
    assert first.candidate.status == "new"
    assert first.candidate.analysis_id == analysis.id
    assert first.candidate.primary_lens_id == "regularization"
    assert repeated.outcome == "existing"
    assert repeated.candidate.id == first.candidate.id
    assert repository.count_new(profile.id) == 1
    assert connection.execute("SELECT COUNT(*) FROM research_candidates").fetchone()[0] == 1
    connection.close()


def test_filtered_analysis_never_creates_a_candidate():
    connection = connect_database(":memory:")
    work = _work("work-filtered")
    analysis = _analysis("work-filtered", relevant=False)
    _persist_work_and_analysis(connection, work, analysis)
    repository = ResearchCandidateRepository(connection)
    service = ResearchCandidateService(repository, clock=_clock)
    profile = _profile()

    result = service.generate(analysis, profile, profile.lenses[0])

    assert result.outcome == "filtered"
    assert result.candidate is None
    assert repository.count_new(profile.id) == 0
    assert connection.execute("SELECT COUNT(*) FROM research_candidates").fetchone()[0] == 0
    connection.close()


def test_shortlist_and_dismiss_manage_notes_views_and_inbox_capacity():
    connection = connect_database(":memory:")
    work_one = _work("work-one")
    analysis_one = _analysis("work-one")
    work_two = _work("work-two")
    analysis_two = _analysis("work-two")
    _persist_work_and_analysis(connection, work_one, analysis_one)
    _persist_work_and_analysis(connection, work_two, analysis_two)
    repository = ResearchCandidateRepository(connection)
    times = iter(
        [
            datetime(2026, 10, 3, hour, tzinfo=timezone.utc)
            for hour in range(8)
        ]
    )
    service = ResearchCandidateService(repository, clock=lambda: next(times))
    profile = _profile(max_new_candidates=1)

    first = service.generate(analysis_one, profile, profile.lenses[0]).candidate
    assert first is not None
    assert service.remaining_capacity(profile) == 0
    full = service.generate(analysis_two, profile, profile.lenses[0])
    assert full.outcome == "inbox_full"

    shortlisted = service.shortlist(first.id, "  Read after the review.  ")
    assert shortlisted.status == "shortlisted"
    assert shortlisted.user_note == "Read after the review."
    assert shortlisted.decided_at is None
    assert service.remaining_capacity(profile) == 1

    second = service.generate(analysis_two, profile, profile.lenses[0])
    assert second.outcome == "created"
    assert service.remaining_capacity(profile) == 0

    noted = service.update_user_note(first.id, "Update the comparison section.")
    viewed_once = service.mark_viewed(noted.id)
    viewed_twice = service.mark_viewed(noted.id)
    assert viewed_once.first_viewed_at == "2026-10-03T05:00:00+00:00"
    assert viewed_twice.first_viewed_at == viewed_once.first_viewed_at
    assert viewed_twice.last_viewed_at == "2026-10-03T06:00:00+00:00"

    dismissed = service.dismiss(first.id, "too_redundant")
    assert dismissed.status == "dismissed"
    assert dismissed.dismiss_reason == "too_redundant"
    assert dismissed.user_note == "Update the comparison section."
    assert dismissed.decided_at == "2026-10-03T07:00:00+00:00"
    repeated = service.generate(analysis_one, profile, profile.lenses[0])
    assert repeated.outcome == "existing"
    assert repeated.candidate.status == "dismissed"
    connection.close()


def test_candidate_transitions_validate_inputs_and_keep_terminal_states():
    connection = connect_database(":memory:")
    work = _work("work-1")
    analysis = _analysis("work-1")
    _persist_work_and_analysis(connection, work, analysis)
    service = ResearchCandidateService(
        ResearchCandidateRepository(connection), clock=_clock
    )
    profile = _profile()
    candidate = service.generate(analysis, profile, profile.lenses[0]).candidate
    assert candidate is not None

    with pytest.raises(ValueError, match="cannot exceed 4000"):
        service.shortlist(candidate.id, "x" * 4001)
    with pytest.raises(ValueError, match="dismiss reason"):
        service.dismiss(candidate.id, "made_up")

    dismissed = service.dismiss(candidate.id, "already_known")
    with pytest.raises(ValueError, match="Cannot move Research Candidate"):
        service.shortlist(dismissed.id)
    connection.close()


def _persist_work_and_analysis(connection, work, analysis):
    repository = ResearchRepository(connection)
    repository.insert_work(work)
    repository.add_analysis_if_missing(analysis)


def _work(work_id):
    return ResearchWorkRecord(
        id=work_id,
        canonical_key="doi:10.1000/{}".format(work_id),
        title="Fisher Information for Continual Learning",
        normalized_title="fisher information for continual learning",
        abstract="Parameter importance can reduce forgetting.",
        authors=("Ada Lovelace",),
        year=2026,
        published_at="2026-10-01",
        doi="10.1000/{}".format(work_id),
        created_at="2026-10-03T00:00:00+00:00",
        updated_at="2026-10-03T00:00:00+00:00",
    )


def _analysis(work_id, relevant=True):
    output = ResearchCandidateAnalysisOutput.model_validate(
        {
            "relevant": relevant,
            "profile_relevance": 0.9,
            "knowledge_relevance": 0.8,
            "novelty_to_library": 0.7,
            "matched_lenses": ["regularization"],
            "matched_topics": ["parameter importance"],
            "summary": "A summary of the discovered work.",
            "why_relevant": "It matches the selected Research Lens.",
            "reading_reason": "It may add useful detail.",
            "existing_relations": [],
            "suggested_collection": "research-core",
            "suggested_section": "Regularization",
        }
    )
    return ResearchWorkAnalysisRecord(
        id="analysis-{}".format(work_id),
        work_id=work_id,
        profile_id="continual-learning",
        input_hash="hash-{}".format(work_id),
        outcome="surface" if relevant else "filtered",
        analysis=output,
        provider="mock",
        model="mock",
        prompt_version="research-candidate-analysis-v1",
        analysis_version=1,
        context_entity_ids=("document:ewc",),
        analyzed_at="2026-10-03T00:00:00+00:00",
    )


def _profile(max_new_candidates=20):
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
            "inbox": {"max_new_candidates": max_new_candidates},
            "ai_analysis": {"enabled": True, "provider": "deepseek"},
        }
    )


def _clock():
    return datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
