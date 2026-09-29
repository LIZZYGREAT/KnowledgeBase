from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from backend.app.db.connection import connect_database
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.import_repository import ImportRepository
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager
from backend.app.services.import_service import ImportService, ImportValidationError
from backend.app.services.indexer import Indexer
from backend.app.repositories.proposal_repository import ProposalRepository
from backend.app.services.proposal_service import ProposalService
from backend.app.services.publisher import (
    PublishConflictError,
    PublishValidationError,
    Publisher,
)


_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def import_context(tmp_path):
    repository = tmp_path / "repo"
    _initialize_repository(repository)
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    imports = ImportRepository(connection)
    service = ImportService(repository, imports, drafts)
    yield repository, connection, drafts, imports, service
    connection.close()


def test_directory_import_stages_markdown_and_pdf_as_manual_bundle(import_context, tmp_path):
    repository, connection, drafts, imports, service = import_context
    source_directory = tmp_path / "incoming" / "Bundle Note"
    source_directory.mkdir(parents=True)
    markdown_path = source_directory / "Bundle Note.md"
    pdf_path = source_directory / "Bundle Note.pdf"
    markdown_path.write_text(_document("bundle-note", "Bundle Note"), encoding="utf-8")
    pdf_path.write_bytes(b"%PDF-1.7\nminimal test document")
    git = GitManager(repository)
    original_revision = git.current_revision()

    job = service.stage_paths([source_directory])
    items = service.get_items(job.id)
    markdown = next(item for item in items if item.file_type == "markdown")
    pdf = next(item for item in items if item.file_type == "pdf")

    assert job.status == "ready"
    assert markdown.metadata["bundle_association"]["status"] == "suggested"
    assert pdf.metadata["bundle_association"]["status"] == "suggested"
    assert (repository / markdown.metadata["staging_path"]).is_file()
    assert (repository / pdf.metadata["staging_path"]).is_file()

    document_draft = service.create_draft(markdown.id)
    assert document_draft.entity_type == "document"
    assert not (repository / "knowledge" / "documents" / "learning" / "bundle-note.md").exists()
    assert git.current_revision() == original_revision

    source_draft = service.confirm_pdf_source(pdf.id)
    assert source_draft.entity_type == "source"
    source_metadata = yaml.safe_load(source_draft.content)
    assert source_metadata["attachments"]["local_pdf"] == "storage://papers/bundle-note.pdf"
    assert (repository / "storage" / "papers" / "bundle-note.pdf").is_file()
    assert not (repository / "knowledge" / "sources" / "bundle-note.yaml").exists()
    assert git.current_revision() == original_revision

    confirmed_markdown, confirmed_pdf = service.associate_bundle(markdown.id, pdf.id)
    assert confirmed_markdown.metadata["bundle_association"]["status"] == "confirmed"
    assert confirmed_pdf.metadata["bundle_association"]["status"] == "confirmed"
    assert imports.get_item(markdown.id).status == "drafted"


def test_pdf_only_creates_source_draft_and_never_creates_a_note(import_context, tmp_path):
    repository, _, _, _, service = import_context
    pdf = tmp_path / "only-source.pdf"
    pdf.write_bytes(b"%PDF-1.4\nminimal PDF data")

    job = service.stage_paths([pdf])
    item = service.get_items(job.id)[0]
    draft = service.confirm_pdf_source(item.id, title="Only Source")

    assert draft.entity_type == "source"
    assert draft.entity_id == "only-source"
    assert not list((repository / "knowledge" / "documents").rglob("*.md"))
    assert not (repository / "knowledge" / "sources" / "only-source.yaml").exists()


def test_pdf_source_publish_commits_metadata_and_keeps_pdf_out_of_git(
    import_context, tmp_path
):
    repository, connection, drafts, _, service = import_context
    imported_pdf = tmp_path / "published-paper.pdf"
    imported_pdf.write_bytes(b"%PDF-1.7\nsource attachment")
    job = service.stage_paths([imported_pdf])
    item = service.get_items(job.id)[0]
    draft = service.confirm_pdf_source(item.id, title="Published Paper")
    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    publisher = Publisher(
        repository,
        drafts,
        indexer,
        ProposalService(ProposalRepository(connection)),
    )

    result = publisher.publish(draft.id)

    assert result.path == "knowledge/sources/published-paper.yaml"
    assert (repository / "knowledge" / "sources" / "published-paper.yaml").is_file()
    assert (repository / "storage" / "papers" / "published-paper.pdf").is_file()
    committed_paths = _git(repository, "show", "--format=", "--name-only", "HEAD").splitlines()
    assert committed_paths == ["knowledge/sources/published-paper.yaml"]
    indexed = connection.execute(
        "SELECT entity_id FROM source_index WHERE entity_id = ?", ("published-paper",)
    ).fetchone()
    assert indexed[0] == "published-paper"


