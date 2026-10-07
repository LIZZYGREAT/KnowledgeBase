import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest
import os
from backend.app.db.connection import connect_database
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.proposal_repository import ProposalRepository
from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.domain.term_runtime import (
    TermCandidateEvidenceInput,
    TermCandidateRecord,
)
from backend.app.services.draft_service import DraftService
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.git_manager import GitManager, GitOperationError
from backend.app.services.indexer import Indexer
from backend.app.services.knowledge_read_service import KnowledgeReadService
from backend.app.services.proposal_service import ProposalService
from backend.app.services.publisher import (
    PublishConflictError,
    PublishError,
    PublishValidationError,
    Publisher,
)
from backend.app.services.term_merge_service import TermMergeConflict, TermMergeService
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver
from backend.app.services.markdown_parser import parse_markdown


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
    publisher = Publisher(
        repository,
        drafts,
        indexer,
        proposals,
        canonical_target_resolver=CanonicalTargetResolver(repository, connection),
    )
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
    result = publisher.publish(draft.id, expected_revision=draft.revision)

    assert (repository / target).read_text(encoding="utf-8") == content
    assert result.path == target
    assert result.commit_revision == git.current_revision()
    changed_paths = _git(repository, "show", "--pretty=format:", "--name-only", result.commit_revision)
    assert changed_paths.splitlines() == [target]
    assert "README.md" in git.status()


def test_term_merge_moves_aliases_relations_and_resolves_old_ids(publish_context):
    repository, connection, _, _, publisher = publish_context
    loser_id = "information-measure"
    loser_path = repository / "knowledge" / "terms" / "{}.md".format(loser_id)
    loser_path.write_text(
        _term(loser_id, "Information Measure", aliases=("IM",)), encoding="utf-8"
    )
    _git(repository, "add", str(loser_path.relative_to(repository)))
    _git(repository, "commit", "-m", "add merge test Term")

    note_path = repository / "knowledge" / "documents" / "papers" / "ewc-review.md"
    note_path.write_text(
        note_path.read_text(encoding="utf-8") + "\n[[information-measure]]\n",
        encoding="utf-8",
    )
    _git(repository, "add", str(note_path.relative_to(repository)))
    _git(repository, "commit", "-m", "link to merge test Term")

    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    candidate_repository = TermCandidateRepository(connection)
    open_candidate = TermCandidateRecord(
        id="open-candidate",
        normalized_name="a pending suggestion",
        display_name="A Pending Suggestion",
        suggested_type="concept",
        suggested_term_id=loser_id,
        status="pending",
        created_at="created",
        updated_at="updated",
    )
    candidate_repository.create_candidate(
        open_candidate,
        [
            TermCandidateEvidenceInput(
                origin_type="external", origin_id="ref-1", mention="A Pending Suggestion"
            )
        ],
    )
    accepted_candidate = TermCandidateRecord(
        id="accepted-candidate",
        normalized_name="an accepted suggestion",
        display_name="An Accepted Suggestion",
        suggested_type="concept",
        suggested_term_id=loser_id,
        accepted_term_id=loser_id,
        status="accepted",
        created_at="created",
        updated_at="updated",
    )
    candidate_repository.create_candidate(accepted_candidate, [])
    connection.executemany(
        """INSERT INTO term_entity_relations (
               id, entity_type, entity_id, term_id, created_from_candidate_id, created_at
           ) VALUES (?, 'document', 'ewc-review', ?, NULL, 'created')""",
        [("loser-relation", loser_id), ("survivor-relation", "fisher-information")],
    )
    connection.commit()

    service = TermMergeService(
        repository, connection, candidate_repository, publisher, indexer
    )
    preview = service.preview(
        "fisher-information", [loser_id], "Fisher Information"
    )
    assert preview.aliases == (
        "Fisher matrix",
        "Information Measure",
        "IM",
        "information-measure",
    )
    assert preview.loser_bodies_not_merged == (loser_id,)
    with pytest.raises(TermMergeConflict, match="Confirm that loser Term bodies"):
        service.merge("fisher-information", [loser_id], "Fisher Information")

    survivor_path = repository / "knowledge" / "terms" / "fisher-information.md"
    survivor_body_before = _markdown_body(survivor_path.read_text(encoding="utf-8"))
    result = service.merge(
        "fisher-information",
        [loser_id],
        "Fisher Information",
        confirm_loser_bodies_not_merged=True,
    )

    assert result.loser_term_ids == (loser_id,)
    assert result.warnings == ()
    assert not loser_path.exists()
    survivor_content = survivor_path.read_text(encoding="utf-8")
    assert _markdown_body(survivor_content) == survivor_body_before
    assert parse_markdown(survivor_content).frontmatter["aliases"] == list(preview.aliases)
    assert set(
        _git(
            repository,
            "show",
            "--pretty=format:",
            "--name-only",
            result.commit_revision,
        ).splitlines()
    ) == {
        "knowledge/terms/fisher-information.md",
        "knowledge/terms/information-measure.md",
    }
    assert TermResolver(TermRegistry.load(repository / "knowledge" / "terms")).resolve(
        loser_id
    ).entity_id == "fisher-information"
    assert KnowledgeReadService(repository, connection).get_entity("term", loser_id)[
        "id"
    ] == "fisher-information"
    merged_term = KnowledgeReadService(repository, connection).get_entity(
        "term", "fisher-information"
    )
    assert any(
        link["source_entity_id"] == "ewc-review"
        and link["link_target"] == loser_id
        for link in merged_term["backlinks"]
    )
    assert len(merged_term["term_relations"]) == 1
    assert [
        tuple(row)
        for row in connection.execute(
            "SELECT entity_type, entity_id, term_id FROM term_entity_relations"
        ).fetchall()
    ] == [("document", "ewc-review", "fisher-information")]
    assert connection.execute(
        "SELECT suggested_term_id FROM term_candidates WHERE id = 'open-candidate'"
    ).fetchone()[0] == "fisher-information"
    assert connection.execute(
        "SELECT accepted_term_id FROM term_candidates WHERE id = 'accepted-candidate'"
    ).fetchone()[0] == "fisher-information"
    assert tuple(
        connection.execute(
            "SELECT loser_term_id, survivor_term_id FROM term_merge_history"
        ).fetchone()
    ) == (loser_id, "fisher-information")


