"""Persistence for Runtime-only presentation annotations."""

import sqlite3
from typing import Optional
import uuid

from backend.app.domain.runtime import PresentationAnnotation


class AnnotationRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[PresentationAnnotation]:
        rows = self.connection.execute(
            """SELECT * FROM presentation_annotations
               WHERE entity_type = ? AND entity_id = ?
               ORDER BY start_offset, end_offset, style_type""",
            (entity_type, entity_id),
        ).fetchall()
        return [_annotation(row) for row in rows]

    def list_stale(self) -> list[PresentationAnnotation]:
        rows = self.connection.execute(
            """SELECT * FROM presentation_annotations WHERE status = 'stale'
               ORDER BY updated_at DESC, entity_type, entity_id, start_offset"""
        ).fetchall()
        return [_annotation(row) for row in rows]

    def get(self, annotation_id: str) -> PresentationAnnotation:
        row = self.connection.execute(
            "SELECT * FROM presentation_annotations WHERE id = ?", (annotation_id,)
        ).fetchone()
        if row is None:
            raise LookupError("Presentation annotation '{}' does not exist".format(annotation_id))
        return _annotation(row)

    def upsert(self, annotation: PresentationAnnotation) -> PresentationAnnotation:
        existing = self.connection.execute(
            """SELECT id, created_at FROM presentation_annotations
               WHERE entity_type = ? AND entity_id = ? AND style_type = ?
                 AND start_offset = ? AND end_offset = ?""",
            (
                annotation.entity_type,
                annotation.entity_id,
                annotation.style_type,
                annotation.start_offset,
                annotation.end_offset,
            ),
        ).fetchone()
        annotation_id = existing["id"] if existing else uuid.uuid4().hex
        created_at = existing["created_at"] if existing else annotation.created_at
        saved = PresentationAnnotation(
            id=annotation_id,
            entity_type=annotation.entity_type,
            entity_id=annotation.entity_id,
            style_type=annotation.style_type,
            style_value=annotation.style_value,
            selected_text=annotation.selected_text,
            prefix_text=annotation.prefix_text,
            suffix_text=annotation.suffix_text,
            start_offset=annotation.start_offset,
            end_offset=annotation.end_offset,
            base_content_hash=annotation.base_content_hash,
            status=annotation.status,
            created_at=created_at,
            updated_at=annotation.updated_at,
        )
        self.connection.execute(
            """INSERT INTO presentation_annotations (
                   id, entity_type, entity_id, style_type, style_value,
                   selected_text, prefix_text, suffix_text, start_offset, end_offset,
                   base_content_hash, status, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(entity_type, entity_id, style_type, start_offset, end_offset)
               DO UPDATE SET style_value = excluded.style_value,
                             selected_text = excluded.selected_text,
                             prefix_text = excluded.prefix_text,
                             suffix_text = excluded.suffix_text,
                             base_content_hash = excluded.base_content_hash,
                             status = excluded.status,
                             updated_at = excluded.updated_at""",
            tuple(saved.__dict__.values()),
        )
        self.connection.commit()
        return saved

    def update_anchor(
        self,
        annotation_id: str,
        start_offset: int,
        end_offset: int,
        base_content_hash: str,
        status: str,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            """UPDATE presentation_annotations
               SET start_offset = ?, end_offset = ?, base_content_hash = ?,
                   status = ?, updated_at = ? WHERE id = ?""",
            (start_offset, end_offset, base_content_hash, status, updated_at, annotation_id),
        )
        self.connection.commit()

    def update_style(
        self,
        annotation_id: str,
        style_type: str,
        style_value: Optional[str],
        updated_at: str,
    ) -> PresentationAnnotation:
        self.connection.execute(
            """UPDATE presentation_annotations
               SET style_type = ?, style_value = ?, updated_at = ? WHERE id = ?""",
            (style_type, style_value, updated_at, annotation_id),
        )
        self.connection.commit()
        return self.get(annotation_id)

    def delete(self, annotation_id: str) -> None:
        cursor = self.connection.execute(
            "DELETE FROM presentation_annotations WHERE id = ?", (annotation_id,)
        )
        self.connection.commit()
        if cursor.rowcount == 0:
            raise LookupError("Presentation annotation '{}' does not exist".format(annotation_id))


def _annotation(row: sqlite3.Row) -> PresentationAnnotation:
    return PresentationAnnotation(**dict(row))