def test_hash_deduplication_detects_canonical_and_previous_imports(import_context, tmp_path):
    repository, _, _, _, service = import_context
    canonical = repository / "knowledge" / "documents" / "learning" / "canonical-note.md"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    content = _document("canonical-note", "Canonical Note")
    canonical.write_text(content, encoding="utf-8")
    _git(repository, "add", "knowledge/documents/learning/canonical-note.md")
    _git(repository, "commit", "-m", "add canonical fixture")
    canonical_copy = tmp_path / "canonical-copy.md"
    canonical_copy.write_bytes(canonical.read_bytes())

    canonical_job = service.stage_paths([canonical_copy])
    canonical_item = service.get_items(canonical_job.id)[0]
    assert canonical_item.status == "duplicate"
    assert canonical_item.metadata["duplicate_kind"] == "canonical"
    with pytest.raises(ImportValidationError, match="Duplicate files"):
        service.create_draft(canonical_item.id)

    first_copy = tmp_path / "new-note.md"
    first_copy.write_text(_document("new-note", "New Note"), encoding="utf-8")
    first_job = service.stage_paths([first_copy])
    first_item = service.get_items(first_job.id)[0]
    assert first_item.status == "ready"
    second_job = service.stage_paths([first_copy])
    second_item = service.get_items(second_job.id)[0]
    assert second_item.status == "duplicate"
    assert second_item.metadata["duplicate_kind"] == "import_item"


def test_legacy_batch_sets_unreviewed_and_legacy_defaults_and_allows_manual_fix(
    import_context, tmp_path
):
    _, _, _, _, service = import_context
    batch = tmp_path / "legacy-notes"
    batch.mkdir()
    (batch / "valid-legacy.md").write_text(
        _document("valid-legacy", "Valid Legacy", include_review=False),
        encoding="utf-8",
    )
    (batch / "needs-metadata.md").write_text("# An old note\n\nNo metadata yet.\n", encoding="utf-8")

    job = service.stage_paths([batch], profile="legacy")
    items = {Path(item.path).name: item for item in service.get_items(job.id)}
    assert items["needs-metadata.md"].status == "needs_review"
    assert items["valid-legacy.md"].status == "ready"
    with pytest.raises(ImportValidationError, match="frontmatter"):
        service.create_draft(items["needs-metadata.md"].id)

    fixed = _document("needs-metadata", "Fixed Legacy", include_review=False)
    updated = service.update_markdown_item(items["needs-metadata.md"].id, fixed)
    assert updated.status == "ready"
    fixed_draft = service.create_draft(updated.id)
    fixed_metadata = _frontmatter(fixed_draft.content)
    assert fixed_metadata["review"]["human"]["status"] == "unreviewed"
    assert fixed_metadata["maintenance"]["status"] == "legacy"

    valid_draft = service.create_draft(items["valid-legacy.md"].id)
    legacy_metadata = _frontmatter(valid_draft.content)
    assert legacy_metadata["review"]["human"]["status"] == "unreviewed"
    assert legacy_metadata["maintenance"]["status"] == "legacy"


def test_markdown_with_style_issues_can_enter_a_draft(import_context, tmp_path):
    _, _, _, _, service = import_context
    source = tmp_path / "style-issue.md"
    source.write_text(
        _document("style-issue", "Style Issue") + "\n## Unnumbered section\n",
        encoding="utf-8",
    )

    job = service.stage_paths([source])
    item = service.get_items(job.id)[0]
    assert item.status == "needs_review"

    draft = service.create_draft(item.id)
    updated_item = service.get_items(job.id)[0]

    assert draft.entity_id == "style-issue"
    assert updated_item.status == "drafted"
    assert any(issue["code"] == "heading.h2_numbering" for issue in updated_item.metadata["lint_issues"])


def test_new_blank_document_creates_runtime_draft_only(import_context):
    repository, _, _, _, service = import_context
    git = GitManager(repository)
    original_revision = git.current_revision()

    draft = service.create_blank_document("A Blank Note", "learning-note")

    assert draft.entity_type == "document"
    assert draft.entity_id == "a-blank-note"
    metadata = _frontmatter(draft.content)
    assert metadata["review"]["human"]["status"] == "unreviewed"
    assert metadata["provenance"]["origin"] == "human-authored"
    assert not (repository / "knowledge" / "documents" / "learning" / "a-blank-note.md").exists()
    assert git.current_revision() == original_revision
    assert git.status() == ""


def test_pdf_source_resolver_updates_existing_source_draft_without_overwriting(
    import_context, tmp_path
):
    repository, _, _, _, service = import_context
    sources = repository / "knowledge" / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    existing_source = sources / "source-alpha.yaml"
    original = (
        "schema_version: 1\nid: source-alpha\ntype: paper\ntitle: Existing Source\n"
        "identifiers:\n  doi: 10.1000/existing\n  arxiv_id: null\n"
        "authors:\n  - Example Author\nyear: 2021\n"
    )
    existing_source.write_text(original, encoding="utf-8")
    _git(repository, "add", "knowledge/sources/source-alpha.yaml")
    _git(repository, "commit", "-m", "add source fixture")
    imported_pdf = tmp_path / "existing-source.pdf"
    imported_pdf.write_bytes(b"%PDF-1.7\nsource content")

    job = service.stage_paths([imported_pdf])
    item = service.get_items(job.id)[0]
    draft = service.confirm_pdf_source(
        item.id, doi="10.1000/not-found", title="Existing Source"
    )

    assert draft.entity_id == "source-alpha"
    candidate = yaml.safe_load(draft.content)
    assert candidate["title"] == "Existing Source"
    assert candidate["authors"] == ["Example Author"]
    assert candidate["attachments"]["local_pdf"] == "storage://papers/source-alpha.pdf"
    assert existing_source.read_text(encoding="utf-8") == original
    assert (repository / "storage" / "papers" / "source-alpha.pdf").is_file()