def test_term_merge_preserves_old_title_and_requires_selected_metadata(publish_context):
    repository, connection, _, _, publisher = publish_context
    terms_dir = repository / "knowledge" / "terms"
    survivor_id = "state-of-the-art"
    loser_id = "sota-method"
    survivor_path = terms_dir / "{}.md".format(survivor_id)
    loser_path = terms_dir / "{}.md".format(loser_id)
    survivor_path.write_text(
        _term(survivor_id, "State of the Art"), encoding="utf-8"
    )
    loser_path.write_text(
        _term(loser_id, "State of the Art Method")
        .replace("type: concept", "type: vocabulary")
        .replace("depth: standard", "depth: stub"),
        encoding="utf-8",
    )
    _git(repository, "add", str(survivor_path.relative_to(repository)), str(loser_path.relative_to(repository)))
    _git(repository, "commit", "-m", "add metadata conflict Terms")

    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    service = TermMergeService(
        repository,
        connection,
        TermCandidateRepository(connection),
        publisher,
        indexer,
    )
    final_title = "state-of-the-art"
    preview = service.preview(survivor_id, [loser_id], final_title)

    assert "State of the Art" in preview.aliases
    assert preview.type_conflict is True
    assert preview.depth_conflict is True
    assert [
        (term.id, term.title, term.type, term.depth)
        for term in preview.selected_terms
    ] == [
        (survivor_id, "State of the Art", "concept", "standard"),
        (loser_id, "State of the Art Method", "vocabulary", "stub"),
    ]
    with pytest.raises(TermMergeConflict, match="Select a final Term type"):
        service.merge(
            survivor_id,
            [loser_id],
            final_title,
            confirm_loser_bodies_not_merged=True,
        )

    result = service.merge(
        survivor_id,
        [loser_id],
        final_title,
        confirm_loser_bodies_not_merged=True,
        final_type="vocabulary",
        final_depth="stub",
    )
    metadata = parse_markdown(survivor_path.read_text(encoding="utf-8")).frontmatter
    assert metadata["title"] == final_title
    assert "State of the Art" in metadata["aliases"]
    assert metadata["type"] == "vocabulary"
    assert metadata["depth"] == "stub"
    assert result.type_conflict is True
    assert result.depth_conflict is True
    resolved = TermResolver(TermRegistry.load(terms_dir)).resolve("State of the Art")
    assert resolved.status == "resolved"
    assert resolved.entity_id == survivor_id


def test_term_merge_git_failure_rolls_back_runtime_migration_and_canonical_files(
    publish_context, monkeypatch
):
    repository, connection, _, _, publisher = publish_context
    loser_id = "information-measure"
    loser_path = repository / "knowledge" / "terms" / "{}.md".format(loser_id)
    loser_path.write_text(
        _term(loser_id, "Information Measure", aliases=("IM",)), encoding="utf-8"
    )
    _git(repository, "add", str(loser_path.relative_to(repository)))
    _git(repository, "commit", "-m", "add merge failure Term")
    indexer = Indexer(repository, connection)
    indexer.full_rebuild()
    candidate_repository = TermCandidateRepository(connection)
    candidate = TermCandidateRecord(
        id="pending-candidate",
        normalized_name="pending suggestion",
        display_name="Pending Suggestion",
        suggested_type="concept",
        suggested_term_id=loser_id,
        status="pending",
        created_at="created",
        updated_at="updated",
    )
    candidate_repository.create_candidate(candidate, [])
    connection.commit()
    survivor_path = repository / "knowledge" / "terms" / "fisher-information.md"
    survivor_before = survivor_path.read_bytes()
    loser_before = loser_path.read_bytes()
    revision_before = publisher.git.current_revision()
    service = TermMergeService(
        repository, connection, candidate_repository, publisher, indexer
    )

    def fail_commit(*args, **kwargs):
        from backend.app.services.git_manager import GitOperationError

        raise GitOperationError("forced Term merge commit failure")

    monkeypatch.setattr(publisher.git, "commit_many", fail_commit)
    with pytest.raises(GitOperationError, match="forced Term merge commit failure"):
        service.merge(
            "fisher-information",
            [loser_id],
            "Fisher Information",
            confirm_loser_bodies_not_merged=True,
        )

    assert survivor_path.read_bytes() == survivor_before
    assert loser_path.read_bytes() == loser_before
    assert publisher.git.current_revision() == revision_before
    assert connection.execute(
        "SELECT suggested_term_id FROM term_candidates WHERE id = 'pending-candidate'"
    ).fetchone()[0] == loser_id
    assert connection.execute("SELECT COUNT(*) FROM term_merge_history").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM term_entity_relations WHERE term_id = ?", (loser_id,)
    ).fetchone()[0] == 0


