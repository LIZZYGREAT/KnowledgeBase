from pathlib import Path

import pytest

from backend.app.db.connection import connect_database
from backend.app.services.indexer import IndexBuildError, Indexer
from backend.app.services.knowledge_read_service import KnowledgeReadService
from backend.app.services.search_service import SearchFilters, SearchService
from backend.app.services.usage_service import UsageService
from tools.kb import main as kb_main


def test_full_rebuild_restores_all_derived_indexes_and_usage(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    connection = connect_database(":memory:")
    indexer = Indexer(repository, connection)

    first = indexer.full_rebuild()
    assert first.documents == 2
    assert first.terms == 1
    assert first.aliases == 1
    assert first.taxonomy_entries == 3
    assert first.collections == 0
    assert first.collection_nodes == 0
    assert first.backlinks == 2
    assert first.evidence == 1
    assert first.sources == 1

    usage = UsageService(connection)
    usage.record_document_open("neural-indexing")
    usage.record_document_open("neural-indexing")
    usage.record_search_result_click("neural-indexing")

    derived_tables = (
        "document_index", "term_index", "source_index", "alias_index",
        "taxonomy_index", "backlink_index", "evidence_index", "document_fts",
        "term_fts", "source_fts", "evidence_fts", "document_stats",
        "collection_node_index", "collection_index",
    )
    with connection:
        for table in derived_tables:
            connection.execute("DELETE FROM {}".format(table))

    second = indexer.full_rebuild()
    assert second == first
    assert SearchService(connection).search("retains canonical facts")
    stats = connection.execute(
        "SELECT view_count, search_click_count FROM document_stats WHERE document_id = ?",
        ("neural-indexing",),
    ).fetchone()
    assert tuple(stats) == (2, 1)
    assert usage.recently_viewed()[0]["entity_id"] == "neural-indexing"
    assert usage.frequently_viewed()[0]["view_count"] == 2
    connection.close()


def test_collection_indexes_preserve_tree_order_and_derive_unfiled_documents(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    documents = repository / "knowledge" / "documents" / "learning"
    _write(documents / "unfiled-note.md", _document("unfiled-note", "Unfiled Note"))
    collections = repository / "knowledge" / "collections"
    collections.mkdir()
    collection_path = collections / "reading.yaml"
    collection_path.write_text(
        "schema_version: 1\nid: reading\ntitle: Reading\ndescription: Ordered path\n"
        "status: active\nposition: 10\nnodes:\n"
        "  - id: foundations\n    kind: section\n    title: Foundations\n"
        "    children:\n      - id: first-note\n        kind: entity\n"
        "        entity_type: document\n        entity_id: neural-indexing\n"
        "      - id: second-note\n        kind: entity\n"
        "        entity_type: document\n        entity_id: usage-target\n",
        encoding="utf-8",
    )
    connection = connect_database(":memory:")
    indexer = Indexer(repository, connection)

    summary = indexer.full_rebuild()
    nodes = connection.execute(
        """SELECT node_id, parent_node_id, kind, depth, ordinal, section_title,
                  entity_type, entity_id
           FROM collection_node_index WHERE collection_id = ? ORDER BY depth, ordinal""",
        ("reading",),
    ).fetchall()

    assert summary.collections == 1
    assert summary.collection_nodes == 3
    assert [row["node_id"] for row in nodes] == ["foundations", "first-note", "second-note"]
    assert tuple(nodes[1]) == (
        "first-note", "foundations", "entity", 1, 0, "Foundations", "document", "neural-indexing"
    )
    assert tuple(nodes[2]) == (
        "second-note", "foundations", "entity", 1, 1, "Foundations", "document", "usage-target"
    )
    assert [item["id"] for item in KnowledgeReadService(repository, connection).unfiled_documents()] == [
        "unfiled-note"
    ]

    collection_path.write_text(
        collection_path.read_text(encoding="utf-8").replace(
            "        entity_id: usage-target", "        entity_id: unfiled-note"
        ),
        encoding="utf-8",
    )
    incremental = indexer.update_path(collection_path)
    assert incremental.collections == 1
    assert incremental.collection_nodes == 3
    assert [
        item["id"] for item in KnowledgeReadService(repository, connection).unfiled_documents()
    ] == ["usage-target"]
    connection.close()


def test_search_exact_title_alias_fts_evidence_and_structured_filters(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    connection = connect_database(":memory:")
    Indexer(repository, connection).full_rebuild()
    usage = UsageService(connection)
    for _ in range(60):
        usage.record_document_open("usage-target")

    search = SearchService(connection)
    title_results = search.search("Neural Indexing")
    assert title_results[0].entity_id == "neural-indexing"
    assert title_results[0].matched_by == "title"
    assert title_results[0].score > next(
        result.score for result in title_results if result.entity_id == "usage-target"
    )

    alias = search.search("Calibrated Optimizer")
    assert alias[0].entity_type == "term"
    assert alias[0].matched_by == "alias"

    full_text = search.search("stochastic lighthouse")
    assert any(result.entity_id == "usage-target" for result in full_text)
    evidence = search.search("retains canonical facts")
    assert any(result.entity_id == "neural-indexing" for result in evidence)
    source = search.search("Source Alpha")
    assert any(result.entity_type == "source" and result.entity_id == "source-alpha" for result in source)

    filtered = search.search(
        "",
        SearchFilters(
            domain="artificial-intelligence",
            topic="graph-search",
            tag="data-structures",
            document_type="learning-note",
            review="approved",
            maintenance="current",
            source="source-alpha",
            term="neural-indexing",
        ),
    )
    assert [(result.entity_type, result.entity_id) for result in filtered] == [
        ("document", "neural-indexing")
    ]
    connection.close()


def test_search_allowed_entities_contract_excludes_unselected_entities(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    connection = connect_database(":memory:")
    Indexer(repository, connection).full_rebuild()

    results = SearchService(connection).search(
        "retains canonical facts",
        allowed_entities={("document", "neural-indexing")},
    )

    assert results
    assert {(result.entity_type, result.entity_id) for result in results} == {
        ("document", "neural-indexing")
    }
    connection.close()


def test_document_fts_uses_a_small_view_count_boost(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    documents = repository / "knowledge" / "documents" / "learning"
    _write(
        documents / "usage-low.md",
        _document(
            "usage-low", "Usage Low", "shared cobalt fern phrase", (), (), (), ()
        ),
    )
    _write(
        documents / "usage-high.md",
        _document(
            "usage-high", "Usage High", "shared cobalt fern phrase", (), (), (), ()
        ),
    )
    connection = connect_database(":memory:")
    Indexer(repository, connection).full_rebuild()
    search = SearchService(connection)
    baseline = {
        result.entity_id: result.score
        for result in search.search("cobalt fern")
    }
    assert baseline["usage-low"] == baseline["usage-high"]

    usage = UsageService(connection)
    for _ in range(10):
        usage.record_document_open("usage-high")

    results = search.search("cobalt fern")
    by_id = {result.entity_id: result for result in results}

    assert by_id["usage-low"].matched_by == "full text"
    assert by_id["usage-high"].matched_by == "full text"
    assert by_id["usage-high"].score > by_id["usage-low"].score
    assert by_id["usage-high"].score - by_id["usage-low"].score <= 3.0
    connection.close()


def test_search_supports_cjk_literal_substrings_in_canonical_text(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    chinese_body = (
        "EWC 使用 Fisher Information 衡量参数重要性。"
        "本文讨论持续学习、灾难性遗忘与贝叶斯方法。"
    )
    _write(
        repository / "knowledge" / "documents" / "learning" / "chinese-note.md",
        _document("chinese-note", title="Chinese Note", body=chinese_body),
    )
    _write(
        repository / "knowledge" / "terms" / "neural-indexing.md",
        _term().replace("A derived index maps edges.", "术语定义描述知识节点。"),
    )
    _write(
        repository / "knowledge" / "sources" / "source-alpha.yaml",
        "schema_version: 1\nid: source-alpha\ntype: paper\ntitle: 贝叶斯文献\n"
        "authors:\n  - 张三\nyear: 2024\n",
    )
    connection = connect_database(":memory:")
    Indexer(repository, connection).full_rebuild()

    search = SearchService(connection)
    for query in (
        "参数",
        "参数重要性",
        "重要性",
        "持续学习",
        "灾难性遗忘",
        "贝叶斯",
    ):
        results = search.search(query)
        assert results and results[0].entity_id == "chinese-note"
        assert results[0].matched_by == "full text"
    assert not search.search("参数%")
    assert any(result.entity_type == "term" for result in search.search("术语定义"))
    assert any(result.entity_type == "source" for result in search.search("张三"))
    connection.close()


def test_incremental_update_refreshes_document_and_term_backlinks(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    term_path = repository / "knowledge" / "terms" / "neural-indexing.md"
    term_path.write_text(_term(aliases=()), encoding="utf-8")
    connection = connect_database(":memory:")
    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    search = SearchService(connection)

    document_path = repository / "knowledge" / "documents" / "learning" / "neural-indexing.md"
    document_path.write_text(
        _document(
            "neural-indexing",
            body="A new phrase: incremental bluebird. See [[Calibrated Optimizer]].\n",
        ),
        encoding="utf-8",
    )
    indexer.update_path(document_path)
    assert search.search("incremental bluebird")[0].entity_id == "neural-indexing"
    assert not search.search("retains canonical facts")
    assert indexer.backlinks_for("neural-indexing") == []

    term_path.write_text(_term(aliases=("Calibrated Optimizer",)), encoding="utf-8")
    indexer.incremental_update(term_path)
    assert indexer.backlinks_for("neural-indexing")
    assert search.search("Calibrated Optimizer")[0].matched_by == "alias"
    connection.close()


def test_rebuild_cli_recreates_runtime_indexes_from_the_selected_repository(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    database_path = tmp_path / "runtime" / "knowledge.db"

    rebuild_args = ["rebuild", "--root", str(repository), "--database", str(database_path)]
    assert kb_main(rebuild_args) == 0
    connection = connect_database(database_path)
    with connection:
        for table in (
            "document_index", "term_index", "source_index", "alias_index",
            "taxonomy_index", "backlink_index", "evidence_index", "document_fts",
            "term_fts", "source_fts", "evidence_fts", "document_stats",
            "collection_node_index", "collection_index",
        ):
            connection.execute("DROP TABLE {}".format(table))
    connection.close()

    assert kb_main(rebuild_args) == 0
    connection = connect_database(database_path)
    assert connection.execute("SELECT COUNT(*) FROM document_index").fetchone()[0] == 2
    assert connection.execute("SELECT COUNT(*) FROM evidence_index").fetchone()[0] == 1
    connection.close()


def test_failed_rebuild_leaves_the_previous_index_intact(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    connection = connect_database(":memory:")
    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    before = connection.execute("SELECT COUNT(*) FROM document_index").fetchone()[0]

    bad_term = repository / "knowledge" / "terms" / "neural-indexing.md"
    bad_term.write_text(_term(id="wrong-id"), encoding="utf-8")
    try:
        indexer.full_rebuild()
    except IndexBuildError:
        pass
    else:
        raise AssertionError("invalid canonical metadata should fail the rebuild")

    assert connection.execute("SELECT COUNT(*) FROM document_index").fetchone()[0] == before
    assert SearchService(connection).search("retains canonical facts")
    connection.close()


@pytest.mark.parametrize(
    ("entity_type", "source_relative", "duplicate_relative", "label"),
    [
        (
            "document",
            "knowledge/documents/learning/neural-indexing.md",
            "knowledge/documents/learning/archive/neural-indexing.md",
            "Document",
        ),
        (
            "term",
            "knowledge/terms/neural-indexing.md",
            "knowledge/terms/archive/neural-indexing.md",
            "Term",
        ),
        (
            "source",
            "knowledge/sources/source-alpha.yaml",
            "knowledge/sources/archive/source-alpha.yaml",
            "Source",
        ),
        (
            "collection",
            "knowledge/collections/collection-one.yaml",
            "knowledge/collections/archive/collection-one.yaml",
            "Collection",
        ),
    ],
)
def test_rebuild_fails_for_duplicate_canonical_entity_ids(
    tmp_path, entity_type, source_relative, duplicate_relative, label
):
    repository = _create_knowledge_tree(tmp_path / entity_type)
    source = repository / source_relative
    if entity_type == "collection":
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "schema_version: 1\nid: collection-one\ntitle: Collection One\n"
            "status: active\nposition: 0\nnodes: []\n",
            encoding="utf-8",
        )
    duplicate = repository / duplicate_relative
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    connection = connect_database(":memory:")

    with pytest.raises(IndexBuildError, match="Duplicate {} id".format(label)):
        Indexer(repository, connection).full_rebuild()

    connection.close()


def test_incremental_indexer_rejects_noncanonical_paths(tmp_path):
    repository = _create_knowledge_tree(tmp_path / "repo")
    connection = connect_database(":memory:")
    indexer = Indexer(repository, connection)

    with pytest.raises(ValueError, match="Sources must be stored directly"):
        indexer.update_path(
            repository / "knowledge" / "sources" / "nested" / "source-alpha.yaml"
        )
    with pytest.raises(ValueError, match="Runtime, storage, and Git data"):
        indexer.update_path(repository / "runtime" / "draft.md")
    connection.close()


def _create_knowledge_tree(root: Path) -> Path:
    taxonomy = root / "knowledge" / "taxonomy"
    documents = root / "knowledge" / "documents" / "learning"
    terms = root / "knowledge" / "terms"
    sources = root / "knowledge" / "sources"
    for directory in (taxonomy, documents, terms, sources):
        directory.mkdir(parents=True, exist_ok=True)

    _write(taxonomy / "domains.yaml", "schema_version: 1\nentries:\n  - id: artificial-intelligence\n    title: Artificial Intelligence\n")
    _write(taxonomy / "topics.yaml", "schema_version: 1\nentries:\n  - id: graph-search\n    title: Graph Search\n")
    _write(taxonomy / "tags.yaml", "schema_version: 1\nentries:\n  - id: data-structures\n    title: Data Structures\n")
    _write(
        sources / "source-alpha.yaml",
        "schema_version: 1\nid: source-alpha\ntype: paper\ntitle: Source Alpha\n"
        "authors:\n  - Example Author\nyear: 2024\n"
        "identifiers:\n  doi: 10.1000/alpha\n  arxiv_id: null\n"
        "url: https://example.com/source-alpha\n",
    )
    _write(terms / "neural-indexing.md", _term())
    _write(
        documents / "neural-indexing.md",
        _document(
            "neural-indexing",
            title="Neural Indexing",
            body=(
                "A stable index retains canonical facts [@source-alpha, Sec. 2].\n"
                "See [[neural-indexing|self reference]] and [[Calibrated Optimizer]].\n"
            ),
        ),
    )
    _write(
        documents / "usage-target.md",
        _document(
            "usage-target",
            title="Usage Target",
            body="Neural Indexing. A stochastic lighthouse marks this document.\n",
            sources=(),
            domains=(),
            topics=(),
            tags=(),
        ),
    )
    return root


def _document(
    entity_id,
    title="Neural Indexing",
    body="A stable index retains canonical facts [@source-alpha].\n",
    sources=("source-alpha",),
    domains=("artificial-intelligence",),
    topics=("graph-search",),
    tags=("data-structures",),
):
    return (
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: learning-note\n"
        "domains:{}\ntopics:{}\ntags:{}\nsources:{}\n"
        "review:\n  human:\n    status: approved\n"
        "maintenance:\n  status: current\n---\n# {}\n\n{}"
    ).format(
        entity_id,
        title,
        _yaml_field(domains),
        _yaml_field(topics),
        _yaml_field(tags),
        _yaml_field(sources),
        title,
        body,
    )


def _term(id="neural-indexing", aliases=("Calibrated Optimizer",)):
    return (
        "---\nschema_version: 1\nid: {}\ntitle: Index Graph\ntype: concept\n"
        "depth: standard\naliases:{}\ndomains: []\ntopics: []\ntags: []\nsources: []\n"
        "---\n# Index Graph\n\nA derived index maps edges.\n"
    ).format(id, _yaml_field(aliases))


def _yaml_field(values):
    if not values:
        return " []"
    return "\n" + "\n".join("  - {}".format(value) for value in values)


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
