import sqlite3
import subprocess
import tarfile

import pytest

from backend.app.db.connection import connect_database
from scripts.backup import create_backup


def _git(repository, *arguments):
    subprocess.run(["git", "-C", str(repository), *arguments], check=True, capture_output=True)


def test_backup_contains_git_runtime_and_storage_snapshots(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "knowledge").mkdir()
    (repository / ".gitignore").write_text("/runtime/\n/storage/\n", encoding="utf-8")
    (repository / "knowledge" / "note.md").write_text("canonical", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Backup test")
    _git(repository, "config", "user.email", "backup@example.invalid")
    _git(repository, "add", ".gitignore", "knowledge/note.md")
    _git(repository, "commit", "-m", "initial")

    runtime = repository / "runtime" / "knowledge.db"
    connection = connect_database(runtime)
    connection.execute("INSERT INTO drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        "draft-id", "document", "note", "revision", "hash", "content", 1, "now", "now"
    ))
    connection.commit()
    connection.close()
    papers = repository / "storage" / "papers"
    papers.mkdir(parents=True)
    (papers / "source.pdf").write_bytes(b"%PDF-1.7")

    archive_path = create_backup(repository, runtime, tmp_path / "backups")

    with tarfile.open(archive_path, "r:gz") as archive:
        assert set(archive.getnames()) == {
            "knowledge.bundle",
            "runtime/knowledge.db",
            "storage.tar.gz",
            "manifest.json",
        }
        archive.extractall(tmp_path / "restore")

    bundle_path = tmp_path / "restore" / "knowledge.bundle"
    restored_repository = tmp_path / "restored-repository"
    _git(tmp_path, "clone", str(bundle_path), str(restored_repository))
    restored_note = restored_repository / "knowledge" / "note.md"
    assert restored_note.read_text(encoding="utf-8") == "canonical"

    restored_db = sqlite3.connect(tmp_path / "restore" / "runtime" / "knowledge.db")
    try:
        assert restored_db.execute("SELECT content FROM drafts WHERE id = 'draft-id'").fetchone()[0] == "content"
        assert restored_db.execute("SELECT name FROM sqlite_master WHERE name = 'presentation_annotations'").fetchone()
    finally:
        restored_db.close()

    storage_archive = tmp_path / "restore" / "storage.tar.gz"
    with tarfile.open(storage_archive, "r:gz") as archive:
        archive.extractall(tmp_path / "restored-storage")
    assert (tmp_path / "restored-storage" / "storage" / "papers" / "source.pdf").read_bytes() == b"%PDF-1.7"


def test_backup_refuses_uncommitted_canonical_changes(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "knowledge").mkdir()
    (repository / ".gitignore").write_text("/runtime/\n/storage/\n", encoding="utf-8")
    note = repository / "knowledge" / "note.md"
    note.write_text("canonical", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Backup test")
    _git(repository, "config", "user.email", "backup@example.invalid")
    _git(repository, "add", "knowledge/note.md")
    _git(repository, "commit", "-m", "initial")
    note.write_text("uncommitted", encoding="utf-8")
    runtime = repository / "runtime" / "knowledge.db"
    connection = connect_database(runtime)
    connection.close()

    with pytest.raises(RuntimeError, match="uncommitted changes"):
        create_backup(repository, runtime, tmp_path / "backups")


@pytest.mark.parametrize(
    "relative_path",
    ["config/research/profiles/profile.yaml", "config/research/research.yaml"],
)
def test_backup_refuses_uncommitted_research_configuration(tmp_path, relative_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".gitignore").write_text("/runtime/\n/storage/\n", encoding="utf-8")
    research_config = repository / relative_path
    research_config.parent.mkdir(parents=True)
    research_config.write_text("version: 1\n", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "Backup test")
    _git(repository, "config", "user.email", "backup@example.invalid")
    _git(repository, "add", ".gitignore", relative_path)
    _git(repository, "commit", "-m", "initial")
    research_config.write_text("version: 2\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Git worktree has uncommitted changes"):
        create_backup(repository, tmp_path / "runtime" / "knowledge.db", tmp_path / "backups")
