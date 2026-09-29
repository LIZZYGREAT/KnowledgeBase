from pathlib import Path

from backend.app.services.canonical_validator import validate_repository_references
from tools import kb


def test_repository_check_finds_dangling_references_and_ambiguous_links(tmp_path):
    repository = _write_reference_fixture(tmp_path / "repo")

    issues = validate_repository_references(repository)
    codes = {issue.code for issue in issues}

    assert "reference.taxonomy.topic" in codes
    assert "reference.source" in codes
    assert "reference.citation.source" in codes
    assert "reference.wiki.ambiguous" in codes
    assert "reference.wiki.unresolved" not in codes


def test_kb_check_fails_for_repository_wide_reference_errors(tmp_path, monkeypatch, capsys):
    repository = _write_reference_fixture(tmp_path / "repo")
    monkeypatch.setattr(kb, "ROOT", repository)

    result = kb.check_paths([repository / "knowledge"])

    output = capsys.readouterr().out
    assert result == 1
    assert "reference.taxonomy.topic" in output
    assert "reference.citation.source" in output
    assert "reference.wiki.ambiguous" in output


def _write_reference_fixture(repository: Path) -> Path:
    knowledge = repository / "knowledge"
    (knowledge / "taxonomy").mkdir(parents=True)
    (knowledge / "documents" / "learning").mkdir(parents=True)
    (knowledge / "terms").mkdir()
    (knowledge / "sources").mkdir()

    (knowledge / "taxonomy" / "domains.yaml").write_text(
        "schema_version: 1\nentries:\n  - id: ai\n    title: AI\n", encoding="utf-8"
    )
    (knowledge / "taxonomy" / "topics.yaml").write_text(
        "schema_version: 1\nentries:\n  - id: topic\n    title: Topic\n", encoding="utf-8"
    )
    (knowledge / "taxonomy" / "tags.yaml").write_text(
        "schema_version: 1\nentries:\n  - id: tag\n    title: Tag\n", encoding="utf-8"
    )
    (knowledge / "sources" / "known-source.yaml").write_text(
        "schema_version: 1\nid: known-source\ntype: personal\ntitle: Known Source\n",
        encoding="utf-8",
    )
    for entity_id, title in (("term-a", "Term A"), ("term-b", "Term B")):
        (knowledge / "terms" / "{}.md".format(entity_id)).write_text(
            "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: concept\n"
            "depth: standard\naliases:\n  - shared alias\n---\n# {}\n".format(
                entity_id, title, title
            ),
            encoding="utf-8",
        )
    (knowledge / "documents" / "learning" / "note.md").write_text(
        "---\nschema_version: 1\nid: note\ntitle: Note\ntype: learning-note\n"
        "topics:\n  - missing-topic\nsources:\n  - missing-source\n---\n"
        "# Note\n\n[@unknown-source] [[shared alias]] [[unresolved term]]\n",
        encoding="utf-8",
    )
    return repository
