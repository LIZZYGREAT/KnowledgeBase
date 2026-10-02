from backend.app.domain.imports import ImportItem
from backend.app.services.legacy_import import LegacyImportAdapter
from backend.app.services.markdown_parser import parse_markdown


def test_legacy_import_adapter_generates_metadata_and_preserves_markdown(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    content = "## Introduction\n\n# Historical Note\n\nKeep this body.\n"
    item = ImportItem(
        id="item-id",
        job_id="job-id",
        path="historical-note.md",
        file_type="markdown",
        sha256="a" * 64,
        status="needs_review",
        detected_entity_type="document",
        metadata={"display_name": "historical-note.md"},
    )
    adapter = LegacyImportAdapter(
        repository,
        document_candidates=lambda _entity_id, _title: [],
        slugify=lambda value, fallback: "-".join(value.lower().split()) or fallback,
    )

    normalized = adapter.normalize_markdown(item, content)

    metadata = parse_markdown(normalized.content).frontmatter
    assert metadata["id"] == "historical-note"
    assert metadata["title"] == "Historical Note"
    assert metadata["maintenance"] == {"status": "legacy"}
    assert normalized.content.endswith(content)
    assert normalized.item_metadata == {
        "legacy_frontmatter_generated": True,
        "generated_title": "Historical Note",
        "generated_entity_id": "historical-note",
    }


def test_legacy_import_adapter_forces_legacy_review_defaults():
    content = (
        "---\nschema_version: 1\nid: old-note\ntitle: Old Note\n"
        "type: learning-note\ndomains: []\ntopics: []\ntags: []\nsources: []\n"
        "review:\n  human:\n    status: approved\n"
        "maintenance:\n  status: current\n"
        "---\n# Old Note\n\nKeep body.\n"
    )

    normalized = LegacyImportAdapter.apply_defaults(content)
    metadata = parse_markdown(normalized).frontmatter

    assert metadata["review"]["human"]["status"] == "unreviewed"
    assert metadata["maintenance"]["status"] == "legacy"
    assert normalized.endswith("# Old Note\n\nKeep body.")
