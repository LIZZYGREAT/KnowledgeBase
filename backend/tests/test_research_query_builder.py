import hashlib

import pytest

from backend.app.domain.research import ResearchProfile
from backend.app.services.research_query_builder import (
    ResearchQueryBuilder,
    normalize_query,
)


def test_builds_one_stable_query_per_enabled_lens_query():
    profile = _profile()
    builder = ResearchQueryBuilder()

    queries = builder.build(profile)

    assert [query.text for query in queries] == [
        "Elastic Weight Consolidation",
        "parameter importance continual learning",
    ]
    assert len({query.lens_id for query in queries}) == 1
    assert all(query.lens_id == "regularization" for query in queries)
    assert queries[0].normalized_text == "elastic weight consolidation"
    assert queries[0].query_key == hashlib.sha256(
        "continual-learning\0regularization\0elastic weight consolidation".encode()
    ).hexdigest()
    assert queries[0].include_terms == ("fisher information", "regularization")
    assert queries[0].profile_exclude_terms == ("pure domain adaptation",)
    assert normalize_query(" ＥＷＣ\tMethods ") == "ewc methods"


def test_run_overrides_change_enabled_lenses_without_changing_profile():
    profile = _profile()
    builder = ResearchQueryBuilder()

    overridden = builder.build(
        profile,
        lens_overrides={"regularization": False, "replay": True},
    )

    assert [query.lens_id for query in overridden] == ["replay"]
    assert profile.lenses[0].enabled is True
    assert profile.lenses[1].enabled is False
    assert builder.build(profile)[0].lens_id == "regularization"


def test_rejects_unknown_or_non_boolean_lens_overrides():
    builder = ResearchQueryBuilder()
    profile = _profile()

    with pytest.raises(ValueError, match="Unknown Research Lens"):
        builder.build(profile, lens_overrides={"missing": True})
    with pytest.raises(ValueError, match="boolean values"):
        builder.build(profile, lens_overrides={"regularization": 1})


def test_rejects_queries_that_collide_after_unicode_normalization():
    profile_data = _profile_data()
    profile_data["lenses"][0]["queries"] = ["ＡＩ methods", "AI methods"]
    profile = ResearchProfile.model_validate(profile_data)

    with pytest.raises(ValueError, match="repeats a query after normalization"):
        ResearchQueryBuilder().build(profile)


def _profile():
    return ResearchProfile.model_validate(_profile_data())


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
                "queries": [
                    "Elastic Weight Consolidation",
                    "parameter importance continual learning",
                ],
                "include_terms": ["fisher information", "regularization"],
                "exclude_terms": [],
            },
            {
                "id": "replay",
                "title": "Replay",
                "enabled": False,
                "priority": "medium",
                "queries": ["experience replay"],
                "include_terms": ["replay"],
                "exclude_terms": [],
            },
        ],
        "exclude_terms": ["pure domain adaptation"],
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
        },
        "inbox": {"max_new_candidates": 20},
        "ai_analysis": {"enabled": True, "provider": "deepseek"},
    }
