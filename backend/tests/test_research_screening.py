from datetime import datetime, timezone

import pytest

from backend.app.db.connection import connect_database
from backend.app.domain.research import ResearchProfile
from backend.app.domain.research_runtime import ResearchWorkRecord
from backend.app.domain.source import SourceMetadata
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.research_deduplicator import normalize_title
from backend.app.services.research_query_builder import ResearchQueryBuilder
from backend.app.services.research_screening import ResearchScreeningService
from backend.app.services.research_watermark import ResearchSearchSlice
from backend.app.services.source_registry import SourceRegistry


_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
_RANGE = ResearchSearchSlice(
    datetime(2026, 10, 1, tzinfo=timezone.utc),
    datetime(2026, 10, 4, tzinfo=timezone.utc),
)


def test_screening_applies_include_terms_and_returns_bounded_pre_rank_components():
    connection, repository, service, profile, query = _setup()
    try:
        work = _work(
            title="Continual Learning with Replay",
            abstract="Replay preserves examples across tasks.",
            published_at="2026-10-02",
            authors=("Ada Lovelace",),
            doi="10.1000/replay",
            venue="Journal of Learning",
            url="https://doi.org/10.1000/replay",
        )

        decision = service.screen(work, profile, query, _RANGE, _NOW)

        assert decision.eligible is True
        assert decision.filtered_reasons == ()
        assert decision.metadata_warnings == ()
        assert decision.pre_rank is not None
        assert decision.pre_rank.query_lexical_match == 1.0
        assert decision.pre_rank.lens_priority == 1.0
        assert 0 < decision.pre_rank.recency <= 1
        assert decision.pre_rank.metadata_completeness == 1.0
        assert 0 <= decision.pre_rank.score <= 1
    finally:
        connection.close()


def test_missing_abstract_is_marked_incomplete_but_title_only_work_can_continue():
    connection, _, service, profile, query = _setup()
    try:
        decision = service.screen(
            _work(
                title="Replay for Continual Learning",
                abstract=None,
                published_at="2026-10-02",
                authors=("Ada Lovelace",),
            ),
            profile,
            query,
            _RANGE,
            _NOW,
        )

        assert decision.eligible is True
        assert decision.metadata_warnings == ("missing_abstract",)
        assert decision.pre_rank is not None
        assert decision.pre_rank.metadata_completeness < 1
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("title", "abstract", "published_at", "year", "expected_reason"),
    [
        ("A Continual Learning Study", "No matching method.", "2026-10-02", 2026, "include_term_not_matched"),
        ("Replay for Continual Learning", "Pure domain adaptation.", "2026-10-02", 2026, "excluded_term"),
        ("Replay for Continual Learning", "Replay method.", "2025-01-01", 2025, "outside_search_range"),
        ("Replay for Continual Learning", "Replay method.", None, None, "missing_publication_date"),
    ],
)
def test_screening_filters_irrelevant_terms_and_invalid_recency(
    title, abstract, published_at, year, expected_reason
):
    connection, _, service, profile, query = _setup()
    try:
        decision = service.screen(
            _work(
                title=title,
                abstract=abstract,
                published_at=published_at,
                year=year,
                authors=("Ada Lovelace",),
            ),
            profile,
            query,
            _RANGE,
            _NOW,
        )

        assert decision.eligible is False
        assert expected_reason in decision.filtered_reasons
        assert decision.pre_rank is None
    finally:
        connection.close()


def test_year_only_publication_date_is_screened_as_a_year_interval():
    connection, _, service, profile, query = _setup()
    try:
        decision = service.screen(
            _work(
                title="Replay for Continual Learning",
                abstract="Replay method.",
                published_at="2026",
                year=2026,
                authors=("Ada Lovelace",),
            ),
            profile,
            query,
            _RANGE,
            _NOW,
        )

        assert decision.eligible is True
    finally:
        connection.close()


def test_existing_source_matches_by_strong_identifier_or_conservative_title_rule():
    connection, _, _, profile, query = _setup()
    try:
        doi_source = _source(
            "saved-paper",
            "A Different Display Title",
            2022,
            ("Grace Hopper",),
            doi="https://doi.org/10.1000/saved",
        )
        service = ResearchScreeningService(
            ResearchRepository(connection), SourceRegistry((doi_source,))
        )
        strong_match = service.screen(
            _work(
                title="Replay for Continual Learning",
                abstract="Replay method.",
                published_at="2026-10-02",
                doi="10.1000/SAVED",
            ),
            profile,
            query,
            _RANGE,
            _NOW,
        )
        assert strong_match.filtered_reasons == ("existing_source",)

        title_source = _source(
            "saved-title",
            "Replay for Continual Learning",
            2025,
            ("Ada Lovelace",),
        )
        weak_service = ResearchScreeningService(
            ResearchRepository(connection), SourceRegistry((title_source,))
        )
        weak_match = weak_service.screen(
            _work(
                title="Replay for Continual Learning",
                abstract="Replay method.",
                published_at="2026-10-02",
                year=2026,
                authors=("Ada Lovelace",),
            ),
            profile,
            query,
            _RANGE,
            _NOW,
        )
        assert weak_match.filtered_reasons == ("existing_source",)
    finally:
        connection.close()