def test_preflight_validates_draft_without_writing_canonical_content(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/preflight-note.md"
    draft = _create_draft(
        drafts, git, "document", "preflight-note", _document("preflight-note"), target
    )

    result = publisher.preflight(draft.id)

    assert result.valid is True
    assert result.conflict is False
    assert result.errors == ()
    assert not (repository / target).exists()
    assert git.status() == ""


def test_preflight_reports_validation_errors_and_canonical_conflicts(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/preflight-invalid.md"
    content = _document("preflight-invalid").replace("continual-learning", "missing-topic")
    draft = _create_draft(drafts, git, "document", "preflight-invalid", content, target)
    invalid = publisher.preflight(draft.id)
    assert invalid.valid is False
    assert invalid.conflict is False
    assert invalid.errors

    (repository / target).write_text(_document("preflight-invalid"), encoding="utf-8")
    conflict = publisher.preflight(draft.id)
    assert conflict.valid is False
    assert conflict.conflict is True
    assert conflict.errors


def test_publish_collection_and_remove_successful_draft(publish_context):
    repository, connection, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/collections/reading.yaml"
    content = _collection("reading", "Reading")
    draft = _create_draft(drafts, git, "collection", "reading", content, target)

    result = publisher.publish(draft.id, expected_revision=draft.revision)

    assert result.entity_type == "collection"
    assert (repository / target).read_text(encoding="utf-8") == content
    assert result.commit_revision == git.current_revision()
    assert drafts.list_for_target("collection", "reading") == []
    assert connection.execute(
        "SELECT title FROM collection_index WHERE collection_id = ?", ("reading",)
    ).fetchone()["title"] == "Reading"


def test_publish_rejects_changed_draft_revision_without_writing_or_committing(
    publish_context,
):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/reviewed-note.md"
    content = _document("reviewed-note", title="Reviewed Note")
    draft = _create_draft(drafts, git, "document", "reviewed-note", content, target)
    drafts.save(
        draft.id,
        _document("reviewed-note", title="Changed After Review"),
        expected_revision=draft.revision,
    )
    current_commit = git.current_revision()

    with pytest.raises(
        PublishConflictError,
        match="Draft changed after review. Refresh the Publish Review before publishing.",
    ):
        publisher.publish(draft.id, expected_revision=draft.revision)

    assert not (repository / target).exists()
    assert git.current_revision() == current_commit
    assert drafts.get(draft.id).revision == draft.revision + 1


def test_publish_requires_the_reviewed_revision(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    draft = _create_draft(
        drafts,
        git,
        "document",
        "revision-required",
        _document("revision-required"),
        "knowledge/documents/learning/revision-required.md",
    )

    with pytest.raises(TypeError, match="expected_revision"):
        publisher.publish(draft.id)


def test_publish_rejects_repository_duplicate_ids_and_rolls_back_candidate(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    duplicate_content = _document("duplicate-note", title="Duplicate Note")
    first = repository / "knowledge/documents/learning/duplicate-note.md"
    second = repository / "knowledge/documents/courses/duplicate-note.md"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_text(duplicate_content, encoding="utf-8")
    second.write_text(duplicate_content, encoding="utf-8")

    target = "knowledge/documents/learning/publish-target.md"
    draft = _create_draft(
        drafts,
        git,
        "document",
        "publish-target",
        _document("publish-target", title="Publish Target"),
        target,
    )
    current_commit = git.current_revision()

    with pytest.raises(PublishValidationError, match="Duplicate Document id 'duplicate-note'"):
        publisher.publish(draft.id, expected_revision=draft.revision)

    assert not (repository / target).exists()
    assert git.current_revision() == current_commit
    assert drafts.get(draft.id).revision == draft.revision


def test_batch_publish_rejects_any_changed_reviewed_revision_atomically(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    document_path = "knowledge/documents/learning/reviewed-batch-note.md"
    collection_path = "knowledge/collections/reviewed-batch.yaml"
    document = _create_draft(
        drafts,
        git,
        "document",
        "reviewed-batch-note",
        _document("reviewed-batch-note", title="Reviewed Batch Note"),
        document_path,
    )
    collection = _create_draft(
        drafts,
        git,
        "collection",
        "reviewed-batch",
        _collection("reviewed-batch", "Reviewed Batch"),
        collection_path,
    )
    drafts.save(
        collection.id,
        _collection("reviewed-batch", "Changed After Review"),
        expected_revision=collection.revision,
    )
    current_commit = git.current_revision()

    with pytest.raises(
        PublishConflictError,
        match="Draft changed after review. Refresh the Publish Review before publishing.",
    ):
        publisher.publish_batch(
            [(document.id, document.revision), (collection.id, collection.revision)],
        )

    assert not (repository / document_path).exists()
    assert not (repository / collection_path).exists()
    assert git.current_revision() == current_commit
    assert drafts.get(document.id).revision == document.revision
    assert drafts.get(collection.id).revision == collection.revision + 1


def test_batch_publish_requires_unique_draft_revision_pairs(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    draft = _create_draft(
        drafts,
        git,
        "document",
        "batch-revision-required",
        _document("batch-revision-required"),
        "knowledge/documents/learning/batch-revision-required.md",
    )

    with pytest.raises(PublishValidationError, match="Draft id and its reviewed revision"):
        publisher.publish_batch([draft.id])
    with pytest.raises(PublishValidationError, match="positive integers"):
        publisher.publish_batch([(draft.id, 0)])
    with pytest.raises(PublishValidationError, match="must be unique"):
        publisher.publish_batch([(draft.id, draft.revision), (draft.id, draft.revision)])


def test_publish_collection_metadata_and_reorder_updates_the_derived_order(publish_context):
    repository, connection, drafts, _, publisher = publish_context
    git = GitManager(repository)
    alpha_path = "knowledge/collections/alpha.yaml"
    beta_path = "knowledge/collections/beta.yaml"
    alpha_initial = _collection("alpha", "Alpha")
    beta_initial = _collection("beta", "Beta").replace("position: 0", "position: 1")

    alpha_draft = _create_draft(
        drafts, git, "collection", "alpha", alpha_initial, alpha_path
    )
    publisher.publish(alpha_draft.id, expected_revision=alpha_draft.revision)
    beta_draft = _create_draft(
        drafts, git, "collection", "beta", beta_initial, beta_path
    )
    publisher.publish(beta_draft.id, expected_revision=beta_draft.revision)

    alpha_updated = _collection("alpha", "Alpha Updated").replace(
        "status: active\nposition: 0",
        "description: Refined learning path\nstatus: active\nposition: 1",
    )
    beta_reordered = _collection("beta", "Beta")
    alpha_update_draft = _create_draft(
        drafts, git, "collection", "alpha", alpha_updated, alpha_path
    )
    beta_reorder_draft = _create_draft(
        drafts, git, "collection", "beta", beta_reordered, beta_path
    )

    result = publisher.publish_batch(
        [
            (alpha_update_draft.id, alpha_update_draft.revision),
            (beta_reorder_draft.id, beta_reorder_draft.revision),
        ],
        "kb: update and reorder collections",
    )

    assert (repository / alpha_path).read_text(encoding="utf-8") == alpha_updated
    assert (repository / beta_path).read_text(encoding="utf-8") == beta_reordered
    assert result.commit_revision == git.current_revision()
    ordered = connection.execute(
        "SELECT collection_id, title, position FROM collection_index ORDER BY position, collection_id"
    ).fetchall()
    assert [(row["collection_id"], row["title"], row["position"]) for row in ordered] == [
        ("beta", "Beta", 0),
        ("alpha", "Alpha Updated", 1),
    ]


def test_publish_batch_commits_document_and_collection_together(publish_context):
    repository, connection, drafts, _, publisher = publish_context
    git = GitManager(repository)
    document_path = "knowledge/documents/learning/batch-note.md"
    collection_path = "knowledge/collections/batch-reading.yaml"
    document_content = _document("batch-note", title="Batch Note")
    collection_content = _collection(
        "batch-reading",
        "Batch Reading",
        "  - id: batch-note\n    kind: entity\n    entity_type: document\n    entity_id: batch-note\n",
    )
    document_draft = _create_draft(
        drafts, git, "document", "batch-note", document_content, document_path
    )
    collection_draft = _create_draft(
        drafts, git, "collection", "batch-reading", collection_content, collection_path
    )
    base_revision = git.current_revision()

    result = publisher.publish_batch(
        [
            (document_draft.id, document_draft.revision),
            (collection_draft.id, collection_draft.revision),
        ],
        "kb: publish reading workspace",
    )

    assert result.commit_revision == git.current_revision()
    assert [item.draft_id for item in result.results] == [
        document_draft.id,
        collection_draft.id,
    ]
    assert all(item.commit_revision == result.commit_revision for item in result.results)
    changed_paths = _git(
        repository, "show", "--pretty=format:", "--name-only", result.commit_revision
    ).splitlines()
    assert set(changed_paths) == {document_path, collection_path}
    assert (repository / document_path).read_text(encoding="utf-8") == document_content
    assert (repository / collection_path).read_text(encoding="utf-8") == collection_content
    assert git.current_revision() != base_revision
    assert drafts.list_for_target("document", "batch-note") == []
    assert drafts.list_for_target("collection", "batch-reading") == []
    assert connection.execute(
        "SELECT entity_id FROM collection_node_index WHERE collection_id = ?",
        ("batch-reading",),
    ).fetchone()["entity_id"] == "batch-note"


def test_preflight_batch_accepts_collection_reference_to_new_document(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    document_content = _document("preflight-batch-note", title="Batch Note")
    collection_content = _collection(
        "preflight-batch-reading",
        "Batch Reading",
        "  - id: preflight-batch-note\n    kind: entity\n    entity_type: document\n    entity_id: preflight-batch-note\n",
    )
    document_draft = _create_draft(
        drafts,
        git,
        "document",
        "preflight-batch-note",
        document_content,
        "knowledge/documents/learning/preflight-batch-note.md",
    )
    collection_draft = _create_draft(
        drafts,
        git,
        "collection",
        "preflight-batch-reading",
        collection_content,
        "knowledge/collections/preflight-batch-reading.yaml",
    )
    head = git.current_revision()

    results = publisher.preflight_batch(
        [
            (document_draft.id, document_draft.revision),
            (collection_draft.id, collection_draft.revision),
        ]
    )

    assert [result.valid for result in results] == [True, True]
    assert all(not result.conflict and not result.errors for result in results)
    assert git.current_revision() == head
    assert git.status() == ""
    assert not (repository / "knowledge/documents/learning/preflight-batch-note.md").exists()
    assert not (repository / "knowledge/collections/preflight-batch-reading.yaml").exists()


def test_preflight_and_publish_accept_source_document_collection_batch(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    source_path = "knowledge/sources/preflight-new-source.yaml"
    document_path = "knowledge/documents/learning/preflight-source-note.md"
    collection_path = "knowledge/collections/preflight-source-reading.yaml"
    source_content = (
        "schema_version: 1\nid: preflight-new-source\ntype: web\n"
        "title: A New Batch Source\nurl: https://example.com/new-source\n"
    )
    document_content = _document("preflight-source-note").replace(
        "ewc-2017", "preflight-new-source"
    )
    collection_content = _collection(
        "preflight-source-reading",
        "Preflight Source Reading",
        "  - id: preflight-source-note\n    kind: entity\n"
        "    entity_type: document\n    entity_id: preflight-source-note\n",
    )
    source_draft = _create_draft(
        drafts,
        git,
        "source",
        "preflight-new-source",
        source_content,
        source_path,
    )
    document_draft = _create_draft(
        drafts,
        git,
        "document",
        "preflight-source-note",
        document_content,
        document_path,
    )
    collection_draft = _create_draft(
        drafts,
        git,
        "collection",
        "preflight-source-reading",
        collection_content,
        collection_path,
    )
    reviewed = [
        (source_draft.id, source_draft.revision),
        (document_draft.id, document_draft.revision),
        (collection_draft.id, collection_draft.revision),
    ]
    base_revision = git.current_revision()

    preflight = publisher.preflight_batch(reviewed)

    assert [result.valid for result in preflight] == [True, True, True]
    assert all(not result.conflict and not result.errors for result in preflight)
    assert git.current_revision() == base_revision
    assert git.status() == ""
    assert not (repository / source_path).exists()
    assert not (repository / document_path).exists()
    assert not (repository / collection_path).exists()

    published = publisher.publish_batch(reviewed)

    changed_paths = _git(
        repository, "show", "--pretty=format:", "--name-only", published.commit_revision
    ).splitlines()
    assert set(changed_paths) == {source_path, document_path, collection_path}
    assert all((repository / path).is_file() for path in changed_paths)
    assert published.commit_revision == git.current_revision()


def test_preflight_batch_rejects_unknown_source_reference(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    draft = _create_draft(
        drafts,
        git,
        "document",
        "preflight-unknown-source",
        _document("preflight-unknown-source").replace("ewc-2017", "missing-source"),
        "knowledge/documents/learning/preflight-unknown-source.md",
    )

    result = publisher.preflight_batch([(draft.id, draft.revision)])[0]

    assert result.valid is False
    assert result.conflict is False
    assert "Unknown Source id(s): missing-source" in " ".join(result.errors)
    assert not (repository / "knowledge/documents/learning/preflight-unknown-source.md").exists()


def test_preflight_batch_rejects_invalid_source_draft_and_dependent_document(
    publish_context,
):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    source_draft = _create_draft(
        drafts,
        git,
        "source",
        "preflight-invalid-source",
        "schema_version: 2\nid: preflight-invalid-source\ntype: web\n"
        "title: Invalid Source\nurl: https://example.com/invalid-source\n",
        "knowledge/sources/preflight-invalid-source.yaml",
    )
    document_draft = _create_draft(
        drafts,
        git,
        "document",
        "preflight-source-dependent-note",
        _document("preflight-source-dependent-note").replace(
            "ewc-2017", "preflight-invalid-source"
        ),
        "knowledge/documents/learning/preflight-source-dependent-note.md",
    )

    results = publisher.preflight_batch(
        [
            (source_draft.id, source_draft.revision),
            (document_draft.id, document_draft.revision),
        ]
    )

    assert [result.valid for result in results] == [False, False]
    assert "schema_version" in " ".join(results[0].errors)
    assert "Unknown Source id(s): preflight-invalid-source" in " ".join(
        results[1].errors
    )
    assert not (
        repository / "knowledge/sources/preflight-invalid-source.yaml"
    ).exists()


def test_preflight_batch_rejects_unknown_document_reference(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    collection_draft = _create_draft(
        drafts,
        git,
        "collection",
        "preflight-batch-invalid",
        _collection(
            "preflight-batch-invalid",
            "Invalid Batch",
            "  - id: missing-note\n    kind: entity\n    entity_type: document\n    entity_id: missing-note\n",
        ),
        "knowledge/collections/preflight-batch-invalid.yaml",
    )

    result = publisher.preflight_batch([(collection_draft.id, collection_draft.revision)])[0]

    assert result.valid is False
    assert result.conflict is False
    assert "Unknown document entity 'missing-note'" in " ".join(result.errors)
    assert not (repository / "knowledge/collections/preflight-batch-invalid.yaml").exists()


def test_preflight_batch_reports_stale_review_revision_as_conflict(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    draft = _create_draft(
        drafts,
        git,
        "document",
        "preflight-stale-review",
        _document("preflight-stale-review"),
        "knowledge/documents/learning/preflight-stale-review.md",
    )
    drafts.save(
        draft.id,
        _document("preflight-stale-review", title="Changed after review"),
        expected_revision=draft.revision,
    )

    result = publisher.preflight_batch([(draft.id, draft.revision)])[0]

    assert result.valid is False
    assert result.conflict is True
    assert "expected revision 1, current revision 2" in " ".join(result.errors)


def test_batch_preparation_preserves_no_op_preflight_and_publish_errors(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/papers/ewc-review.md"
    content = (repository / target).read_bytes().decode("utf-8")
    draft = _create_draft(drafts, git, "document", "ewc-review", content, target)
    current_revision = git.current_revision()

    result = publisher.preflight_batch([(draft.id, draft.revision)])[0]

    assert result.valid is False
    assert result.conflict is False
    assert result.errors == ("Draft has no canonical changes to publish",)
    with pytest.raises(PublishError, match="Draft .* has no canonical changes to publish"):
        publisher.publish_batch([(draft.id, draft.revision)])
    assert git.current_revision() == current_revision
    assert drafts.get(draft.id).revision == draft.revision


def test_publish_batch_validation_failure_restores_all_files_and_keeps_drafts(
    publish_context,
):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    document_path = "knowledge/documents/learning/batch-invalid-note.md"
    collection_path = "knowledge/collections/batch-invalid.yaml"
    document_draft = _create_draft(
        drafts,
        git,
        "document",
        "batch-invalid-note",
        _document("batch-invalid-note"),
        document_path,
    )
    collection_draft = _create_draft(
        drafts,
        git,
        "collection",
        "batch-invalid",
        _collection(
            "batch-invalid",
            "Invalid Batch",
            "  - id: missing-note\n    kind: entity\n    entity_type: document\n    entity_id: missing-note\n",
        ),
        collection_path,
    )
    head = git.current_revision()

    with pytest.raises(PublishValidationError, match="Unknown document entity 'missing-note'"):
        publisher.publish_batch([
            (document_draft.id, document_draft.revision),
            (collection_draft.id, collection_draft.revision),
        ])

    assert not (repository / document_path).exists()
    assert not (repository / collection_path).exists()
    assert git.current_revision() == head
    assert git.status() == ""
    assert drafts.get(document_draft.id) == document_draft
    assert drafts.get(collection_draft.id) == collection_draft


def test_publish_batch_commit_failure_restores_all_files_and_keeps_drafts(
    publish_context, monkeypatch
):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    document_path = "knowledge/documents/learning/commit-failure-note.md"
    collection_path = "knowledge/collections/commit-failure.yaml"
    document_draft = _create_draft(
        drafts,
        git,
        "document",
        "commit-failure-note",
        _document("commit-failure-note"),
        document_path,
    )
    collection_draft = _create_draft(
        drafts,
        git,
        "collection",
        "commit-failure",
        _collection(
            "commit-failure",
            "Commit Failure",
            "  - id: commit-note\n    kind: entity\n    entity_type: document\n    entity_id: commit-failure-note\n",
        ),
        collection_path,
    )

    def fail_commit(paths, message):
        raise GitOperationError("forced commit failure")

    monkeypatch.setattr(publisher.git, "commit_many", fail_commit)
    with pytest.raises(GitOperationError, match="forced commit failure"):
        publisher.publish_batch([
            (document_draft.id, document_draft.revision),
            (collection_draft.id, collection_draft.revision),
        ])

    assert not (repository / document_path).exists()
    assert not (repository / collection_path).exists()
    assert git.status() == ""
    assert drafts.get(document_draft.id) == document_draft
    assert drafts.get(collection_draft.id) == collection_draft


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
    result = publisher.publish(draft.id, expected_revision=draft.revision)

    assert (repository / target).is_file()
    assert result.commit_revision == git.current_revision()


def test_other_document_publish_does_not_conflict_with_existing_draft(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    first_path = "knowledge/documents/learning/first-note.md"
    second_path = "knowledge/documents/learning/second-note.md"
    first = _create_draft(drafts, git, "document", "first-note", _document("first-note"), first_path)
    second = _create_draft(drafts, git, "document", "second-note", _document("second-note"), second_path)

    publisher.publish(second.id, expected_revision=second.revision)
    result = publisher.publish(first.id, expected_revision=first.revision)

    assert result.entity_id == "first-note"
    assert (repository / first_path).is_file()


def test_publish_rejects_changed_target_content_without_overwriting(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/papers/ewc-review.md"
    original = (repository / target).read_bytes()
    content = original.decode("utf-8").replace(
        "title: Overcoming Catastrophic Forgetting in Neural Networks",
        "title: Edited title",
        1,
    )
    draft = _create_draft(drafts, git, "document", "ewc-review", content, target)
    (repository / target).write_text("external unstaged edit\n", encoding="utf-8")

    with pytest.raises(PublishConflictError, match="Canonical file changed"):
        publisher.publish(draft.id, expected_revision=draft.revision)

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
        publisher.publish(draft.id, expected_revision=draft.revision)


def test_deleting_target_conflicts_with_existing_file_base(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/papers/ewc-review.md"
    draft = _create_draft(
        drafts,
        git,
        "document",
        "ewc-review",
        (repository / target).read_text(encoding="utf-8"),
        target,
    )
    (repository / target).unlink()

    with pytest.raises(PublishConflictError, match="Canonical file changed"):
        publisher.publish(draft.id, expected_revision=draft.revision)


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
        publisher.publish(draft.id, expected_revision=draft.revision)

    assert not (repository / target).exists()
    assert git.current_revision() == head


def test_current_document_style_issues_still_block_publish(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/current-style.md"
    content = _document("current-style") + "\n## Unnumbered section\n"
    draft = _create_draft(drafts, git, "document", "current-style", content, target)

    with pytest.raises(PublishValidationError, match="heading.h2_numbering"):
        publisher.publish(draft.id, expected_revision=draft.revision)
    assert not (repository / target).exists()


def test_legacy_document_style_issues_publish_with_warnings(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/legacy-style.md"
    content = _document("legacy-style").replace(
        "schema_version: 1", "schema_version: 1\nmaintenance:\n  status: legacy", 1
    ) + "\n## Old section numbering\n"
    draft = _create_draft(drafts, git, "document", "legacy-style", content, target)

    result = publisher.publish(draft.id, expected_revision=draft.revision)

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
        publisher.publish(draft.id, expected_revision=draft.revision)
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

    result = publisher.publish(draft.id, expected_revision=draft.revision)
    assert (repository / target).is_file()
    assert result.commit_revision == git.current_revision()
    assert any("run `python tools/kb.py rebuild`" in warning for warning in result.warnings)


def test_applied_proposal_is_published_through_its_draft(publish_context):
    repository, _, drafts, proposals, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/proposed-note.md"
    base = _document("proposed-note", title="Before")
    content = _document("proposed-note", title="Candidate Content")
    draft = _create_draft(
        drafts, git, "document", "proposed-note", base, target
    )
    proposal = proposals.create(
        "document",
        "proposed-note",
        "document_revision",
        hashlib.sha256(base.encode("utf-8")).hexdigest(),
        {"draft_id": draft.id, "content": content},
        "ai",
    )
    _, applied = proposals.apply_to_draft(proposal.id, draft, draft.revision)

    result = publisher.publish(applied.id, expected_revision=applied.revision)

    assert (repository / target).read_text(encoding="utf-8") == content
    assert proposals.get(proposal.id).status == "merged"
    assert result.commit_revision == git.current_revision()


def test_proposal_survives_unrelated_document_publish(publish_context):
    repository, _, drafts, proposals, publisher = publish_context
    git = GitManager(repository)
    proposal_target = "knowledge/documents/learning/proposal-target.md"
    other_target = "knowledge/documents/learning/other-target.md"
    proposal_content = _document("proposal-target", title="Proposed Content")
    proposal_base = _document("proposal-target", title="Before")
    proposal_draft = _create_draft(
        drafts, git, "document", "proposal-target", proposal_base, proposal_target
    )
    proposal = proposals.create(
        "document",
        "proposal-target",
        "document_revision",
        hashlib.sha256(proposal_base.encode("utf-8")).hexdigest(),
        {"draft_id": proposal_draft.id, "content": proposal_content},
        "ai",
    )
    _, proposal_draft = proposals.apply_to_draft(proposal.id, proposal_draft, 1)
    other_draft = _create_draft(
        drafts, git, "document", "other-target", _document("other-target"), other_target
    )

    publisher.publish(other_draft.id, expected_revision=other_draft.revision)
    result = publisher.publish(proposal_draft.id, expected_revision=proposal_draft.revision)

    assert result.entity_id == "proposal-target"
    assert proposals.get(proposal.id).status == "merged"


def test_proposal_status_failure_is_reported_as_post_publish_warning(
    publish_context, monkeypatch
):
    repository, _, drafts, proposals, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/proposal-warning.md"
    base = _document("proposal-warning", title="Before")
    content = _document("proposal-warning", title="Published Content")
    draft = _create_draft(
        drafts, git, "document", "proposal-warning", base, target
    )
    proposal = proposals.create(
        "document",
        "proposal-warning",
        "document_revision",
        hashlib.sha256(base.encode("utf-8")).hexdigest(),
        {"draft_id": draft.id, "content": content},
        "ai",
    )
    _, applied = proposals.apply_to_draft(proposal.id, draft, draft.revision)

    def fail_finalize(*_args, **_kwargs):
        raise RuntimeError("runtime database unavailable")

    monkeypatch.setattr(proposals, "finalize_draft_publish", fail_finalize)
    result = publisher.publish(applied.id, expected_revision=applied.revision)

    assert result.commit_revision == git.current_revision()
    assert (repository / target).read_text(encoding="utf-8") == content
    assert proposals.get(proposal.id).status == "drafted"
    assert any("Proposal status update failed" in warning for warning in result.warnings)


def test_proposal_becomes_stale_when_its_draft_changes_before_publish(publish_context):
    repository, _, drafts, proposals, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/changed-draft.md"
    initial_content = _document("changed-draft", title="Before")
    initial_draft = _create_draft(
        drafts, git, "document", "changed-draft", initial_content, target
    )
    proposal_hash = hashlib.sha256(initial_content.encode("utf-8")).hexdigest()
    proposal = proposals.create(
        "document",
        "changed-draft",
        "document_revision",
        proposal_hash,
        {"draft_id": initial_draft.id, "content": _document("changed-draft", title="Proposed Content")},
        "ai",
    )
    _, applied = proposals.apply_to_draft(proposal.id, initial_draft, 1)
    edited = drafts.save(
        applied.id,
        _document("changed-draft", title="Manual Edit"),
        expected_revision=applied.revision,
    )

    publisher.publish(edited.id, expected_revision=edited.revision)

    assert (repository / target).read_text(encoding="utf-8") == edited.content
    assert proposals.get(proposal.id).status == "stale"


@pytest.mark.parametrize(
    ("edit_after_apply", "expected_status"),
    [(False, "merged"), (True, "stale")],
)
def test_applied_proposal_closes_when_its_draft_is_published(
    publish_context, edit_after_apply, expected_status
):
    repository, _, drafts, proposals, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/applied-proposal.md"
    base = _document("applied-proposal", title="Before")
    candidate = _document("applied-proposal", title="Candidate")
    draft = _create_draft(
        drafts, git, "document", "applied-proposal", base, target
    )
    proposal = proposals.create(
        "document",
        "applied-proposal",
        "document_revision",
        hashlib.sha256(base.encode("utf-8")).hexdigest(),
        {"draft_id": draft.id, "content": candidate},
        "ai",
    )
    _, applied_draft = proposals.apply_to_draft(proposal.id, draft, 1)

    if edit_after_apply:
        applied_draft = drafts.save(
            applied_draft.id,
            _document("applied-proposal", title="Manual Edit"),
            expected_revision=applied_draft.revision,
        )
    publisher.publish(applied_draft.id, expected_revision=applied_draft.revision)

    assert proposals.get(proposal.id).status == expected_status


def test_restore_creates_a_new_commit_and_preserves_published_history(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/terms/fisher-information.md"
    before_revision = git.current_revision()
    before_content = (repository / target).read_bytes()
    updated = _term("fisher-information", title="Updated Fisher Information")
    draft = _create_draft(drafts, git, "term", "fisher-information", updated, target)

    published = publisher.publish(draft.id, expected_revision=draft.revision)
    restore_result = publisher.restore(target, before_revision)

    assert restore_result.commit_revision != published.commit_revision
    assert (repository / target).read_bytes() == before_content
    _git(repository, "cat-file", "-e", published.commit_revision)
    assert _git(repository, "show", "-s", "--format=%s", restore_result.commit_revision).startswith("restore:")
    with pytest.raises(GitOperationError):
        publisher.restore(target, "0" * 40)
    assert git.current_revision() == restore_result.commit_revision


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
    published = publisher.publish(draft.id, expected_revision=draft.revision)

    restored = publisher.restore(target, before_creation)

    assert restored.commit_revision != published.commit_revision
    assert not (repository / target).exists()
    assert _git(repository, "show", "-s", "--format=%s", restored.commit_revision).startswith("restore:")
    _git(repository, "cat-file", "-e", published.commit_revision)

    restored_again = publisher.restore(target, published.commit_revision)

    assert (repository / target).is_file()
    assert restored_again.commit_revision != restored.commit_revision
    assert _git(repository, "show", "-s", "--format=%s", restored_again.commit_revision).startswith("restore:")


def test_restore_rejects_deleting_a_referenced_document(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    before_creation = git.current_revision()
    document_path = "knowledge/documents/learning/restore-referenced-document.md"
    collection_path = "knowledge/collections/restore-document-path.yaml"
    document_content = _document("restore-referenced-document")
    document_draft = _create_draft(
        drafts,
        git,
        "document",
        "restore-referenced-document",
        document_content,
        document_path,
    )
    collection_draft = _create_draft(
        drafts,
        git,
        "collection",
        "restore-document-path",
        _collection(
            "restore-document-path",
            "Restore Document Path",
            "  - id: referenced-document\n    kind: entity\n    entity_type: document\n    entity_id: restore-referenced-document\n",
        ),
        collection_path,
    )
    publisher.publish_batch(
        [
            (document_draft.id, document_draft.revision),
            (collection_draft.id, collection_draft.revision),
        ]
    )
    head = git.current_revision()

    with pytest.raises(
        PublishValidationError,
        match="Unknown document entity 'restore-referenced-document'",
    ):
        publisher.restore(document_path, before_creation)

    assert (repository / document_path).read_text(encoding="utf-8") == document_content
    assert git.current_revision() == head
    assert git.status() == ""


def test_restore_rejects_deleting_a_term_referenced_by_a_collection(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    before_creation = git.current_revision()
    term_path = "knowledge/terms/restore-referenced-term.md"
    collection_path = "knowledge/collections/restore-term-path.yaml"
    term_content = _term("restore-referenced-term", title="Restore Referenced Term")
    term_draft = _create_draft(
        drafts, git, "term", "restore-referenced-term", term_content, term_path
    )
    collection_draft = _create_draft(
        drafts,
        git,
        "collection",
        "restore-term-path",
        _collection(
            "restore-term-path",
            "Restore Term Path",
            "  - id: referenced-term\n    kind: entity\n    entity_type: term\n    entity_id: restore-referenced-term\n",
        ),
        collection_path,
    )
    publisher.publish_batch(
        [
            (term_draft.id, term_draft.revision),
            (collection_draft.id, collection_draft.revision),
        ]
    )
    head = git.current_revision()

    with pytest.raises(
        PublishValidationError,
        match="Unknown term entity 'restore-referenced-term'",
    ):
        publisher.restore(term_path, before_creation)

    assert (repository / term_path).read_text(encoding="utf-8") == term_content
    assert git.current_revision() == head
    assert git.status() == ""


def test_restore_rejects_historical_term_alias_that_ambiguates_existing_wiki_link(
    publish_context,
):
    repository, _, _, _, publisher = publish_context
    git = GitManager(repository)
    term_a_path = repository / "knowledge" / "terms" / "restore-term-a.md"
    term_b_path = repository / "knowledge" / "terms" / "restore-term-b.md"
    document_path = repository / "knowledge" / "documents" / "learning" / "restore-alias-link.md"
    shared_alias = "shared-restore-alias"

    term_a_path.write_text(
        _term("restore-term-a", title="Restore Term A", aliases=(shared_alias,)),
        encoding="utf-8",
    )
    term_b_path.write_text(
        _term("restore-term-b", title="Restore Term B", aliases=(shared_alias,)),
        encoding="utf-8",
    )
    document_path.write_text(
        _document("restore-alias-link", body="See [[{}]].\n".format(shared_alias)),
        encoding="utf-8",
    )
    _git(
        repository,
        "add",
        "knowledge/terms/restore-term-a.md",
        "knowledge/terms/restore-term-b.md",
        "knowledge/documents/learning/restore-alias-link.md",
    )
    _git(repository, "commit", "-m", "record historical ambiguous alias")
    historical_revision = git.current_revision()
    current_content = _term("restore-term-a", title="Restore Term A")
    term_a_path.write_text(current_content, encoding="utf-8")
    _git(repository, "add", "knowledge/terms/restore-term-a.md")
    _git(repository, "commit", "-m", "remove duplicate alias")
    head = git.current_revision()

    with pytest.raises(PublishValidationError, match="Ambiguous wiki link 'shared-restore-alias'"):
        publisher.restore(term_a_path, historical_revision)

    assert term_a_path.read_text(encoding="utf-8") == current_content
    assert git.current_revision() == head
    assert git.status() == ""


def test_restore_accepts_a_safe_historical_document(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/restore-safe-document.md"
    historical_content = _document("restore-safe-document", title="Historical Document")
    historical_draft = _create_draft(
        drafts, git, "document", "restore-safe-document", historical_content, target
    )
    historical_publish = publisher.publish(
        historical_draft.id, expected_revision=historical_draft.revision
    )
    current_content = _document("restore-safe-document", title="Current Document")
    current_draft = _create_draft(
        drafts,
        git,
        "document",
        "restore-safe-document",
        current_content,
        target,
    )
    current_publish = publisher.publish(current_draft.id, expected_revision=current_draft.revision)

    restored = publisher.restore(target, historical_publish.commit_revision)

    assert restored.commit_revision not in {
        historical_publish.commit_revision,
        current_publish.commit_revision,
    }
    assert (repository / target).read_text(encoding="utf-8") == historical_content
    assert GitManager(repository).current_revision() == restored.commit_revision


def test_restore_commit_failure_rolls_back_canonical_content(publish_context, monkeypatch):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/restore-commit-failure.md"
    historical_content = _document("restore-commit-failure", title="Historical")
    draft = _create_draft(
        drafts, git, "document", "restore-commit-failure", historical_content, target
    )
    historical = publisher.publish(draft.id, expected_revision=draft.revision)
    current_content = _document("restore-commit-failure", title="Current")
    current_draft = _create_draft(
        drafts, git, "document", "restore-commit-failure", current_content, target
    )
    publisher.publish(current_draft.id, expected_revision=current_draft.revision)
    head = git.current_revision()

    def fail_commit(*_args, **_kwargs):
        raise GitOperationError("simulated restore commit failure")

    monkeypatch.setattr(publisher.git, "commit", fail_commit)
    with pytest.raises(GitOperationError, match="simulated restore commit failure"):
        publisher.restore(target, historical.commit_revision)

    assert (repository / target).read_text(encoding="utf-8") == current_content
    assert git.current_revision() == head
    assert git.status() == ""


def test_restore_rejects_deleting_a_referenced_source(publish_context):
    repository, _, _, _, publisher = publish_context
    git = GitManager(repository)
    before_source = git.current_revision()
    source_path = repository / "knowledge" / "sources" / "restore-source.yaml"
    source_path.write_text(
        "schema_version: 1\nid: restore-source\ntype: web\ntitle: Restore Source\n",
        encoding="utf-8",
    )
    document_path = (
        repository / "knowledge" / "documents" / "learning" / "source-reference.md"
    )
    document_path.write_text(
        _document("source-reference")
        .replace("  - ewc-2017", "  - restore-source")
        .replace("[@ewc-2017]", "[@restore-source]"),
        encoding="utf-8",
    )
    _git(
        repository,
        "add",
        "knowledge/sources/restore-source.yaml",
        "knowledge/documents/learning/source-reference.md",
    )
    _git(repository, "commit", "-m", "add referenced restore Source")
    current_revision = git.current_revision()

    with pytest.raises(PublishValidationError, match="References removed Source"):
        publisher.restore(source_path, before_source)

    assert source_path.is_file()
    assert git.current_revision() == current_revision


def test_restore_rejects_removing_a_referenced_taxonomy_id(publish_context):
    repository, _, _, _, publisher = publish_context
    git = GitManager(repository)
    before_topic = git.current_revision()
    topic_path = repository / "knowledge" / "taxonomy" / "topics.yaml"
    topic_path.write_text(
        topic_path.read_text(encoding="utf-8")
        + "  - id: restore-topic\n    title: Restore Topic\n",
        encoding="utf-8",
    )
    document_path = (
        repository / "knowledge" / "documents" / "learning" / "topic-reference.md"
    )
    document_path.write_text(
        _document(
            "topic-reference", topics=("continual-learning", "restore-topic")
        ),
        encoding="utf-8",
    )
    _git(
        repository,
        "add",
        "knowledge/taxonomy/topics.yaml",
        "knowledge/documents/learning/topic-reference.md",
    )
    _git(repository, "commit", "-m", "add referenced restore Topic")
    current_revision = git.current_revision()

    with pytest.raises(PublishValidationError, match="removed topic"):
        publisher.restore(topic_path, before_topic)

    assert "restore-topic" in topic_path.read_text(encoding="utf-8")
    assert git.current_revision() == current_revision


def test_restore_rejects_broken_historical_markdown(publish_context):
    repository, _, _, _, publisher = publish_context
    git = GitManager(repository)
    target = repository / "knowledge" / "documents" / "learning" / "broken-history.md"
    target.write_text("---\nnot: [valid\n", encoding="utf-8")
    _git(repository, "add", "knowledge/documents/learning/broken-history.md")
    _git(repository, "commit", "-m", "add broken historical document")
    broken_revision = git.current_revision()

    current_content = _document("broken-history", title="Current Valid Document")
    target.write_text(current_content, encoding="utf-8")
    _git(repository, "add", "knowledge/documents/learning/broken-history.md")
    _git(repository, "commit", "-m", "replace with valid document")
    current_revision = git.current_revision()

    with pytest.raises(PublishValidationError, match="Restore content"):
        publisher.restore(target, broken_revision)

    assert target.read_text(encoding="utf-8") == current_content
    assert git.current_revision() == current_revision


def test_restore_allows_style_only_markdown_findings_as_warnings(publish_context):
    repository, _, _, _, publisher = publish_context
    git = GitManager(repository)
    target = repository / "knowledge" / "documents" / "learning" / "restore-style.md"
    historical_content = _document("restore-style", title="Historical Version")
    historical_content += "\n## Unnumbered historical heading\n"
    target.write_text(historical_content, encoding="utf-8")
    _git(repository, "add", "knowledge/documents/learning/restore-style.md")
    _git(repository, "commit", "-m", "add historical style finding")
    historical_revision = git.current_revision()

    current_content = _document("restore-style", title="Current Version")
    target.write_text(current_content, encoding="utf-8")
    _git(repository, "add", "knowledge/documents/learning/restore-style.md")
    _git(repository, "commit", "-m", "update current document")

    result = publisher.restore(target, historical_revision)

    assert target.read_text(encoding="utf-8") == historical_content
    assert any("heading.h2_numbering" in warning for warning in result.warnings)


def test_restore_rejects_taxonomy_registry_absence(publish_context):
    repository, _, _, _, publisher = publish_context
    git = GitManager(repository)
    target = repository / "knowledge" / "taxonomy" / "topics.yaml"
    original = target.read_bytes()
    target.unlink()
    _git(repository, "add", "-u", "knowledge/taxonomy/topics.yaml")
    _git(repository, "commit", "-m", "remove taxonomy registry")
    absent_revision = git.current_revision()
    target.write_bytes(original)
    _git(repository, "add", "knowledge/taxonomy/topics.yaml")
    _git(repository, "commit", "-m", "restore taxonomy registry")
    current_revision = git.current_revision()

    with pytest.raises(
        PublishValidationError, match="cannot be restored to an absent file"
    ):
        publisher.restore(target, absent_revision)

    assert target.read_bytes() == original
    assert git.current_revision() == current_revision


def test_restore_commit_is_success_when_index_update_fails(publish_context, monkeypatch):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/documents/learning/restore-warning.md"
    before_creation = git.current_revision()
    draft = _create_draft(
        drafts, git, "document", "restore-warning", _document("restore-warning"), target
    )
    published = publisher.publish(draft.id, expected_revision=draft.revision)

    def fail_update(*_args, **_kwargs):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(publisher.indexer, "update_path", fail_update)
    result = publisher.restore(target, before_creation)

    assert result.commit_revision == git.current_revision()
    assert not (repository / target).exists()
    assert result.warnings and "run `python tools/kb.py rebuild`" in result.warnings[0]
    _git(repository, "cat-file", "-e", published.commit_revision)


def test_taxonomy_removal_cannot_leave_dangling_canonical_references(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    target = "knowledge/taxonomy/domains.yaml"
    content = "schema_version: 1\nentries: []\n"
    draft = _create_draft(drafts, git, "taxonomy", "domains", content, target)

    with pytest.raises(PublishValidationError, match="removed domain"):
        publisher.publish(draft.id, expected_revision=draft.revision)

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
    publisher.publish(draft.id, expected_revision=draft.revision)
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
        publisher.publish(ambiguous_draft.id, expected_revision=ambiguous_draft.revision)
    assert not (repository / ambiguous_path).exists()


def test_publisher_supports_term_source_and_taxonomy_canonical_paths(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)

    term_path = "knowledge/terms/new-concept.md"
    term_content = _term("new-concept", title="New Concept")
    term_draft = _create_draft(drafts, git, "term", "new-concept", term_content, term_path)
    publisher.publish(term_draft.id, expected_revision=term_draft.revision)

    git = GitManager(repository)
    source_path = "knowledge/sources/new-source.yaml"
    source_content = (
        "schema_version: 1\nid: new-source\ntype: web\ntitle: New Source\n"
        "url: https://example.com/reference\n"
    )
    source_draft = _create_draft(
        drafts, git, "source", "new-source", source_content, source_path
    )
    publisher.publish(source_draft.id, expected_revision=source_draft.revision)

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
    publisher.publish(taxonomy_draft.id, expected_revision=taxonomy_draft.revision)

    assert (repository / term_path).is_file()
    assert (repository / source_path).is_file()
    assert (repository / taxonomy_path).is_file()


def test_source_pdf_attachment_must_match_published_source_id(publish_context):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)
    unrelated_pdf = repository / "storage" / "papers" / "other-source.pdf"
    unrelated_pdf.parent.mkdir(parents=True, exist_ok=True)
    unrelated_pdf.write_bytes(b"%PDF-1.4\nunrelated source")
    source_content = (
        "schema_version: 1\nid: source-owner\ntype: paper\ntitle: Source Owner\n"
        "authors: []\nattachments:\n  local_pdf: storage://papers/other-source.pdf\n"
    )
    draft = _create_draft(
        drafts,
        git,
        "source",
        "source-owner",
        source_content,
        "knowledge/sources/source-owner.yaml",
    )

    with pytest.raises(PublishValidationError, match="attachment ID must match"):
        publisher.publish(draft.id, expected_revision=draft.revision)

    assert not (repository / "knowledge" / "sources" / "source-owner.yaml").exists()


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

    published = publisher.publish(draft.id, expected_revision=draft.revision)
    assert connection.execute(
        "SELECT title FROM document_index WHERE entity_id = ?", ("indexed-note",)
    ).fetchone()[0] == "Test Note"

    publisher.restore(target, before_publish)
    assert connection.execute(
        "SELECT 1 FROM document_index WHERE entity_id = ?", ("indexed-note",)
    ).fetchone() is None
    _git(repository, "cat-file", "-e", published.commit_revision)
    
@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX filesystem permission semantics required",
)
def test_publish_new_file_uses_canonical_file_permissions(
    publish_context,
):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)

    target = "knowledge/documents/learning/permission-note.md"
    path = repository / target
    parent = path.parent

    # Production canonical directories are group-writable.
    parent.chmod(0o775)
    parent_stat = parent.stat()

    content = _document("permission-note")

    draft = _create_draft(
        drafts,
        git,
        "document",
        "permission-note",
        content,
        target,
    )

    publisher.publish(draft.id, expected_revision=draft.revision)

    file_stat = path.stat()

    assert file_stat.st_mode & 0o777 == 0o664
    assert file_stat.st_uid == parent_stat.st_uid
    assert file_stat.st_gid == parent_stat.st_gid


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX filesystem permission semantics required",
)
def test_publish_existing_file_preserves_permissions(
    publish_context,
):
    repository, _, drafts, _, publisher = publish_context
    git = GitManager(repository)

    relative_target = "knowledge/documents/papers/ewc-review.md"
    target = repository / relative_target
    original_content = target.read_text(encoding="utf-8")
    updated_content = original_content + "\nPermission preservation update.\n"

    target.chmod(0o640)

    draft = _create_draft(
        drafts,
        git,
        "document",
        "ewc-review",
        updated_content,
        relative_target,
    )

    publisher.publish(draft.id, expected_revision=draft.revision)

    assert target.read_text(encoding="utf-8") == updated_content
    assert target.stat().st_mode & 0o777 == 0o640


def _initialize_repository(repository: Path) -> None:
    repository.mkdir()
    shutil.copytree(_ROOT / "config", repository / "config")
    (repository / "knowledge").mkdir()
    shutil.copytree(
        _ROOT / "knowledge" / "taxonomy",
        repository / "knowledge" / "taxonomy",
    )
    (repository / "knowledge" / "documents" / "papers").mkdir(parents=True, exist_ok=True)
    (repository / "knowledge" / "documents" / "learning").mkdir(parents=True, exist_ok=True)
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


def _collection(entity_id, title, nodes=""):
    nodes_text = nodes or "  []\n"
    return (
        "schema_version: 1\nid: {}\ntitle: {}\nstatus: active\n"
        "position: 0\nnodes:\n{}"
    ).format(entity_id, title, nodes_text)


def _term(entity_id, title, aliases=()):
    alias_text = "".join("  - {}\n".format(alias) for alias in aliases) or "  []\n"
    return (
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: concept\n"
        "depth: standard\naliases:\n{}domains:\n  - artificial-intelligence\n"
        "topics: []\ntags: []\nsources: []\n---\n# {}\n\nA concise definition.\n"
    ).format(entity_id, title, alias_text, title)


def _markdown_body(content):
    parsed = parse_markdown(content)
    return "".join(content.splitlines(keepends=True)[parsed.frontmatter_end_line :])


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
