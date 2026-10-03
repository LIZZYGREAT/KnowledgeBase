from pathlib import Path
import subprocess

import pytest

from backend.app.services.git_manager import GitManager


def test_git_manager_commits_research_profiles_as_an_explicit_canonical_root(tmp_path):
    repository = tmp_path / "repo"
    (repository / "knowledge").mkdir(parents=True)
    (repository / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "KnowledgeBase Tests")
    _git(repository, "config", "user.email", "kb-tests@example.invalid")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "initial state")

    git = GitManager(repository)
    base_revision = git.current_revision()
    target = "config/research/profiles/continual-learning.yaml"
    profile_path = repository / target
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("schema_version: 1\nid: continual-learning\n", encoding="utf-8")

    revision = git.commit(target, "Add research profile")

    assert git.read_at_revision(target, revision) == profile_path.read_bytes()
    assert "continual-learning" in git.diff(base_revision, target)
    assert _git(repository, "show", "--pretty=format:", "--name-only", revision).splitlines() == [
        target
    ]


@pytest.mark.parametrize(
    "path",
    [
        "config/research/research.yaml",
        "config/writing-standard.yaml",
        "config/research/profiles/profile.md",
        "backend/app/settings.yaml",
        "README.md",
    ],
)
def test_git_manager_rejects_files_outside_canonical_roots(tmp_path, path):
    repository = tmp_path / "repo"
    (repository / "knowledge").mkdir(parents=True)
    (repository / "README.md").write_text("initial\n", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.name", "KnowledgeBase Tests")
    _git(repository, "config", "user.email", "kb-tests@example.invalid")
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "initial state")

    git = GitManager(repository)

    with pytest.raises(ValueError):
        git.content_hash(path)


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout.strip()
