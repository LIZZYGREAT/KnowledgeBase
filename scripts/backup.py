#!/usr/bin/env python3
"""Create a restorable archive of canonical Git history, Runtime SQLite, and storage."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.environ.get("KB_BACKUP_PATH", REPOSITORY_ROOT.parent / "KnowledgeBase-backups")),
    )
    arguments = parser.parse_args()
    repository = Path(os.environ.get("KNOWLEDGE_REPO_PATH", REPOSITORY_ROOT)).expanduser().resolve()
    configured_database = Path(
        os.environ.get("DATABASE_PATH", repository / "runtime" / "knowledge.db")
    ).expanduser()
    database = configured_database if configured_database.is_absolute() else repository / configured_database
    output_dir = arguments.output_dir.expanduser().resolve()

    try:
        archive = create_backup(repository, database, output_dir)
    except (OSError, sqlite3.Error, RuntimeError, subprocess.CalledProcessError) as error:
        print("ERROR backup: {}".format(error))
        return 1
    print("Created {} ({:,} bytes)".format(archive, archive.stat().st_size))
    return 0


def create_backup(repository: Path, database: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    dirty = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if dirty.strip():
        raise RuntimeError("Git worktree has uncommitted changes; commit or resolve them before backup")
    if not database.is_file():
        raise RuntimeError("Runtime database does not exist: {}".format(database))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    final_path = output_dir / "knowledgebase-{}.tar.gz".format(stamp)
    temporary_path = output_dir / (final_path.name + ".tmp")
    try:
        with tempfile.TemporaryDirectory(prefix="kb-backup-", dir=output_dir) as staging_dir:
            staging = Path(staging_dir)
            bundle_path = staging / "knowledge.bundle"
            subprocess.run(
                ["git", "-C", str(repository), "bundle", "create", str(bundle_path), "--all", "HEAD"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(repository), "bundle", "verify", str(bundle_path)],
                check=True,
                capture_output=True,
            )

            database_snapshot = staging / "knowledge.db"
            source = sqlite3.connect(str(database))
            target = sqlite3.connect(str(database_snapshot))
            try:
                source.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise RuntimeError("Runtime database backup failed integrity_check: {}".format(result))
            finally:
                target.close()
                source.close()

            storage_snapshot = staging / "storage.tar.gz"
            storage_path = repository / "storage"
            with tarfile.open(storage_snapshot, "w:gz") as storage_archive:
                if storage_path.exists():
                    storage_archive.add(storage_path, arcname="storage", recursive=True)

            manifest = {
                "format": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "contents": ["knowledge.bundle", "runtime/knowledge.db", "storage.tar.gz"],
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with tarfile.open(temporary_path, "w:gz") as archive:
                archive.add(bundle_path, arcname="knowledge.bundle")
                archive.add(database_snapshot, arcname="runtime/knowledge.db")
                archive.add(storage_snapshot, arcname="storage.tar.gz")
                archive.add(staging / "manifest.json", arcname="manifest.json")

        with temporary_path.open("r+b") as source:
            os.fsync(source.fileno())
        temporary_path.replace(final_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return final_path


if __name__ == "__main__":
    raise SystemExit(main())
