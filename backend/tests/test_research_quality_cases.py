"""Synthetic acceptance inputs; no external Provider or paid model is called."""

import pytest
from backend.app.db.connection import connect_database
from backend.app.repositories.research_candidate_repository import ResearchCandidateRepository
from backend.app.services.research_candidate_service import ResearchCandidateService
from backend.tests.test_research_candidate import _analysis, _work, _profile, _persist_work_and_analysis, _clock


CASES = [
    ("early-foundation", 2015, .9, .5, "high", "created"),
    ("contemporary-method", 2017, .88, .4, "high", "created"),
    ("natural-successor", 2018, .85, .55, "medium", "created"),
    ("recent-unrelated", 2026, .2, .9, "high", "filtered"),
    ("old-unrelated", 2005, .25, .9, "medium", "filtered"),
    ("redundant-contribution", 2016, .95, .01, "high", "filtered"),
    ("same-topic-different-method", 2017, .9, .5, "high", "created"),
    ("valuable-stretch", 2026, .9, .7, "low", "created"),
    ("older-prerequisite", 2013, .8, .6, "high", "created"),
    ("library-coverage-gap", 2017, .9, .5, "low", "created"),
    ("alternative-method", 2017, .86, .5, "medium", "created"),
    ("new-but-weak-fit", 2026, .5, .9, "high", "filtered"),
    ("no-increment", 2020, .98, .0, "high", "filtered"),
    ("easy-but-low-value", 2000, .4, .04, "high", "filtered"),
    ("bridges-current-gap", 2014, .7, .2, "medium", "created"),
    ("fit-below-threshold", 2017, .54, .5, "high", "filtered"),
    ("fit-at-threshold", 2017, .55, .5, "medium", "created"),
    ("gain-at-threshold", 2017, .9, .05, "high", "created"),
    ("gain-below-threshold", 2017, .9, .04, "high", "filtered"),
    ("difficult-but-relevant", 2019, .95, .8, "low", "created"),
]


@pytest.mark.parametrize("case,year,relevance,gain,readiness,expected", CASES, ids=[row[0] for row in CASES])
def test_recommendation_quality_inputs(case, year, relevance, gain, readiness, expected):
    connection = connect_database(":memory:")
    try:
        analysis = _analysis(case)
        analysis = analysis.model_copy(update={"analysis": analysis.analysis.model_copy(update={"profile_relevance": relevance, "novelty_to_library": gain, "readiness": readiness})})
        _persist_work_and_analysis(connection, _work(case).model_copy(update={"year": year}), analysis)
        service = ResearchCandidateService(ResearchCandidateRepository(connection), clock=_clock)
        profile = _profile()
        assert service.generate(analysis, profile, profile.lenses[0]).outcome == expected
        assert connection.execute("SELECT COUNT(*) FROM research_works").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM research_work_analyses").fetchone()[0] == 1
    finally:
        connection.close()
