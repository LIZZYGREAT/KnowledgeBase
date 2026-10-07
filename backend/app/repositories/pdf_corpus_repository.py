"""Runtime persistence for lazily extracted PDF text."""

import sqlite3
from typing import Optional, Sequence

from backend.app.domain.pdf_corpus import PdfCorpusRecord, PdfCorpusState


class PdfCorpusRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get(self, source_id: str) -> Optional[PdfCorpusRecord]:
        row = self.connection.execute(
            "SELECT * FROM pdf_corpus WHERE source_id = ?", (source_id,)
        ).fetchone()
        return _record(row) if row is not None else None

    def get_state(self, source_id: str) -> Optional[PdfCorpusState]:
        row = self.connection.execute(
            """SELECT source_id, text_hash, status, extracted_at,
                      error_message, updated_at
               FROM pdf_corpus WHERE source_id = ?""",
            (source_id,),
        ).fetchone()
        return _state(row) if row is not None else None

    def list_states(self, source_ids: Sequence[str]) -> dict[str, PdfCorpusState]:
        """Load status rows in bounded batches without selecting corpus text."""
        unique_ids = list(dict.fromkeys(source_ids))
        result: dict[str, PdfCorpusState] = {}
        batch_size = 900
        for start in range(0, len(unique_ids), batch_size):
            batch = unique_ids[start : start + batch_size]
            placeholders = ", ".join("?" for _ in batch)
            rows = self.connection.execute(
                """SELECT source_id, text_hash, status, extracted_at,
                          error_message, updated_at
                   FROM pdf_corpus WHERE source_id IN ({})""".format(placeholders),
                batch,
            ).fetchall()
            result.update((row["source_id"], _state(row)) for row in rows)
        return result

    def save(self, record: PdfCorpusRecord) -> None:
        self.connection.execute(
            """INSERT INTO pdf_corpus (
                   source_id, pdf_hash, extractor_version, text_hash, text,
                   status, extracted_at, error_message, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id) DO UPDATE SET
                   pdf_hash = excluded.pdf_hash,
                   extractor_version = excluded.extractor_version,
                   text_hash = excluded.text_hash,
                   text = excluded.text,
                   status = excluded.status,
                   extracted_at = excluded.extracted_at,
                   error_message = excluded.error_message,
                   updated_at = excluded.updated_at""",
            (
                record.source_id,
                record.pdf_hash,
                record.extractor_version,
                record.text_hash,
                record.text,
                record.status,
                record.extracted_at,
                record.error_message,
                record.updated_at,
            ),
        )
        self.connection.commit()


def _record(row: sqlite3.Row) -> PdfCorpusRecord:
    return PdfCorpusRecord(
        source_id=row["source_id"],
        pdf_hash=row["pdf_hash"],
        extractor_version=row["extractor_version"],
        text_hash=row["text_hash"],
        text=row["text"],
        status=row["status"],
        extracted_at=row["extracted_at"],
        error_message=row["error_message"],
        updated_at=row["updated_at"],
    )


def _state(row: sqlite3.Row) -> PdfCorpusState:
    return PdfCorpusState(
        source_id=row["source_id"],
        text_hash=row["text_hash"],
        status=row["status"],
        extracted_at=row["extracted_at"],
        error_message=row["error_message"],
        updated_at=row["updated_at"],
    )