def test_invalid_pdf_is_recorded_failed_and_duplicate_pdf_is_not_copied_again(
    import_context, tmp_path
):
    repository, _, _, _, service = import_context
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a PDF")
    job = service.stage_paths([invalid])
    item = service.get_items(job.id)[0]
    assert job.status == "failed"
    assert item.status == "failed"

    pdf = tmp_path / "repeat.pdf"
    pdf.write_bytes(b"%PDF-1.5\ncopy me")
    first = service.stage_paths([pdf])
    first_item = service.get_items(first.id)[0]
    second = service.stage_paths([pdf])
    duplicate = service.get_items(second.id)[0]
    assert first_item.status == "ready"
    assert duplicate.status == "duplicate"
    assert duplicate.metadata["duplicate_kind"] == "import_item"
    assert "staging_path" not in duplicate.metadata
    assert not (repository / "storage" / "papers" / "repeat.pdf").exists()


def test_import_draft_cannot_publish_over_a_changed_canonical_document(import_context, tmp_path):
    repository, connection, drafts, _, service = import_context
    target = repository / "knowledge" / "documents" / "learning" / "conflicted.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_document("conflicted", "Version A"), encoding="utf-8")
    _git(repository, "add", "knowledge/documents/learning/conflicted.md")
    _git(repository, "commit", "-m", "add version A")

    incoming = tmp_path / "version-b.md"
    incoming.write_text(_document("conflicted", "Version B"), encoding="utf-8")
    job = service.stage_paths([incoming])
    item = service.get_items(job.id)[0]
    draft = service.create_draft(item.id)

    target.write_text(_document("conflicted", "Version C"), encoding="utf-8")
    _git(repository, "add", "knowledge/documents/learning/conflicted.md")
    _git(repository, "commit", "-m", "canonical version C")
    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    publisher = Publisher(
        repository,
        drafts,
        indexer,
        ProposalService(ProposalRepository(connection)),
    )

    with pytest.raises(PublishConflictError):
        publisher.publish(draft.id)
    assert "Version C" in target.read_text(encoding="utf-8")
    assert GitManager(repository).current_revision() != draft.base_git_revision


def test_source_draft_cannot_publish_when_staged_pdf_is_missing(import_context, tmp_path):
    repository, connection, drafts, _, service = import_context
    imported_pdf = tmp_path / "source-attachment.pdf"
    imported_pdf.write_bytes(b"%PDF-1.7\nsource attachment")
    job = service.stage_paths([imported_pdf])
    item = service.get_items(job.id)[0]
    draft = service.confirm_pdf_source(item.id, title="Source Attachment")
    stored_pdf = repository / "storage" / "papers" / "source-attachment.pdf"
    assert stored_pdf.is_file()
    stored_pdf.unlink()

    publisher = Publisher(
        repository,
        drafts,
        Indexer(repository, connection),
        ProposalService(ProposalRepository(connection)),
    )

    with pytest.raises(PublishValidationError, match="attachment is missing"):
        publisher.publish(draft.id)
    assert not (repository / "knowledge" / "sources" / "source-attachment.yaml").exists()


def _initialize_repository(repository: Path) -> None:
    repository.mkdir(parents=True)
    shutil.copytree(_ROOT / "config", repository / "config")
    shutil.copytree(_ROOT / "knowledge", repository / "knowledge")
    shutil.copy2(_ROOT / ".gitignore", repository / ".gitignore")
    for relative in (
        "knowledge/documents/papers",
        "knowledge/documents/learning",
        "knowledge/documents/courses",
        "knowledge/terms",
        "knowledge/sources",
        "storage/staging",
        "storage/papers",
    ):
        (repository / relative).mkdir(parents=True, exist_ok=True)
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "KnowledgeBase Import Tests")
    _git(repository, "config", "user.email", "kb-import-tests@example.invalid")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "initial Import fixture")


def _document(entity_id, title, include_review=True):
    review = "review:\n  human:\n    status: approved\n" if include_review else ""
    return (
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: learning-note\n"
        "{}---\n# {}\n\nImported text.\n"
    ).format(entity_id, title, review, title)


def _frontmatter(content):
    from backend.app.services.markdown_parser import parse_markdown

    return parse_markdown(content).frontmatter


def _git(repository, *arguments):
    result = subprocess.run(
        ["git", "-C", str(repository)] + list(arguments),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout.strip()
