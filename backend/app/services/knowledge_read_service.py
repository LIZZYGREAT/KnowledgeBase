"""Read canonical entities through the rebuildable knowledge indexes."""

import json
from pathlib import Path
import sqlite3

from backend.app.services.markdown_parser import parse_markdown, parse_yaml


_INDEX_TABLES = {
    "document": ("document_index", ".md"),
    "term": ("term_index", ".md"),
    "source": ("source_index", ".yaml"),
}


class KnowledgeReadService:
    def __init__(self, repository_root: Path, connection: sqlite3.Connection):
        self.repository_root = Path(repository_root).resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        self.connection = connection

    def list_entities(self, entity_type: str, limit: int = 50, offset: int = 0) -> list[dict]:
        if entity_type not in _INDEX_TABLES:
            raise ValueError("Unsupported canonical entity type: {}".format(entity_type))
        _validate_page(limit, offset)
        table, _ = _INDEX_TABLES[entity_type]
        rows = self.connection.execute(
            "SELECT entity_id, title, metadata_json FROM {} "
            "ORDER BY title COLLATE NOCASE, entity_id LIMIT ? OFFSET ?".format(table),
            (limit, offset),
        ).fetchall()
        return [
            {
                "id": row["entity_id"],
                "title": row["title"],
                "entity_type": entity_type,
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def get_entity(self, entity_type: str, entity_id: str) -> dict:
        if entity_type not in _INDEX_TABLES:
            raise ValueError("Unsupported canonical entity type: {}".format(entity_type))
        table, extension = _INDEX_TABLES[entity_type]
        row = self.connection.execute(
            "SELECT * FROM {} WHERE entity_id = ?".format(table), (entity_id,)
        ).fetchone()
        if row is None:
            raise LookupError("{} '{}' does not exist in the canonical index".format(entity_type, entity_id))
        path = self._canonical_path(row["path"], extension)
        content = path.read_text(encoding="utf-8")
        if entity_type in {"document", "term"}:
            parsed = parse_markdown(content)
            if parsed.frontmatter is None:
                raise ValueError("Indexed Markdown has invalid frontmatter: {}".format(entity_id))
            metadata = parsed.frontmatter
            body = _markdown_body(content, parsed.frontmatter_end_line)
        else:
            metadata = parse_yaml(content)
            body = None
        if metadata.get("id") != entity_id:
            raise ValueError("Indexed canonical id does not match file metadata: {}".format(entity_id))

        result = {
            "id": entity_id,
            "title": metadata["title"],
            "entity_type": entity_type,
            "metadata": metadata,
            "content": body,
            "related_terms": self._related_terms(entity_type, entity_id),
            "backlinks": self._backlinks(entity_type, entity_id),
            "evidence": self._evidence(entity_type, entity_id),
            "related_documents": [],
        }
        if entity_type == "source":
            result["related_documents"] = self._source_documents(entity_id)
            result["evidence"] = self._source_evidence(entity_id)
        return result

    def topics(self, limit: int = 100, offset: int = 0) -> list[dict]:
        _validate_page(limit, offset)
        rows = self.connection.execute(
            "SELECT entity_id, title FROM taxonomy_index WHERE kind = 'topic' "
            "ORDER BY title COLLATE NOCASE, entity_id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [{"id": row["entity_id"], "title": row["title"]} for row in rows]

    def _related_terms(self, entity_type: str, entity_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT DISTINCT t.entity_id, t.title, t.metadata_json
               FROM backlink_index b JOIN term_index t ON t.entity_id = b.term_id
               WHERE b.source_entity_type = ? AND b.source_entity_id = ?
               ORDER BY t.title COLLATE NOCASE, t.entity_id""",
            (entity_type, entity_id),
        ).fetchall()
        return [
            {"id": row["entity_id"], "title": row["title"], "metadata": json.loads(row["metadata_json"])}
            for row in rows
        ]

    def _backlinks(self, entity_type: str, entity_id: str) -> list[dict]:
        if entity_type == "term":
            rows = self.connection.execute(
                """SELECT source_entity_type, source_entity_id, link_target, label, line
                   FROM backlink_index WHERE term_id = ?
                   ORDER BY source_entity_type, source_entity_id, line""",
                (entity_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        return []

    def _evidence(self, entity_type: str, entity_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT source_id, locator, line, citation, claim
               FROM evidence_index WHERE entity_type = ? AND entity_id = ?
               ORDER BY line, source_id""",
            (entity_type, entity_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _source_documents(self, source_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT entity_id, title, metadata_json FROM document_index "
            "ORDER BY title COLLATE NOCASE, entity_id"
        ).fetchall()
        related = []
        evidence_ids = {
            row["entity_id"]
            for row in self.connection.execute(
                "SELECT DISTINCT entity_id FROM evidence_index "
                "WHERE entity_type = 'document' AND source_id = ?",
                (source_id,),
            )
        }
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            if source_id in metadata.get("sources", []) or row["entity_id"] in evidence_ids:
                related.append({"id": row["entity_id"], "title": row["title"], "metadata": metadata})
        return related

    def _source_evidence(self, source_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT entity_type, entity_id, locator, line, citation, claim
               FROM evidence_index WHERE source_id = ?
               ORDER BY entity_type, entity_id, line""",
            (source_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _canonical_path(self, relative_path: str, extension: str) -> Path:
        target = (self.repository_root / relative_path).resolve()
        try:
            target.relative_to(self.knowledge_root.resolve())
        except ValueError as error:
            raise ValueError("Canonical index path escaped knowledge/") from error
        if target.suffix.lower() != extension or not target.is_file():
            raise LookupError("Indexed canonical file is missing")
        return target


def _markdown_body(content: str, frontmatter_end_line: int) -> str:
    lines = content.lstrip("\ufeff").splitlines()
    return "\n".join(lines[frontmatter_end_line:]).strip()


def _validate_page(limit: int, offset: int) -> None:
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    if not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be zero or greater")
