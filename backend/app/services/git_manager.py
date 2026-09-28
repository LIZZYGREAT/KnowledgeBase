"""Narrow Git operations for canonical KnowledgeBase files."""

from pathlib import Path
from typing import Optional, Union
import hashlib
import os
import re
import subprocess
import tempfile


class GitOperationError(RuntimeError):
    pass


class GitConflictError(RuntimeError):
    pass


class GitManager:
    """Wrap Git access and restrict all file operations to ``knowledge/``."""

    def __init__(self, repository_root: Union[str, Path]):
        self.repository_root = Path(repository_root).resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        if not self.knowledge_root.is_dir():
            raise ValueError("Repository must contain a knowledge/ directory")
        result = self._run(["rev-parse", "--show-toplevel"], check=False)
        if result.returncode != 0:
            raise ValueError("Repository root is not inside a Git repository")
        git_root = Path(result.stdout.decode("utf-8").strip()).resolve()
        if git_root != self.repository_root:
            raise ValueError("repository_root must be the Git worktree root")

    def status(self) -> str:
        result = self._run(["status", "--short", "--untracked-files=all"])
        return result.stdout.decode("utf-8")

    def current_revision(self) -> str:
        result = self._run(["rev-parse", "--verify", "HEAD"])
        return result.stdout.decode("ascii").strip()

    def diff(self, base_revision: str, path: Union[str, Path]) -> str:
        revision = _validate_revision(base_revision)
        relative_path = self._relative_knowledge_path(path)
        result = self._run(["diff", revision, "--", relative_path])
        return result.stdout.decode("utf-8", errors="replace")

    def content_hash(self, path: Union[str, Path]) -> str:
        target, _ = self._resolve_knowledge_path(path)
        content = target.read_bytes() if target.is_file() else b""
        return hashlib.sha256(content).hexdigest()

    def assert_base(
        self, base_revision: str, base_content_hash: str, path: Union[str, Path]
    ) -> None:
        expected_revision = _validate_revision(base_revision)
        current_revision = self.current_revision()
        if expected_revision != current_revision:
            raise GitConflictError(
                "Git base changed from {} to {}".format(
                    expected_revision, current_revision
                )
            )
        actual_hash = self.content_hash(path)
        if not re.fullmatch(r"[0-9a-f]{64}", base_content_hash or ""):
            raise GitConflictError("Draft has an invalid canonical content hash")
        if base_content_hash != actual_hash:
            raise GitConflictError(
                "Canonical file changed since the Draft base was captured"
            )

    def commit(self, path: Union[str, Path], message: str) -> str:
        relative_path = self._relative_knowledge_path(path)
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Commit message must be non-empty text")
        tracked = self._run(
            ["ls-files", "--error-unmatch", "--", relative_path], check=False
        )
        staged_new_file = tracked.returncode != 0 and Path(
            self.repository_root / relative_path
        ).is_file()
        if staged_new_file:
            self._run(["add", "--", relative_path])
        result = self._run(
            ["commit", "--only", "-m", message.strip(), "--", relative_path],
            check=False,
        )
        if result.returncode != 0:
            if staged_new_file:
                self._run(
                    ["rm", "--cached", "--ignore-unmatch", "--", relative_path],
                    check=False,
                )
            raise GitOperationError(
                "Git commit failed: {}".format(
                    result.stderr.decode("utf-8", errors="replace").strip()
                )
            )
        return self.current_revision()

    def restore(
        self,
        path: Union[str, Path],
        revision: str,
        message: Optional[str] = None,
    ) -> str:
        """Restore a tracked path from history and record the restoration as a commit."""
        target_revision = _validate_revision(revision)
        self._run(
            ["cat-file", "-e", "{}^{{commit}}".format(target_revision)]
        )
        target, relative_path = self._resolve_knowledge_path(path)
        head = self.current_revision()
        tracked_at_head = self._run(
            ["cat-file", "-e", "{}:{}".format(head, relative_path)], check=False
        )
        if tracked_at_head.returncode != 0:
            raise GitOperationError("Restore target is not tracked at the current revision")

        historical = self._run(
            ["cat-file", "-e", "{}:{}".format(target_revision, relative_path)],
            check=False,
        )
        if historical.returncode == 0:
            object_type = self._run(
                ["cat-file", "-t", "{}:{}".format(target_revision, relative_path)]
            ).stdout.decode("ascii").strip()
            if object_type != "blob":
                raise GitOperationError("Restore revision does not contain a regular file")
        previous = target.read_bytes() if target.is_file() else None
        try:
            if historical.returncode == 0:
                content = self._run(
                    ["show", "{}:{}".format(target_revision, relative_path)]
                ).stdout
                _atomic_write(target, content)
            else:
                if target.exists():
                    if not target.is_file():
                        raise GitOperationError("Restore target is not a regular file")
                    target.unlink()

            commit_message = message or "restore: {} to {}".format(
                relative_path, target_revision[:12]
            )
            return self.commit(relative_path, commit_message)
        except Exception:
            if previous is None:
                if target.exists() and target.is_file():
                    target.unlink()
            else:
                _atomic_write(target, previous)
            raise

    def _relative_knowledge_path(self, path: Union[str, Path]) -> str:
        _, relative = self._resolve_knowledge_path(path)
        return relative

    def _resolve_knowledge_path(self, path: Union[str, Path]):
        supplied = Path(path)
        lexical = supplied if supplied.is_absolute() else self.repository_root / supplied
        lexical = Path(os.path.abspath(str(lexical)))
        try:
            repo_relative = lexical.relative_to(self.repository_root)
            knowledge_relative = lexical.relative_to(self.knowledge_root)
        except ValueError as error:
            raise ValueError("Git operations are limited to repository knowledge/ files") from error

        cursor = self.repository_root
        for part in repo_relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Git operations do not follow symlinks")

        if not knowledge_relative.parts or any(part in {".", ".."} for part in knowledge_relative.parts):
            raise ValueError("A canonical file path under knowledge/ is required")
        if lexical.suffix.lower() not in {".md", ".yaml", ".yml"}:
            raise ValueError("Canonical files must use .md, .yaml, or .yml")
        if lexical.exists() and not lexical.is_file():
            raise ValueError("Canonical target must be a regular file")
        return lexical, lexical.relative_to(self.repository_root).as_posix()

    def _run(self, arguments, check=True):
        result = subprocess.run(
            ["git", "-C", str(self.repository_root)] + list(arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and result.returncode != 0:
            raise GitOperationError(
                "Git {} failed: {}".format(
                    arguments[0], result.stderr.decode("utf-8", errors="replace").strip()
                )
            )
        return result


def _validate_revision(revision: str) -> str:
    if not isinstance(revision, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision):
        raise ValueError("Git revision must be a full commit hash")
    return revision


def _atomic_write(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", dir=str(target.parent), prefix=".kb-publish-", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(target))
    finally:
        if temporary.exists():
            temporary.unlink()
