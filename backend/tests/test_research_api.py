import asyncio
from types import SimpleNamespace

import pytest

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.app.domain.ai import ResearchCandidateAnalysisOutput
from backend.app.domain.research import ResearchLens
from backend.app.domain.runtime import Draft
from backend.app.domain.research_runtime import ResearchWorkAnalysisRecord
from backend.app.services.research_providers.base import ProviderWork
from backend.app.api.research import router
from backend.app.api.publishing import router as publishing_router
from backend.app.services.publisher import PublishedResult
from backend.tests.test_research_runs import (
    _NOW,
    _profile,
    FakeProvider,
    _service,
)


def test_research_profile_controls_and_manual_search_api_are_runtime_only(tmp_path):
    connection = _connection()
    profile = _profile()
    replay_lens = ResearchLens.model_validate(
        {
            "id": "replay",
            "title": "Replay",
            "enabled": False,
            "priority": "medium",
            "queries": ["experience replay"],
            "include_terms": ["replay"],
            "exclude_terms": [],
        }
    )
    profile = profile.model_copy(update={"lenses": [*profile.lenses, replay_lens]})
    service, _, _, _ = _service(tmp_path, connection, FakeProvider([]), profile=profile)
    app = _app(service)

    async def exercise_routes():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            profiles = await client.get("/api/research/profiles")
            assert profiles.status_code == 200
            assert profiles.json()[0]["id"] == "continual-learning"
            assert (await client.get("/api/research/profiles/missing")).status_code == 404
            assert (
                await client.post(
                    "/api/research/profiles/continual-learning/pause",
                    json={"days": 3, "until": "2026-10-08T00:00:00Z"},
                )
            ).status_code == 422

            paused = await client.post(
                "/api/research/profiles/continual-learning/pause", json={"days": 3}
            )
            assert paused.status_code == 200
            assert paused.json()["runtime_state"]["paused_until"] == (
                "2026-10-06T12:00:00+00:00"
            )
            resumed = await client.post(
                "/api/research/profiles/continual-learning/resume",
                json={"strategy": "from_now"},
            )
            assert resumed.status_code == 200
            assert resumed.json()["watermark_skipped"] is True
            assert service.control_event_repository.latest_resume("continual-learning")[
                "payload"
            ]["strategy"] == "from_now"

            queued = await client.post(
                "/api/research/profiles/continual-learning/runs",
                json={
                    "lenses": ["regularization"],
                    "breadth": "explore",
                    "date_range": {"mode": "last_30_days"},
                    "additional_queries": ["dynamic fisher continual learning"],
                },
            )
            assert queued.status_code == 202, queued.json()
            request = service.run_request_repository.get(queued.json()["request_id"])
            assert request is not None and request.status == "pending"
            assert request.override["breadth"] == "explore"
            assert request.override["additional_queries"] == [
                "dynamic fisher continual learning"
            ]
            assert request.override["additional_query_lens"] == "regularization"

            incremental = await client.post(
                "/api/research/profiles/continual-learning/runs",
                json={
                    "lenses": ["regularization", "replay"],
                    "date_range": {"mode": "incremental"},
                    "additional_queries": ["replay distillation"],
                    "additional_query_lens": "replay",
                },
            )
            assert incremental.status_code == 202, incremental.json()
            incremental_request = service.run_request_repository.get(
                incremental.json()["request_id"]
            )
            assert incremental_request is not None
            assert incremental_request.override["manual_incremental"] is True
            assert incremental_request.override["additional_query_lens"] == "replay"
            assert "manual_range" not in incremental_request.override

            profile = service.profile_registry.get("continual-learning")
            with pytest.raises(ValueError, match="explicit Lens"):
                service.queue_manual_run(
                    profile.id,
                    {
                        "lens_overrides": {
                            lens.id: lens.id in {"regularization", "replay"}
                            for lens in profile.lenses
                        },
                        "additional_queries": ["ambiguous additional query"],
                    },
                )
            assert (await client.get("/api/research/runs")).json()["count"] == 0
            assert (await client.get("/api/research/candidates")).json()["count"] == 0
            assert (await client.get("/api/research/runs/missing")).status_code == 404

    asyncio.run(exercise_routes())
    connection.close()


def test_profile_reactivation_review_and_publish_require_a_selected_strategy(tmp_path):
    connection = _connection()
    service, _, _, _ = _service(tmp_path, connection, FakeProvider([]))
    profile = service.profile_registry.get("continual-learning")
    draft = Draft(
        id="profile-draft",
        entity_type="research_profile",
        entity_id=profile.id,
        base_git_revision="revision",
        base_content_hash="hash",
        content="profile draft",
        revision=1,
        created_at=_NOW.isoformat(),
        updated_at=_NOW.isoformat(),
    )
    publish_calls = []

    def publish(*args, **kwargs):
        publish_calls.append((args, kwargs))
        return PublishedResult(
            draft_id=draft.id,
            entity_type="research_profile",
            entity_id=profile.id,
            path="config/research/profiles/continual-learning.yaml",
            commit_revision="commit",
        )

    publisher = SimpleNamespace(
        preflight=lambda draft_id: SimpleNamespace(valid=True),
        publish=publish,
    )
    service.parse_profile_candidate = lambda profile_id, content: profile
    review = {
        "required": True,
        "triggers": ["profile_enabled"],
        "max_catchup_days": profile.search.max_catchup_days,
        "strategies": ["last_window", "all", "from_now"],
    }
    service.reactivation_review = lambda candidate: review
    applied = []
    service.apply_reactivation_strategy = lambda profile_id, strategy, **kwargs: applied.append(
        (profile_id, strategy, kwargs)
    )

    application = FastAPI()
    application.include_router(router)
    application.include_router(publishing_router)
    application.state.research_service = service
    application.state.draft_service = SimpleNamespace(get=lambda draft_id: draft)
    application.state.publisher = publisher

    async def exercise_routes():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            reviewed = await client.post(
                "/api/research/profiles/{}/reactivation-review".format(profile.id),
                json={"draft_id": draft.id},
            )
            assert reviewed.status_code == 200
            assert reviewed.json() == review

            blocked = await client.post(
                "/api/publish",
                json={"draft_id": draft.id, "expected_revision": draft.revision},
            )
            assert blocked.status_code == 409
            assert publish_calls == []
            assert applied == []

            published = await client.post(
                "/api/publish",
                json={
                    "draft_id": draft.id,
                    "expected_revision": draft.revision,
                    "reactivation_strategy": "last_window",
                },
            )
            assert published.status_code == 200, published.json()
            assert published.json()["commit_revision"] == "commit"
            assert len(publish_calls) == 1
            assert applied[0][0:2] == (profile.id, "last_window")
            assert applied[0][2]["catchup_days"] == profile.search.max_catchup_days

    asyncio.run(exercise_routes())
    connection.close()