def test_existing_candidate_and_matching_analysis_are_filtered():
    connection, repository, service, profile, query = _setup()
    try:
        work = _work(
            work_id="work-1",
            title="Replay for Continual Learning",
            abstract="Replay method.",
            published_at="2026-10-02",
            authors=("Ada Lovelace",),
        )
        with repository.write_transaction():
            repository.insert_work(work)
            connection.execute(
                """INSERT INTO research_candidates (
                       id, work_id, profile_id, status, analysis_id, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("candidate-1", work.id, profile.id, "dismissed", "analysis-1", "now", "now"),
            )
            connection.execute(
                """INSERT INTO research_work_analyses (
                       id, work_id, profile_id, input_hash, outcome, analysis_json,
                       provider, model, prompt_version, analysis_version,
                       context_entity_ids_json, analyzed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "analysis-1",
                    work.id,
                    profile.id,
                    "input-hash-a",
                    "filtered",
                    "{}",
                    "deepseek",
                    "model",
                    "prompt-v1",
                    1,
                    "[]",
                    "now",
                ),
            )

        decision = service.screen(
            work, profile, query, _RANGE, _NOW, analysis_input_hash="input-hash-a"
        )
        different_input = service.screen(
            work, profile, query, _RANGE, _NOW, analysis_input_hash="input-hash-b"
        )

        assert decision.filtered_reasons == ("existing_candidate", "existing_analysis")
        assert different_input.filtered_reasons == ("existing_candidate",)
        assert repository.has_analysis_for_profile(work.id, profile.id) is True
    finally:
        connection.close()


def test_pre_rank_rewards_recency_but_does_not_read_citation_counts():
    connection, _, service, profile, query = _setup()
    try:
        fresh = service.screen(
            _work(
                title="Replay for Continual Learning",
                abstract="Replay method.",
                published_at="2026-10-02",
                authors=("Ada Lovelace",),
            ),
            profile,
            query,
            _RANGE,
            _NOW,
        )
        older = service.screen(
            _work(
                title="Replay for Continual Learning",
                abstract="Replay method.",
                published_at="2026-10-01",
                authors=("Ada Lovelace",),
            ),
            profile,
            query,
            _RANGE,
            _NOW,
        )

        assert fresh.pre_rank is not None and older.pre_rank is not None
        assert fresh.pre_rank.recency > older.pre_rank.recency
        assert set(fresh.pre_rank.__dataclass_fields__) == {
            "score",
            "query_lexical_match",
            "lens_priority",
            "recency",
            "metadata_completeness",
        }
    finally:
        connection.close()


def _setup():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    profile = ResearchProfile.model_validate(_profile_data())
    query = ResearchQueryBuilder().build(profile)[0]
    service = ResearchScreeningService(repository, SourceRegistry(()))
    return connection, repository, service, profile, query


def _work(
    work_id="work-screen",
    title="Replay for Continual Learning",
    abstract="Replay method.",
    published_at="2026-10-02",
    year=2026,
    authors=("Ada Lovelace",),
    doi="10.1000/screen",
    arxiv_id=None,
    openalex_id=None,
    semantic_scholar_id=None,
    venue="Journal of Learning",
    url="https://example.test/paper",
):
    return ResearchWorkRecord(
        id=work_id,
        canonical_key="doi:{}".format(doi) if doi else "title:{}".format(normalize_title(title)),
        title=title,
        normalized_title=normalize_title(title),
        abstract=abstract,
        authors=authors,
        year=year,
        published_at=published_at,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        openalex_id=openalex_id,
        semantic_scholar_id=semantic_scholar_id,
        url=url,
        created_at="2026-10-03T12:00:00+00:00",
        updated_at="2026-10-03T12:00:00+00:00",
    )


def _source(source_id, title, year, authors, doi=None):
    return SourceMetadata.model_validate(
        {
            "schema_version": 1,
            "id": source_id,
            "type": "paper",
            "title": title,
            "authors": list(authors),
            "year": year,
            "identifiers": {"doi": doi},
        }
    )


def _profile_data():
    return {
        "schema_version": 1,
        "id": "continual-learning",
        "title": "Continual Learning",
        "enabled": True,
        "lenses": [
            {
                "id": "replay",
                "title": "Replay",
                "enabled": True,
                "priority": "high",
                "queries": ["continual learning replay"],
                "include_terms": ["replay", "rehearsal"],
                "exclude_terms": ["survey only"],
            }
        ],
        "exclude_terms": ["pure domain adaptation"],
        "providers": {"discovery": ["arxiv"], "enrichment": []},
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
        },
        "inbox": {"max_new_candidates": 20},
        "ai_analysis": {"enabled": True, "provider": "deepseek"},
    }
