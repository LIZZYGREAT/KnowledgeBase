"""SQLite persistence for Import Jobs and their staged items."""

import json
import sqlite3
from typing import List, Optional

from backend.app.domain.imports import ImportItem, ImportJob


class ImportJobNotFoundError(LookupError):
    pass


class ImportItemNotFoundError(LookupError):
    pass


class ImportRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def create_job(self, job: ImportJob) -> ImportJob:
        with self.connection:
            self.connection.execute(
                """INSERT INTO import_jobs (
                       id, status, profile, created_at, updated_at, error_message
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    job.id, job.status, job.profile, job.created_at,
                    job.updated_at, job.error_message,
                ),
            )
        return self.get_job(job.id)

    def get_job(self, job_id: str) -> Optional[ImportJob]:
        row = self.connection.execute(
            "SELECT * FROM import_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if row is None:
            return None
        return ImportJob(
            id=row["id"],
            status=row["status"],
            profile=row["profile"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            error_message=row["error_message"],
        )

    def update_job(self, job_id: str, status: str, updated_at: str, error_message=None) -> ImportJob:
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE import_jobs SET status = ?, updated_at = ?, error_message = ?
                   WHERE id = ?""",
                (status, updated_at, error_message, job_id),
            )
        if cursor.rowcount != 1:
            raise ImportJobNotFoundError("Import Job '{}' does not exist".format(job_id))
        return self.get_job(job_id)

    def create_item(self, item: ImportItem) -> ImportItem:
        with self.connection:
            self.connection.execute(
                """INSERT INTO import_items (
                       id, job_id, path, file_type, sha256, status,
                       detected_entity_type, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.id, item.job_id, item.path, item.file_type, item.sha256,
                    item.status, item.detected_entity_type,
                    json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
        return self.get_item(item.id)

    def get_item(self, item_id: str) -> Optional[ImportItem]:
        row = self.connection.execute(
            "SELECT * FROM import_items WHERE id = ?", (item_id,)
        ).fetchone()
        return _item_from_row(row) if row else None

    def list_items(self, job_id: str) -> List[ImportItem]:
        rows = self.connection.execute(
            "SELECT * FROM import_items WHERE job_id = ? ORDER BY path, id",
            (job_id,),
        ).fetchall()
        return [_item_from_row(row) for row in rows]

    def update_item(self, item: ImportItem) -> ImportItem:
        metadata_json = json.dumps(
            item.metadata, ensure_ascii=False, sort_keys=True
        )
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE import_items SET
                       path = ?, file_type = ?, sha256 = ?, status = ?,
                       detected_entity_type = ?, metadata_json = ?
                   WHERE id = ?""",
                (
                    item.path, item.file_type, item.sha256, item.status,
                    item.detected_entity_type, metadata_json, item.id,
                ),
            )
        if cursor.rowcount != 1:
            raise ImportItemNotFoundError("Import Item '{}' does not exist".format(item.id))
        return self.get_item(item.id)

    def find_duplicate(self, file_type: str, sha256: str) -> Optional[ImportItem]:
        row = self.connection.execute(
            """SELECT * FROM import_items
               WHERE file_type = ? AND sha256 = ?
                 AND status NOT IN ('failed', 'duplicate')
               ORDER BY rowid LIMIT 1""",
            (file_type, sha256),
        ).fetchone()
        return _item_from_row(row) if row else None


def _item_from_row(row) -> ImportItem:
    return ImportItem(
        id=row["id"],
        job_id=row["job_id"],
        path=row["path"],
        file_type=row["file_type"],
        sha256=row["sha256"],
        status=row["status"],
        detected_entity_type=row["detected_entity_type"],
        metadata=json.loads(row["metadata_json"]),
    )
