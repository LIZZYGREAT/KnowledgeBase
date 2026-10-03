from pathlib import Path

import pytest

from backend.app.db.connection import connect_database
from backend.app.domain.research import ResearchProfile
from backend.app.domain.research_runtime import ResearchWorkRecord
from backend.app.services.collection_service import CollectionService
from backend.app.services.context_export_service import ContextExportService
from backend.app.services.indexer import Indexer
from backend.app.services.knowledge_read_service import KnowledgeReadService
from backend.app.services.research_context_builder import ResearchContextBuilder


def test_builds_pinned_collection_context_and_uses_bounded_evidence_snippets(tmp_path):
    root = _repository(tmp_path / "repo")
    _write_document(
        root,
        "ewc",
        "EWC Consolidation",
        "Fisher information protects earlier task parameters [@source-alpha, Sec. 2].\n\n"
        + ("Unrelated background " * 80)
        + "unrelated-secrets-never-shared",
        review_status="approved",
        sources=("source-alpha",),
        topics=("continual-learning",),
        domains=("artificial-intelligence",),
    )
    _write_document(
        root,
        "replay-note",
        "Replay Memory",
        "Replay memory preserves examples between tasks.",
        review_status="unreviewed",
    )
    _write_term(root)
    _write_source(root)
    _write_collection(root)
    connection, builder = _context_builder(root, max_context_entities=8)
    try:
        pack = builder.build(
            _work(),
            _profile(dynamic=True),
            _profile(dynamic=True).lenses[0],
            keywords=("fisher information", "replay memory"),
        )

        cards = {(card.entity_type, card.entity_id): card for card in pack.cards}
        assert pack.budget == 8
        assert len(pack.cards) <= pack.budget
        assert pack.omitted_count == 0
        assert cards[("collection", "research-core")].pinned is True
        assert cards[("document", "ewc")].pinned is True
        assert cards[("document", "ewc")].review_status == "approved"
        assert cards[("document", "ewc")].topics == ("continual-learning",)
        assert cards[("document", "ewc")].domains == ("artificial-intelligence",)
        assert cards[("term", "fisher-information")].pinned is True
        assert cards[("source", "source-alpha")].review_status == "verified"

        evidence = cards[("document", "ewc")].relevant_sections
        assert any(section.heading.startswith("Evidence") for section in evidence)
        assert all(len(section.excerpt) <= 450 for card in pack.cards for section in card.relevant_sections)
        serialized = pack.model_dump_json()
        assert "unrelated-secrets-never-shared" not in serialized
        assert "canonical_content" not in serialized
        assert "Unrelated background" not in serialized
    finally:
        connection.close()


def test_dynamic_retrieval_adds_relevant_cards_and_merges_with_pinned_context(tmp_path):
    root = _repository(tmp_path / "repo")
    _write_document(
        root,
        "ewc",
        "EWC Consolidation",
        "Fisher information protects earlier task parameters.",
        review_status="approved",
        topics=("continual-learning",),
    )
    _write_document(
        root,
        "dynamic-replay",
        "Replay Memory for Continual Learning",
        "Replay memory stores examples for future tasks.",
        review_status="unreviewed",
    )
    _write_term(root)
    _write_source(root)
    _write_collection(root)
    connection, builder = _context_builder(root, max_context_entities=8)
    try:
        profile = _profile(dynamic=True)
        pack = builder.build(
            _work(),
            profile,
            profile.lenses[0],
            keywords=("fisher information", "replay memory"),
        )

        cards = {(card.entity_type, card.entity_id): card for card in pack.cards}
        assert cards[("document", "ewc")].pinned is True
        assert cards[("document", "ewc")].retrieval_score > 0
        assert ("document", "dynamic-replay") in cards
        assert ("term", "fisher-information") in cards
        assert all(card.retrieval_score >= 0 for card in pack.cards)
    finally:
        connection.close()


def test_dynamic_retrieval_can_be_disabled_and_entity_budget_is_enforced(tmp_path):
    root = _repository(tmp_path / "repo")
    _write_document(root, "ewc", "EWC Consolidation", "Fisher information prevents forgetting.")
    _write_document(root, "dynamic-one", "Fisher Information", "Fisher information details.")
    _write_term(root)
    _write_source(root)
    _write_collection(root)
    connection, builder = _context_builder(root, max_context_entities=8)
    try:
        static_profile = _profile(dynamic=False)
        static_pack = builder.build(_work(), static_profile, static_profile.lenses[0])
        assert all(card.pinned for card in static_pack.cards)
        assert len(static_pack.cards) == 4

        dynamic_profile = _profile(dynamic=True)
        bounded_connection, bounded_builder = _context_builder(root, max_context_entities=2)
        bounded = bounded_builder.build(
            _work(), dynamic_profile, dynamic_profile.lenses[0]
        )
        assert len(bounded.cards) == 2
        assert bounded.omitted_count >= 2
        bounded_connection.close()
    finally:
        connection.close()


def test_context_builder_rejects_lens_from_another_profile_and_bad_budget(tmp_path):
    root = _repository(tmp_path / "repo")
    _write_document(root, "ewc", "EWC", "Fisher information.")
    _write_term(root)
    _write_source(root)
    _write_collection(root)
    connection, builder = _context_builder(root, max_context_entities=4)
    try:
        other_lens = _profile().lenses[0].model_copy(update={"title": "Other lens"})
        with pytest.raises(ValueError, match="does not belong"):
            builder.build(_work(), _profile(), other_lens)
    finally:
        connection.close()

    with pytest.raises(ValueError, match="positive integer"):
        _context_builder(root, max_context_entities=0)


