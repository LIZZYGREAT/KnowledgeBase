import hashlib
from pathlib import Path

import pytest
import yaml

from backend.app.services.research_profile_registry import ResearchProfileRegistry
from tools.research import main as research_main


def test_repository_research_configuration_loads_profiles_without_network():
    root = Path(__file__).resolve().parents[2]

    registry = ResearchProfileRegistry.load(root)

    profile = registry.get("continual-learning")
    assert profile is not None
    assert [lens.id for lens in profile.lenses] == [
        "regularization",
        "replay",
        "class-incremental",
    ]
    assert registry.path_for(profile.id).as_posix().endswith(
        "config/research/profiles/continual-learning.yaml"
    )
    assert registry.content_hash(profile.id) == hashlib.sha256(
        registry.path_for(profile.id).read_bytes()
    ).hexdigest()
    assert research_main(["check", "--root", str(root)]) == 0


def test_profile_registry_rejects_duplicate_lens_ids(tmp_path):
    root = _valid_repository(tmp_path)
    profile = _profile()
    profile["lenses"].append(dict(profile["lenses"][0]))
    _write_profile(root, profile)

    with pytest.raises(ValueError, match="lens IDs must be unique"):
        ResearchProfileRegistry.load(root)


def test_profile_registry_rejects_duplicate_profile_ids(tmp_path):
    root = _valid_repository(tmp_path)
    profile = _profile()
    _write_profile(root, profile, "first.yaml")
    _write_profile(root, profile, "second.yaml")

    with pytest.raises(ValueError, match="Duplicate Research Profile id"):
        ResearchProfileRegistry.load(root)


def test_profile_registry_rejects_invalid_provider_and_query(tmp_path):
    root = _valid_repository(tmp_path)
    profile = _profile()
    profile["providers"]["discovery"] = ["semantic_scholar"]
    profile["lenses"][0]["queries"] = [" "]
    _write_profile(root, profile)

    with pytest.raises(ValueError, match="providers.discovery|queries"):
        ResearchProfileRegistry.load(root)


def test_profile_registry_rejects_unknown_collection_and_pinned_document(tmp_path):
    root = _valid_repository(tmp_path)
    profile = _profile()
    profile["context"]["collections"] = ["missing-collection"]
    profile["context"]["documents"] = ["missing-document"]
    _write_profile(root, profile)

    with pytest.raises(ValueError) as error:
        ResearchProfileRegistry.load(root)
    assert "unknown Collection id(s): missing-collection" in str(error.value)
    assert "unknown pinned Document id(s): missing-document" in str(error.value)


def test_research_check_rejects_invalid_global_ranking_config(tmp_path, capsys):
    root = _valid_repository(tmp_path)
    config_path = root / "config" / "research" / "research.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["ranking"]["strict"]["novelty_weight"] = 0.2
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    assert research_main(["check", "--root", str(root)]) == 1
    assert "weights must sum to 1.0" in capsys.readouterr().out


def test_profile_registry_rejects_symlinked_profiles(tmp_path):
    root = _valid_repository(tmp_path)
    profiles = root / "config" / "research" / "profiles"
    target = tmp_path / "outside.yaml"
    target.write_text(yaml.safe_dump(_profile()), encoding="utf-8")
    linked_profile = profiles / "research.yaml"
    try:
        linked_profile.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation is unavailable in this environment")

    with pytest.raises(ValueError, match="does not follow symlinks"):
        ResearchProfileRegistry.load(root)


def _valid_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    profile_dir = root / "config" / "research" / "profiles"
    profile_dir.mkdir(parents=True)
    (root / "knowledge" / "documents" / "learning").mkdir(parents=True)
    (root / "knowledge" / "collections").mkdir(parents=True)
    (root / "knowledge" / "documents" / "learning" / "doc-one.md").write_text(
        "---\nschema_version: 1\nid: doc-one\ntitle: Document One\n"
        "type: learning-note\n---\n# Document One\n",
        encoding="utf-8",
    )
    (root / "knowledge" / "collections" / "collection-one.yaml").write_text(
        "schema_version: 1\nid: collection-one\ntitle: Collection One\n"
        "status: active\nposition: 0\nnodes: []\n",
        encoding="utf-8",
    )
    (root / "config" / "research" / "research.yaml").write_text(
        yaml.safe_dump(_global_config(), sort_keys=False), encoding="utf-8"
    )
    _write_profile(root, _profile())
    return root


def _global_config() -> dict:
    return {
        "schema_version": 1,
        "providers": {"timeout_seconds": 20, "max_retries": 3},
        "runtime": {"slice_days": 1, "overlap_hours": 48},
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


def _profile() -> dict:
    return {
        "schema_version": 1,
        "id": "research-profile",
        "title": "Research Profile",
        "description": "A profile used by focused tests.",
        "enabled": True,
        "lenses": [
            {
                "id": "core",
                "title": "Core direction",
                "enabled": True,
                "priority": "medium",
                "queries": ["continual learning"],
                "include_terms": [],
                "exclude_terms": [],
            }
        ],
        "exclude_terms": [],
        "providers": {"discovery": ["arxiv"], "enrichment": ["crossref"]},
        "context": {
            "collections": ["collection-one"],
            "documents": ["doc-one"],
            "dynamic_retrieval": {"enabled": True, "scope": "entire-library"},
        },
        "schedule": {"mode": "manual"},
        "search": {
            "breadth": "balanced",
            "initial_lookback_days": 30,
            "max_catchup_days": 30,
            "max_candidates_per_run": 10,
        },
        "inbox": {"max_new_candidates": 20},
        "ai_analysis": {"enabled": True, "provider": "deepseek"},
    }


def _write_profile(root: Path, profile: dict, filename: str = "research-profile.yaml") -> None:
    path = root / "config" / "research" / "profiles" / filename
    path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
