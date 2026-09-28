from pathlib import Path

import pytest

from backend.app.services.source_registry import SourceRegistry
from backend.app.services.source_resolver import SourceResolver
from backend.app.services.taxonomy_registry import TaxonomyRegistry
from backend.app.services.taxonomy_resolver import TaxonomyResolver
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver


def write_term(directory: Path, term_id: str, title: str, aliases=()):
    alias_yaml = "".join("  - {}\n".format(alias) for alias in aliases)
    aliases_yaml = "aliases:\n{}".format(alias_yaml) if aliases else ""
    text = (
        "---\n"
        "schema_version: 1\n"
        "id: {}\n"
        "title: {}\n"
        "type: concept\n"
        "depth: standard\n"
        "{}"
        "---\n"
        "# {}\n"
    ).format(term_id, title, aliases_yaml, title)
    (directory / "{}.md".format(term_id)).write_text(text, encoding="utf-8")


def write_taxonomy(directory: Path, filename: str, entries: str):
    (directory / filename).write_text(
        "schema_version: 1\nentries:\n{}".format(entries), encoding="utf-8"
    )


def write_source(directory: Path, source_id: str, title: str, doi=None):
    doi_value = '  doi: "{}"\n'.format(doi) if doi else "  doi: null\n"
    text = (
        "schema_version: 1\n"
        "id: {}\n"
        "type: paper\n"
        "title: {}\n"
        "authors: []\n"
        "year: 2024\n"
        "identifiers:\n"
        "{}"
        "  arxiv_id: null\n"
        "attachments:\n"
        "  local_pdf: null\n"
    ).format(source_id, title, doi_value)
    (directory / "{}.yaml".format(source_id)).write_text(text, encoding="utf-8")


def test_term_registry_builds_alias_index_and_resolves_id_title_and_alias(tmp_path):
    write_term(tmp_path, "stochastic-gradient-descent", "Stochastic Gradient Descent", ["SGD", "随机梯度下降"])
    registry = TermRegistry.load(tmp_path)
    resolver = TermResolver(registry)

    assert registry.alias_index.resolve("sgd") == ("stochastic-gradient-descent",)
    assert resolver.resolve("stochastic-gradient-descent").matched_by == "exact"
    assert resolver.resolve("Stochastic Gradient Descent").matched_by == "title"
    assert resolver.resolve("stochastic   gradient descent").matched_by == "normalized"
    alias_result = resolver.resolve("SGD")
    assert alias_result.status == "resolved"
    assert alias_result.entity_id == "stochastic-gradient-descent"
    assert alias_result.matched_by == "alias"
    assert resolver.resolve("sgd").matched_by == "normalized"


def test_term_resolver_returns_ambiguous_merge_candidates_without_choosing(tmp_path):
    write_term(tmp_path, "term-a", "Term A", ["shared alias"])
    write_term(tmp_path, "term-b", "Term B", ["shared alias"])
    result = TermResolver(TermRegistry.load(tmp_path)).resolve("shared alias")

    assert result.status == "ambiguous"
    assert result.entity_id is None
    assert [candidate.id for candidate in result.candidates] == ["term-a", "term-b"]


def test_fuzzy_match_only_returns_candidates_and_unresolved_is_empty(tmp_path):
    write_term(tmp_path, "fisher-information", "Fisher Information")
    resolver = TermResolver(TermRegistry.load(tmp_path))

    fuzzy = resolver.resolve("Fisher Informaton")
    assert fuzzy.status == "unresolved"
    assert fuzzy.matched_by == "fuzzy"
    assert fuzzy.candidates[0].id == "fisher-information"
    assert resolver.resolve("unrelated concept").candidates == ()


def test_taxonomy_registry_and_resolver_keep_domain_topic_and_tag_scopes(tmp_path):
    write_taxonomy(tmp_path, "domains.yaml", "  - id: ai\n    title: Artificial Intelligence\n")
    write_taxonomy(tmp_path, "topics.yaml", "  - id: ai\n    title: AI Topic\n")
    write_taxonomy(tmp_path, "tags.yaml", "  - id: reviewed\n    title: Reviewed\n")
    registry = TaxonomyRegistry.load(tmp_path)
    resolver = TaxonomyResolver(registry)

    assert resolver.resolve("ai", "domain").entity_id == "ai"
    assert resolver.resolve("AI Topic", "topic").entity_id == "ai"
    assert resolver.resolve("reviewed", "tag").status == "resolved"
    assert registry.get("domain", "ai").title == "Artificial Intelligence"


def test_taxonomy_registry_requires_all_three_files(tmp_path):
    write_taxonomy(tmp_path, "domains.yaml", "  - id: ai\n    title: AI\n")
    with pytest.raises(FileNotFoundError, match="topics.yaml"):
        TaxonomyRegistry.load(tmp_path)


def test_source_registry_resolves_id_title_and_external_identifier(tmp_path):
    write_source(tmp_path, "ewc-2017", "Overcoming Catastrophic Forgetting", "10.1/example")
    registry = SourceRegistry.load(tmp_path)
    resolver = SourceResolver(registry)

    assert resolver.resolve("ewc-2017").matched_by == "exact"
    assert resolver.resolve("Overcoming Catastrophic Forgetting").matched_by == "title"
    identifier = resolver.resolve("10.1/example")
    assert identifier.status == "resolved"
    assert identifier.entity_id == "ewc-2017"
    assert identifier.matched_by == "identifier"


def test_duplicate_term_ids_and_filename_mismatches_fail_registry_load(tmp_path):
    write_term(tmp_path, "term-a", "First")
    (tmp_path / "term-b.md").write_text(
        "---\nschema_version: 1\nid: term-a\ntitle: Second\ntype: concept\ndepth: standard\n---\n# Second\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match canonical id"):
        TermRegistry.load(tmp_path)