def _context_builder(root: Path, max_context_entities: int):
    connection = connect_database(":memory:")
    Indexer(root, connection).full_rebuild()
    knowledge = KnowledgeReadService(root, connection)
    collections = CollectionService(root, connection)
    context_export = ContextExportService(knowledge, connection)
    return connection, ResearchContextBuilder(
        knowledge,
        collections,
        context_export,
        max_context_entities=max_context_entities,
    )


def _repository(root: Path) -> Path:
    taxonomy = root / "knowledge" / "taxonomy"
    documents = root / "knowledge" / "documents" / "learning"
    terms = root / "knowledge" / "terms"
    sources = root / "knowledge" / "sources"
    collections = root / "knowledge" / "collections"
    for directory in (taxonomy, documents, terms, sources, collections):
        directory.mkdir(parents=True, exist_ok=True)
    (taxonomy / "domains.yaml").write_text(
        "schema_version: 1\nentries:\n  - id: artificial-intelligence\n    title: Artificial Intelligence\n",
        encoding="utf-8",
    )
    (taxonomy / "topics.yaml").write_text(
        "schema_version: 1\nentries:\n  - id: continual-learning\n    title: Continual Learning\n",
        encoding="utf-8",
    )
    (taxonomy / "tags.yaml").write_text(
        "schema_version: 1\nentries: []\n", encoding="utf-8"
    )
    return root


def _write_document(
    root,
    entity_id,
    title,
    body,
    review_status="unreviewed",
    sources=(),
    topics=(),
    domains=(),
):
    path = root / "knowledge" / "documents" / "learning" / "{}.md".format(entity_id)
    path.write_text(
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: learning-note\n"
        "domains:{}\ntopics:{}\ntags: []\nsources:{}\n"
        "review:\n  human:\n    status: {}\n"
        "maintenance:\n  status: current\n---\n# {}\n\n{}\n".format(
            entity_id,
            title,
            _yaml_field(domains),
            _yaml_field(topics),
            _yaml_field(sources),
            review_status,
            title,
            body,
        ),
        encoding="utf-8",
    )


def _write_term(root):
    (root / "knowledge" / "terms" / "fisher-information.md").write_text(
        "---\nschema_version: 1\nid: fisher-information\ntitle: Fisher Information\n"
        "type: concept\ndepth: standard\naliases: []\ndomains: []\ntopics: []\n"
        "tags: []\nsources: []\nreview:\n  human:\n    status: approved\n"
        "---\n# Fisher Information\n\nFisher information measures parameter sensitivity.\n",
        encoding="utf-8",
    )


def _write_source(root):
    (root / "knowledge" / "sources" / "source-alpha.yaml").write_text(
        "schema_version: 1\nid: source-alpha\ntype: paper\ntitle: Source Alpha\n"
        "authors:\n  - Ada Lovelace\nyear: 2024\n"
        "identifiers:\n  doi: 10.1000/alpha\n  arxiv_id: null\n"
        "url: https://doi.org/10.1000/alpha\nmetadata_review:\n  status: verified\n",
        encoding="utf-8",
    )


def _write_collection(root):
    (root / "knowledge" / "collections" / "research-core.yaml").write_text(
        "schema_version: 1\nid: research-core\ntitle: Research Core\n"
        "description: Reviewed continual learning foundations\nstatus: active\n"
        "position: 0\nnodes:\n  - id: core-section\n    kind: section\n"
        "    title: Core\n    children:\n"
        "      - id: ewc-node\n        kind: entity\n"
        "        entity_type: document\n        entity_id: ewc\n"
        "      - id: fisher-node\n        kind: entity\n"
        "        entity_type: term\n        entity_id: fisher-information\n"
        "      - id: source-node\n        kind: entity\n"
        "        entity_type: source\n        entity_id: source-alpha\n",
        encoding="utf-8",
    )


def _yaml_field(values):
    if not values:
        return " []"
    return "\n" + "\n".join("  - {}".format(value) for value in values)


def _profile(profile_id="continual-learning", dynamic=True):
    return ResearchProfile.model_validate(
        {
            "schema_version": 1,
            "id": profile_id,
            "title": profile_id.replace("-", " ").title(),
            "enabled": True,
            "lenses": [
                {
                    "id": "regularization",
                    "title": "Regularization",
                    "enabled": True,
                    "priority": "high",
                    "queries": ["fisher information continual learning"],
                    "include_terms": ["fisher information"],
                    "exclude_terms": [],
                }
            ],
            "exclude_terms": [],
            "providers": {"discovery": ["arxiv"], "enrichment": []},
            "context": {
                "collections": ["research-core"],
                "documents": ["ewc"],
                "dynamic_retrieval": {"enabled": dynamic, "scope": "entire-library"},
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
    )


def _work():
    return ResearchWorkRecord(
        id="research-work",
        canonical_key="doi:10.1000/research",
        title="Fisher Information for Continual Learning",
        normalized_title="fisher information for continual learning",
        abstract="Replay memory and parameter importance reduce forgetting.",
        authors=("Ada Lovelace",),
        year=2026,
        published_at="2026-10-02",
        doi="10.1000/research",
        created_at="2026-10-03T12:00:00+00:00",
        updated_at="2026-10-03T12:00:00+00:00",
    )
