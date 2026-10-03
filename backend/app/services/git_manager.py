"""Narrow Git operations for canonical KnowledgeBase files."""

from pathlib import Path
from typing import Optional, Union
import hashlib
import os
import re
import subprocess
import stat
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
        if not target.is_file():
            return hashlib.sha256(b"\x00knowledgebase:missing").hexdigest()
        return hashlib.sha256(target.read_bytes()).hexdigest()

    def read_at_revision(
        self, path: Union[str, Path], revision: str
    ) -> Optional[bytes]:
        """Read a canonical file from a commit, or return None if it was absent."""
        target_revision = _validate_revision(revision)
        self._run(["cat-file", "-e", "{}^{{commit}}".format(target_revision)])
        _, relative_path = self._resolve_knowledge_path(path)
        object_spec = "{}:{}".format(target_revision, relative_path)
        historical = self._run(["cat-file", "-e", object_spec], check=False)
        if historical.returncode != 0:
            return None
        object_type = (
            self._run(["cat-file", "-t", object_spec])
            .stdout.decode("ascii")
            .strip()
        )
        if object_type != "blob":
            raise GitOperationError("Revision path is not a regular file")
        return self._run(["show", object_spec]).stdout

    def assert_base(
        self, base_revision: str, base_content_hash: str, path: Union[str, Path]
    ) -> None:
        _validate_revision(base_revision)
        actual_hash = self.content_hash(path)
        if not re.fullmatch(r"[0-9a-f]{64}", base_content_hash or ""):
            raise GitConflictError("Draft has an invalid canonical content hash")
        if base_content_hash != actual_hash:
            raise GitConflictError(
                "Canonical file changed since the Draft base was captured"
            )

    def commit(self, path: Union[str, Path], message: str) -> str:
        return self.commit_many([path], message)

    def commit_many(self, paths, message: str) -> str:
        """Commit only the supplied canonical paths, preserving unrelated staged files."""
        relative_paths = [self._relative_knowledge_path(path) for path in paths]
        if not relative_paths:
            raise ValueError("At least one canonical file path is required")
        if len(relative_paths) != len(set(relative_paths)):
            raise ValueError("Canonical commit paths must be unique")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Commit message must be non-empty text")
        new_paths = []
        for relative_path in relative_paths:
            tracked = self._run(
                ["ls-files", "--error-unmatch", "--", relative_path], check=False
            )
            if tracked.returncode != 0 and (self.repository_root / relative_path).is_file():
                new_paths.append(relative_path)

        try:
            if new_paths:
                self._run(["add", "--"] + new_paths)
            result = self._run(
                ["commit", "--only", "-m", message.strip(), "--"] + relative_paths,
                check=False,
            )
            if result.returncode != 0:
                raise GitOperationError(
                    "Git commit failed: {}".format(
                        result.stderr.decode("utf-8", errors="replace").strip()
                    )
                )
            return self.current_revision()
        except Exception:
            if new_paths:
                self._run(
                    ["rm", "--cached", "--ignore-unmatch", "--"] + new_paths,
                    check=False,
                )
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

    # Production is Linux, but development/tests may run on Windows.
    # Windows does not provide POSIX ownership APIs such as geteuid/fchown.
    preserve_posix_metadata = os.name == "posix"

    desired_mode = None
    desired_uid = None
    desired_gid = None

    if preserve_posix_metadata:
        if target.exists():
            target_stat = target.stat()
            desired_mode = stat.S_IMODE(target_stat.st_mode)
            desired_uid = target_stat.st_uid
            desired_gid = target_stat.st_gid
        else:
            parent_stat = target.parent.stat()

            # New canonical files inherit the parent directory's
            # read/write policy while dropping directory execute bits.
            desired_mode = stat.S_IMODE(parent_stat.st_mode) & 0o666
            desired_uid = parent_stat.st_uid
            desired_gid = parent_stat.st_gid

    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=str(target.parent),
        prefix=".kb-publish-",
        delete=False,
    )
    temporary = Path(handle.name)

    try:
        with handle:
            handle.write(content)
            handle.flush()

            if preserve_posix_metadata:
                # The production backend currently runs as root. For a
                # new bind-mounted canonical file, adopt the canonical
                # directory owner/group instead of leaving root:root.
                if (
                    hasattr(os, "geteuid")
                    and hasattr(os, "fchown")
                    and os.geteuid() == 0
                ):
                    os.fchown(
                        handle.fileno(),
                        desired_uid,
                        desired_gid,
                    )

                if hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), desired_mode)

            os.fsync(handle.fileno())

        os.replace(str(temporary), str(target))

    finally:
        if temporary.exists():
            temporary.unlink()
