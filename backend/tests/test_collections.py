from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.domain.collection import Collection
from backend.app.services.canonical_validator import validate_repository_references
from backend.app.services.collection_registry import CollectionRegistry
from backend.app.services.markdown_parser import parse_yaml
from tools import kb


def test_collection_schema_accepts_ordered_sections_and_entity_references():
    collection = Collection.model_validate(
        parse_yaml(
            "schema_version: 1\nid: continual-learning\ntitle: 持续学习\n"
            "status: active\nposition: 10\nnodes:\n"
            "  - id: methods\n    kind: section\n    title: 方法\n    children:\n"
            "      - id: ewc-node\n        kind: entity\n"
            "        entity_type: document\n        entity_id: ewc\n"
        )
    )

    assert collection.id == "continual-learning"
    assert collection.nodes[0].children[0].entity_id == "ewc"


@pytest.mark.parametrize(
    ("nodes", "message"),
    [
        (
            "  - id: repeated\n    kind: section\n    title: A\n"
            "  - id: repeated\n    kind: section\n    title: B\n",
            "node IDs must be unique",
        ),
        (
            "  - id: first\n    kind: entity\n    entity_type: document\n    entity_id: ewc\n"
            "  - id: second\n    kind: entity\n    entity_type: document\n    entity_id: ewc\n",
            "only once",
        ),
        (
            "  - id: first\n    kind: section\n    title: A\n    children:\n"
            "      - id: second\n        kind: section\n        title: B\n        children:\n"
            "          - id: third\n            kind: section\n            title: C\n",
            "at most 2 levels",
        ),
    ],
)
def test_collection_schema_rejects_invalid_tree(nodes, message):
    value = parse_yaml(
        "schema_version: 1\nid: test\ntitle: Test\nstatus: active\n"
        "position: 0\nnodes:\n" + nodes
    )

    with pytest.raises(ValidationError, match=message):
        Collection.model_validate(value)


def test_collection_registry_rejects_a_filename_that_does_not_match_id(tmp_path):
    (tmp_path / "other.yaml").write_text(
        "schema_version: 1\nid: canonical-id\ntitle: Test\n"
        "status: active\nposition: 0\nnodes: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not match canonical id"):
        CollectionRegistry.load(tmp_path)


def test_repository_check_accepts_collection_with_existing_canonical_entities(
    tmp_path, monkeypatch, capsys
):
    repository = _write_repository(tmp_path / "repo")
    collection_path = repository / "knowledge" / "collections" / "learning.yaml"
    collection_path.write_text(
        "schema_version: 1\nid: learning\ntitle: Learning\nstatus: active\n"
        "position: 0\nnodes:\n  - id: methods\n    kind: section\n"
        "    title: Methods\n    children:\n"
        "      - id: ewc-node\n        kind: entity\n"
        "        entity_type: document\n        entity_id: ewc\n"
        "      - id: fisher-node\n        kind: entity\n"
        "        entity_type: term\n        entity_id: fisher-information\n"
        "  - id: sources\n    kind: section\n    title: Sources\n"
        "    children:\n      - id: ewc-source-node\n        kind: entity\n"
        "        entity_type: source\n        entity_id: ewc-2017\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kb, "ROOT", repository)

    result = kb.check_paths([repository / "knowledge"])

    assert result == 0, capsys.readouterr().out


def test_repository_check_rejects_collection_references_to_missing_entities(tmp_path):
    repository = _write_repository(tmp_path / "repo")
    collection_path = repository / "knowledge" / "collections" / "learning.yaml"
    collection_path.write_text(
        "schema_version: 1\nid: learning\ntitle: Learning\nstatus: active\n"
        "position: 0\nnodes:\n  - id: missing-note\n    kind: entity\n"
        "    entity_type: document\n    entity_id: missing-note\n",
        encoding="utf-8",
    )

    issues = validate_repository_references(repository)

    assert any(
        issue.code == "reference.collection.entity" and "missing-note" in issue.message
        for issue in issues
    )


def test_kb_check_reports_collection_tree_validation_errors(tmp_path, monkeypatch, capsys):
    repository = _write_repository(tmp_path / "repo")
    collection_path = repository / "knowledge" / "collections" / "learning.yaml"
    collection_path.write_text(
        "schema_version: 1\nid: learning\ntitle: Learning\nstatus: active\n"
        "position: 0\nnodes:\n  - id: repeated\n    kind: section\n"
        "    title: First\n  - id: repeated\n    kind: section\n"
        "    title: Second\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(kb, "ROOT", repository)

    result = kb.check_paths([repository / "knowledge"])

    output = capsys.readouterr().out
    assert result == 1
    assert "schema.metadata" in output
    assert "node IDs must be unique" in output


def _write_repository(repository: Path) -> Path:
    knowledge = repository / "knowledge"
    for directory in (
        knowledge / "collections",
        knowledge / "documents" / "learning",
        knowledge / "terms",
        knowledge / "sources",
        knowledge / "taxonomy",
    ):
        directory.mkdir(parents=True)

    for name in ("domains", "topics", "tags"):
        (knowledge / "taxonomy" / (name + ".yaml")).write_text(
            "schema_version: 1\nentries: []\n", encoding="utf-8"
        )
    (knowledge / "documents" / "learning" / "ewc.md").write_text(
        "---\nschema_version: 1\nid: ewc\ntitle: EWC\ntype: learning-note\n---\n# EWC\n",
        encoding="utf-8",
    )
    (knowledge / "terms" / "fisher-information.md").write_text(
        "---\nschema_version: 1\nid: fisher-information\ntitle: Fisher Information\n"
        "type: concept\ndepth: standard\n---\n# Fisher Information\n",
        encoding="utf-8",
    )
    (knowledge / "sources" / "ewc-2017.yaml").write_text(
        "schema_version: 1\nid: ewc-2017\ntype: paper\ntitle: EWC\n",
        encoding="utf-8",
    )
    return repository