def test_research_candidate_reads_and_actions_are_human_controlled(tmp_path):
    connection = _connection()
    service, _, _, _ = _service(tmp_path, connection, FakeProvider([]))
    profile = service.profile_registry.get("continual-learning")
    query = service.query_builder.build(profile)[0]
    provider_work = ProviderWork(
        provider="arxiv",
        provider_record_id="2501.01234",
        title="A Research API Candidate",
        abstract="A concrete abstract for the research candidate.",
        authors=("Example Author",),
        year=2026,
        arxiv_id="2501.01234",
    )
    ingested = service.deduplicator.record_discovery(
        profile.id,
        query.lens_id,
        query.query_key,
        query.text,
        provider_work,
        discovered_at=_NOW,
    )
    output = ResearchCandidateAnalysisOutput.model_validate(
        {
            "relevant": True,
            "profile_relevance": 0.9,
            "knowledge_relevance": 0.8,
            "novelty_to_library": 0.7,
            "matched_lenses": [query.lens_id],
            "matched_topics": ["continual learning"],
            "summary": "A concise analysis summary.",
            "why_relevant": "It matches the Profile's Research Lens.",
            "reading_reason": "It may provide a useful method comparison.",
            "existing_relations": [],
        }
    )
    analysis = ResearchWorkAnalysisRecord(
        id="api-analysis",
        work_id=ingested.work.id,
        profile_id=profile.id,
        input_hash="api-analysis-hash",
        outcome="surface",
        analysis=output,
        provider="mock",
        model="mock",
        prompt_version="research-candidate-analysis-v1",
        analysis_version=1,
        context_entity_ids=(),
        analyzed_at=_NOW.isoformat(),
    )
    analysis, _ = service.work_repository.add_analysis_if_missing(analysis)
    generated = service.candidate_service.generate(analysis, profile, profile.lenses[0])
    other_profile_discovery = service.deduplicator.record_discovery(
        "another-profile",
        "another-lens",
        "another-query",
        "a query from another Profile",
        ProviderWork(
            provider="openalex",
            provider_record_id="W987654321",
            title=provider_work.title,
            abstract=provider_work.abstract,
            authors=provider_work.authors,
            year=provider_work.year,
            arxiv_id=provider_work.arxiv_id,
            openalex_id="W987654321",
        ),
        discovered_at=_NOW,
    )
    assert other_profile_discovery.work.id == ingested.work.id
    app = _app(service)

    async def exercise_routes():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            listing = await client.get(
                "/api/research/candidates",
                params={"profile_id": profile.id, "status": "new"},
            )
            assert listing.status_code == 200, listing.json()
            assert listing.json()["count"] == 1
            assert listing.json()["candidates"][0]["work"]["id"] == ingested.work.id

            details = await client.get(
                "/api/research/candidates/{}".format(generated.candidate.id)
            )
            assert details.status_code == 200, details.json()
            assert details.json()["candidate"]["first_viewed_at"] == _NOW.isoformat()
            assert {
                discovery["profile_id"] for discovery in details.json()["discoveries"]
            } == {profile.id}
            assert len(details.json()["discoveries"]) == 1

            shortlist = await client.post(
                "/api/research/candidates/{}/shortlist".format(generated.candidate.id),
                json={"note": "Read after the current review batch."},
            )
            assert shortlist.status_code == 200
            assert shortlist.json()["status"] == "shortlisted"
            updated_note = await client.patch(
                "/api/research/candidates/{}/note".format(generated.candidate.id),
                json={"note": "Compare with the recent replay approach."},
            )
            assert updated_note.status_code == 200, updated_note.json()
            assert updated_note.json()["user_note"] == (
                "Compare with the recent replay approach."
            )
            cleared_note = await client.patch(
                "/api/research/candidates/{}/note".format(generated.candidate.id),
                json={"note": "   "},
            )
            assert cleared_note.status_code == 200
            assert cleared_note.json()["user_note"] is None
            dismiss = await client.post(
                "/api/research/candidates/{}/dismiss".format(generated.candidate.id),
                json={"reason": "too_redundant", "note": "Already covered."},
            )
            assert dismiss.status_code == 200
            assert dismiss.json()["dismiss_reason"] == "too_similar"
            assert dismiss.json()["status"] == "dismissed"

    asyncio.run(exercise_routes())
    connection.close()


def _connection():
    from backend.app.db.connection import connect_database

    return connect_database(":memory:")


def _app(service):
    application = FastAPI()
    application.include_router(router)
    application.state.research_service = service
    return application
