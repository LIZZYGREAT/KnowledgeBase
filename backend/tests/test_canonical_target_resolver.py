from pathlib import Path

import pytest

from backend.app.db.connection import connect_database
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver


@pytest.fixture
def resolver(tmp_path):
    repository = tmp_path / "repository"
    (repository / "knowledge").mkdir(parents=True)
    connection = connect_database(":memory:")
    instance = CanonicalTargetResolver(repository, connection)
    yield repository, connection, instance
    connection.close()


def test_resolves_document_to_its_indexed_path(resolver):
    repository, connection, target_resolver = resolver
    path = "knowledge/documents/papers/indexed-document.md"
    (repository / path).parent.mkdir(parents=True)
    (repository / path).write_text(_document("indexed-document", "paper-note"), encoding="utf-8")
    connection.execute(
        """INSERT INTO document_index
           (entity_id, path, title, document_type, metadata_json, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("indexed-document", path, "Indexed", "paper-note", '{"id":"indexed-document","type":"paper-note"}', "hash"),
    )

    result = target_resolver.resolve_target(
        "document", "indexed-document", _document("indexed-document", "paper-note")
    )

    assert result.path == repository / path
    assert result.metadata.type == "paper-note"


def test_resolves_term_to_its_indexed_path(resolver):
    repository, connection, target_resolver = resolver
    path = "knowledge/terms/indexed-term.md"
    connection.execute(
        """INSERT INTO term_index
           (entity_id, path, title, term_type, depth, aliases_json, metadata_json, content_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("indexed-term", path, "Indexed", "concept", "standard", "[]", '{"id":"indexed-term"}', "hash"),
    )

    result = target_resolver.resolve_target("term", "indexed-term", _term("indexed-term"))

    assert result.path == repository / path
    assert result.metadata.id == "indexed-term"


def test_resolves_source_collection_and_taxonomy_paths(resolver):
    repository, _, target_resolver = resolver
    source = "schema_version: 1\nid: source-one\ntype: web\ntitle: Source One\n"
    collection = (
        "schema_version: 1\nid: collection-one\ntitle: Collection One\n"
        "status: active\nposition: 0\nnodes: []\n"
    )
    taxonomy = "schema_version: 1\nentries: []\n"

    assert target_resolver.resolve_target("source", "source-one", source).path == (
        repository / "knowledge/sources/source-one.yaml"
    )
    assert target_resolver.resolve_target("collection", "collection-one", collection).path == (
        repository / "knowledge/collections/collection-one.yaml"
    )
    assert target_resolver.resolve_target("taxonomy", "topics", taxonomy).path == (
        repository / "knowledge/taxonomy/topics.yaml"
    )


def test_rejects_document_type_changes(resolver):
    _, connection, target_resolver = resolver
    indexed_path = "knowledge/documents/papers/same-id.md"
    connection.execute(
        """INSERT INTO document_index
           (entity_id, path, title, document_type, metadata_json, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("same-id", indexed_path, "Same", "paper-note", '{"type":"paper-note"}', "hash"),
    )
    with pytest.raises(ValueError, match="cannot change its canonical type"):
        target_resolver.resolve_target("document", "same-id", _document("same-id", "course-note"))


def test_resolving_existing_document_does_not_scan_the_document_tree(resolver, monkeypatch):
    repository, connection, target_resolver = resolver
    indexed_path = "knowledge/documents/papers/indexed-document.md"
    connection.execute(
        """INSERT INTO document_index
           (entity_id, path, title, document_type, metadata_json, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("indexed-document", indexed_path, "Indexed", "paper-note", "{}", "hash"),
    )

    def fail_rglob(*_args, **_kwargs):
        raise AssertionError("CanonicalTargetResolver must not scan the knowledge tree")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    result = target_resolver.resolve_target(
        "document", "indexed-document", _document("indexed-document", "paper-note")
    )

    assert result.path == repository / indexed_path


def test_rejects_unsafe_indexed_paths_and_mismatched_entity_ids(resolver):
    _, connection, target_resolver = resolver
    connection.execute(
        """INSERT INTO document_index
           (entity_id, path, title, document_type, metadata_json, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("unsafe-id", "../../outside/unsafe-id.md", "Unsafe", "paper-note", "{}", "hash"),
    )
    with pytest.raises(ValueError, match="Indexed canonical path is invalid"):
        target_resolver.resolve_target("document", "unsafe-id", _document("unsafe-id", "paper-note"))
    with pytest.raises(ValueError, match="must match"):
        target_resolver.resolve_target("source", "expected-id", "schema_version: 1\nid: other-id\ntype: web\ntitle: Source\n")


def _document(entity_id: str, document_type: str) -> str:
    return (
        "---\nschema_version: 1\nid: {}\ntitle: Example\ntype: {}\n"
        "domains: []\ntopics: []\ntags: []\nsources: []\n---\n# Example\n"
    ).format(entity_id, document_type)


def _term(entity_id: str) -> str:
    return (
        "---\nschema_version: 1\nid: {}\ntitle: Example\ntype: concept\n"
        "depth: standard\naliases: []\ndomains: []\ntopics: []\ntags: []\n"
        "sources: []\n---\n# Example\n"
    ).format(entity_id)
