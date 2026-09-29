from pathlib import Path
import shutil
import subprocess

import pytest

from backend.app.db.connection import connect_database
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.proposal_repository import ProposalRepository
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager, GitOperationError
from backend.app.services.indexer import Indexer
from backend.app.services.proposal_service import ProposalService
from backend.app.services.publisher import (
    PublishConflictError,
    PublishError,
    PostPublishIndexUpdateError,
    PublishValidationError,
    Publisher,
)


_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def publish_context(tmp_path):
    repository = tmp_path / "repo"
    _initialize_repository(repository)
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    proposals = ProposalService(ProposalRepository(connection))
    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    publisher = Publisher(repository, drafts, indexer, proposals)
    yield repository, connection, drafts, proposals, publisher
    connection.close()


def test_publish_writes_one_canonical_file_and_commit_only_includes_target(
    publish_context,
):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/new-note.md"
    content = _document("new-note", title="New Note")
    draft = _create_draft(drafts, git, "document", "new-note", content, target)
    assert git.current_revision() == draft.base_git_revision
    assert git.status() == ""

    (repository / "README.md").write_text("staged unrelated change\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    result = publisher.publish(draft.id)

    assert (repository / target).read_text(encoding="utf-8") == content
    assert result.path == target
    assert result.commit_revision == git.current_revision()
    changed_paths = _git(repository, "show", "--pretty=format:", "--name-only", result.commit_revision)
    assert changed_paths.splitlines() == [target]
    assert "README.md" in git.status()


def test_unrelated_commit_does_not_conflict_with_new_file_draft(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/stale-note.md"
    draft = _create_draft(
        drafts, git, "document", "stale-note", _document("stale-note"), target
    )

    (repository / "README.md").write_text("another commit\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "unrelated change")
    result = publisher.publish(draft.id)

    assert (repository / target).is_file()
    assert result.commit_revision == git.current_revision()


def test_other_document_publish_does_not_conflict_with_existing_draft(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    first_path = "knowledge/documents/learning/first-note.md"
    second_path = "knowledge/documents/learning/second-note.md"
    first = _create_draft(drafts, git, "document", "first-note", _document("first-note"), first_path)
    second = _create_draft(drafts, git, "document", "second-note", _document("second-note"), second_path)

    publisher.publish(second.id)
    result = publisher.publish(first.id)

    assert result.entity_id == "first-note"
    assert (repository / first_path).is_file()


def test_publish_rejects_changed_target_content_without_overwriting(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/papers/ewc-review.md"
    original = (repository / target).read_bytes()
    content = _document("ewc-review", title="Edited title")
    draft = _create_draft(drafts, git, "document", "ewc-review", content, target)
    (repository / target).write_text("external unstaged edit\n", encoding="utf-8")

    with pytest.raises(PublishConflictError, match="Canonical file changed"):
        publisher.publish(draft.id)

    assert (repository / target).read_text(encoding="utf-8") == "external unstaged edit\n"
    assert git.current_revision() == draft.base_git_revision
    assert original != (repository / target).read_bytes()


def test_creation_of_empty_target_conflicts_with_missing_target_base(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/created-empty.md"
    draft = _create_draft(
        drafts, git, "document", "created-empty", _document("created-empty"), target
    )
    (repository / target).parent.mkdir(parents=True, exist_ok=True)
    (repository / target).write_bytes(b"")

    with pytest.raises(PublishConflictError, match="Canonical file changed"):
        publisher.publish(draft.id)


def test_deleting_target_conflicts_with_existing_file_base(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/papers/ewc-review.md"
    draft = _create_draft(
        drafts, git, "document", "ewc-review", _document("ewc-review"), target
    )
    (repository / target).unlink()

    with pytest.raises(PublishConflictError, match="Canonical file changed"):
        publisher.publish(draft.id)


def test_validation_failure_does_not_write_or_commit(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/bad-reference.md"
    content = _document("bad-reference", topics=("missing-topic",))
    draft = _create_draft(
        drafts, git, "document", "bad-reference", content, target
    )
    head = git.current_revision()

    with pytest.raises(PublishValidationError, match="Unknown topic"):
        publisher.publish(draft.id)

    assert not (repository / target).exists()
    assert git.current_revision() == head


def test_current_document_style_issues_still_block_publish(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/current-style.md"
    content = _document("current-style") + "\n## Unnumbered section\n"
    draft = _create_draft(drafts, git, "document", "current-style", content, target)

    with pytest.raises(PublishValidationError, match="heading.h2_numbering"):
        publisher.publish(draft.id)
    assert not (repository / target).exists()


def test_legacy_document_style_issues_publish_with_warnings(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/legacy-style.md"
    content = _document("legacy-style").replace(
        "schema_version: 1", "schema_version: 1\nmaintenance:\n  status: legacy", 1
    ) + "\n## Old section numbering\n"
    draft = _create_draft(drafts, git, "document", "legacy-style", content, target)

    result = publisher.publish(draft.id)

    assert (repository / target).is_file()
    assert any("heading.h2_numbering" in warning for warning in result.warnings)


def test_legacy_document_with_broken_frontmatter_cannot_publish(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/broken-legacy.md"
    content = (
        "---\nschema_version: 1\nid: broken-legacy\ntitle: Broken Legacy\n"
        "type: learning-note\nmaintenance:\n  status: legacy\n"
    )
    draft = _create_draft(drafts, git, "document", "broken-legacy", content, target)

    with pytest.raises(PublishValidationError, match="frontmatter"):
        publisher.publish(draft.id)
    assert not (repository / target).exists()


def test_unrelated_malformed_markdown_does_not_block_publish(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    unrelated = repository / "knowledge" / "documents" / "learning" / "temporarily-broken.md"
    unrelated.write_text("---\nnot valid frontmatter\n", encoding="utf-8")
    target = "knowledge/documents/learning/local-validation.md"
    draft = _create_draft(
        drafts, git, "document", "local-validation", _document("local-validation"), target
    )

    with pytest.raises(PostPublishIndexUpdateError) as error:
        publisher.publish(draft.id)
    assert (repository / target).is_file()
    assert error.value.commit_revision == git.current_revision()


def test_approved_proposal_is_applied_and_merged_after_commit(publish_context):
    repository, _, drafts, proposals, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/proposed-note.md"
    content = _document("proposed-note", title="Approved Content")
    draft = _create_draft(
        drafts, git, "document", "proposed-note", "draft placeholder", target
    )
    proposal = proposals.create(
        "document",
        "proposed-note",
        "document_revision",
        git.content_hash(target),
        {"content": content},
        "reviewer",
    )
    proposals.approve(proposal.id, git.content_hash(target), "checked")

    result = publisher.publish(draft.id, proposal_id=proposal.id)

    assert (repository / target).read_text(encoding="utf-8") == content
    assert proposals.get(proposal.id).status == "merged"
    assert result.proposal_id == proposal.id
    assert result.commit_revision == git.current_revision()


def test_proposal_survives_unrelated_document_publish(publish_context):
    repository, _, drafts, proposals, publisher = publish_context
    git = GitManager(repository)
    proposal_target = "knowledge/documents/learning/proposal-target.md"
    other_target = "knowledge/documents/learning/other-target.md"
    proposal_content = _document("proposal-target", title="Proposed Content")
    proposal_draft = _create_draft(
        drafts, git, "document", "proposal-target", "draft placeholder", proposal_target
    )
    proposal = proposals.create(
        "document",
        "proposal-target",
        "document_revision",
        git.content_hash(proposal_target),
        {"content": proposal_content},
        "reviewer",
    )
    proposals.approve(proposal.id, git.content_hash(proposal_target), "checked")
    other_draft = _create_draft(
        drafts, git, "document", "other-target", _document("other-target"), other_target
    )

    publisher.publish(other_draft.id)
    result = publisher.publish(proposal_draft.id, proposal_id=proposal.id)

    assert result.entity_id == "proposal-target"
    assert proposals.get(proposal.id).status == "merged"


def test_restore_creates_a_new_commit_and_preserves_published_history(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/terms/fisher-information.md"
    before_revision = git.current_revision()
    before_content = (repository / target).read_bytes()
    updated = _term("fisher-information", title="Updated Fisher Information")
    draft = _create_draft(drafts, git, "term", "fisher-information", updated, target)

    published = publisher.publish(draft.id)
    restored_revision = publisher.restore(target, before_revision)

    assert restored_revision != published.commit_revision
    assert (repository / target).read_bytes() == before_content
    _git(repository, "cat-file", "-e", published.commit_revision)
    assert _git(repository, "show", "-s", "--format=%s", restored_revision).startswith("restore:")
    with pytest.raises(GitOperationError):
        publisher.restore(target, "0" * 40)
    assert git.current_revision() == restored_revision


def test_restore_to_before_new_file_creation_records_deletion_commit(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/new-note.md"
    before_creation = git.current_revision()
    draft = _create_draft(
        drafts,
        git,
        "document",
        "new-note",
        _document("new-note"),
        target,
    )
    published = publisher.publish(draft.id)

    restored = publisher.restore(target, before_creation)

    assert restored != published.commit_revision
    assert not (repository / target).exists()
    assert _git(repository, "show", "-s", "--format=%s", restored).startswith("restore:")
    _git(repository, "cat-file", "-e", published.commit_revision)


def test_taxonomy_removal_cannot_leave_dangling_canonical_references(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/taxonomy/domains.yaml"
    content = "schema_version: 1\nentries: []\n"
    draft = _create_draft(drafts, git, "taxonomy", "domains", content, target)

    with pytest.raises(PublishValidationError, match="removed domain"):
        publisher.publish(draft.id)

    assert git.current_revision() == draft.base_git_revision
    assert "artificial-intelligence" in (repository / target).read_text(encoding="utf-8")


def test_unresolved_wiki_link_is_retained_but_ambiguous_link_blocks_publish(
    publish_context,
):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    unresolved_path = "knowledge/documents/learning/unresolved-note.md"
    unresolved = _document("unresolved-note", body="See [[not-created-yet]].\n")
    draft = _create_draft(
        drafts, git, "document", "unresolved-note", unresolved, unresolved_path
    )
    publisher.publish(draft.id)
    assert "[[not-created-yet]]" in (repository / unresolved_path).read_text(encoding="utf-8")

    duplicate_term = _term("fisher-variant", title="Fisher Information")
    term_path = repository / "knowledge" / "terms" / "fisher-variant.md"
    term_path.write_text(duplicate_term, encoding="utf-8")
    _git(repository, "add", "knowledge/terms/fisher-variant.md")
    _git(repository, "commit", "-m", "add ambiguous term")
    current = GitManager(repository)
    ambiguous_path = "knowledge/documents/learning/ambiguous-note.md"
    ambiguous = _document(
        "ambiguous-note", body="See [[Fisher Information]].\n"
    )
    ambiguous_draft = _create_draft(
        drafts, current, "document", "ambiguous-note", ambiguous, ambiguous_path
    )

    with pytest.raises(PublishValidationError, match="Ambiguous wiki link"):
        publisher.publish(ambiguous_draft.id)
    assert not (repository / ambiguous_path).exists()


def test_publisher_supports_term_source_and_taxonomy_canonical_paths(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)

    term_path = "knowledge/terms/new-concept.md"
    term_content = _term("new-concept", title="New Concept")
    term_draft = _create_draft(drafts, git, "term", "new-concept", term_content, term_path)
    publisher.publish(term_draft.id)

    git = GitManager(repository)
    source_path = "knowledge/sources/new-source.yaml"
    source_content = (
        "schema_version: 1\nid: new-source\ntype: web\ntitle: New Source\n"
        "url: https://example.com/reference\n"
    )
    source_draft = _create_draft(
        drafts, git, "source", "new-source", source_content, source_path
    )
    publisher.publish(source_draft.id)

    git = GitManager(repository)
    taxonomy_path = "knowledge/taxonomy/tags.yaml"
    taxonomy_content = (
        "schema_version: 1\nentries:\n"
        "  - id: regularization\n    title: Regularization\n"
        "  - id: verified\n    title: Verified\n"
    )
    taxonomy_draft = _create_draft(
        drafts, git, "taxonomy", "tags", taxonomy_content, taxonomy_path
    )
    publisher.publish(taxonomy_draft.id)

    assert (repository / term_path).is_file()
    assert (repository / source_path).is_file()
    assert (repository / taxonomy_path).is_file()


def test_publisher_refreshes_incremental_index_after_publish_and_restore(publish_context):
    repository, connection, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/indexed-note.md"
    before_publish = git.current_revision()
    draft = _create_draft(
        drafts,
        git,
        "document",
        "indexed-note",
        _document("indexed-note", body="Publisher incremental index phrase.\n"),
        target,
    )

    published = publisher.publish(draft.id)
    assert connection.execute(
        "SELECT title FROM document_index WHERE entity_id = ?", ("indexed-note",)
    ).fetchone()[0] == "Test Note"

    publisher.restore(target, before_publish)
    assert connection.execute(
        "SELECT 1 FROM document_index WHERE entity_id = ?", ("indexed-note",)
    ).fetchone() is None
    _git(repository, "cat-file", "-e", published.commit_revision)


def _initialize_repository(repository: Path) -> None:
    repository.mkdir()
    shutil.copytree(_ROOT / "config", repository / "config")
    shutil.copytree(_ROOT / "knowledge", repository / "knowledge")
    (repository / "knowledge" / "documents" / "papers").mkdir(parents=True, exist_ok=True)
    (repository / "knowledge" / "terms").mkdir(parents=True, exist_ok=True)
    (repository / "knowledge" / "sources").mkdir(parents=True, exist_ok=True)
    (repository / "knowledge" / "documents" / "papers" / "ewc-review.md").write_text(
        (_ROOT / "backend" / "tests" / "fixtures" / "valid_document.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repository / "knowledge" / "terms" / "fisher-information.md").write_text(
        (_ROOT / "backend" / "tests" / "fixtures" / "valid_term.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (repository / "knowledge" / "sources" / "ewc-2017.yaml").write_text(
        (_ROOT / "backend" / "tests" / "fixtures" / "valid_source.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    registries = {
        "domains.yaml": [("artificial-intelligence", "Artificial Intelligence")],
        "topics.yaml": [("continual-learning", "Continual Learning")],
        "tags.yaml": [("regularization", "Regularization")],
    }
    for filename, entries in registries.items():
        lines = ["schema_version: 1", "entries:"]
        for entity_id, title in entries:
            lines.extend(["  - id: {}".format(entity_id), "    title: {}".format(title)])
        (repository / "knowledge" / "taxonomy" / filename).write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    (repository / "README.md").write_text("fixture\n", encoding="utf-8")

    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "KnowledgeBase Tests")
    _git(repository, "config", "user.email", "kb-tests@example.invalid")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "initial canonical state")


def _create_draft(drafts, git, entity_type, entity_id, content, relative_path):
    return drafts.create(
        entity_type,
        entity_id,
        content,
        git.current_revision(),
        git.content_hash(relative_path),
    )


def _document(entity_id, title="Test Note", topics=("continual-learning",), body=None):
    topic_lines = "".join("  - {}\n".format(topic) for topic in topics) or "  []\n"
    body = body or "See [[fisher-information]] and [@ewc-2017].\n"
    return (
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: learning-note\n"
        "domains:\n  - artificial-intelligence\ntopics:\n{}tags:\n"
        "  - regularization\nsources:\n  - ewc-2017\n---\n# {}\n\n{}"
    ).format(entity_id, title, topic_lines, title, body)


def _term(entity_id, title, aliases=()):
    alias_text = "".join("  - {}\n".format(alias) for alias in aliases) or "  []\n"
    return (
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: concept\n"
        "depth: standard\naliases:\n{}domains:\n  - artificial-intelligence\n"
        "topics: []\ntags: []\nsources: []\n---\n# {}\n\nA concise definition.\n"
    ).format(entity_id, title, alias_text, title)


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
