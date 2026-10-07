"""Read canonical entities through the rebuildable knowledge indexes."""

import json
from collections import defaultdict
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Optional

from backend.app.services.markdown_parser import parse_markdown, parse_yaml
from backend.app.services.resolution import normalize_key


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

    def entity_summary(self, entity_type: str, entity_id: str) -> dict:
        if entity_type not in _INDEX_TABLES:
            raise ValueError("Unsupported canonical entity type: {}".format(entity_type))
        table, _ = _INDEX_TABLES[entity_type]
        row = self.connection.execute(
            "SELECT entity_id, title, metadata_json FROM {} WHERE entity_id = ?".format(table),
            (entity_id,),
        ).fetchone()
        if row is None:
            raise LookupError("{} '{}' does not exist in the canonical index".format(entity_type, entity_id))
        return {
            "id": row["entity_id"],
            "title": row["title"],
            "entity_type": entity_type,
            "metadata": json.loads(row["metadata_json"]),
        }

    def library_documents(self) -> list[dict]:
        rows = self.connection.execute(
            """SELECT entity_id, title, metadata_json, content_hash
               FROM document_index
               ORDER BY title COLLATE NOCASE, entity_id"""
        ).fetchall()
        return [
            {
                "id": row["entity_id"],
                "title": row["title"],
                "entity_type": "document",
                "metadata": json.loads(row["metadata_json"]),
                "content_hash": row["content_hash"],
            }
            for row in rows
        ]

    def library_sources(self) -> list[dict]:
        """Build Library Source summaries and related Terms in bounded SQL reads."""
        source_rows = self.connection.execute(
            """SELECT entity_id, title, metadata_json FROM source_index
               ORDER BY title COLLATE NOCASE, entity_id"""
        ).fetchall()
        if not source_rows:
            return []

        sources = {
            row["entity_id"]: {
                "id": row["entity_id"],
                "title": row["title"],
                "entity_type": "source",
                "metadata": json.loads(row["metadata_json"]),
                "related_terms": {},
            }
            for row in source_rows
        }
        document_sources: dict[str, set[str]] = defaultdict(set)
        document_rows = self.connection.execute(
            "SELECT entity_id, metadata_json FROM document_index"
        ).fetchall()
        for row in document_rows:
            metadata = json.loads(row["metadata_json"])
            source_ids = metadata.get("sources", [])
            if isinstance(source_ids, list):
                for source_id in source_ids:
                    if isinstance(source_id, str) and source_id in sources:
                        document_sources[row["entity_id"]].add(source_id)

        evidence_rows = self.connection.execute(
            """SELECT DISTINCT source_id, entity_id FROM evidence_index
               WHERE entity_type = 'document'"""
        ).fetchall()
        for row in evidence_rows:
            if row["source_id"] in sources:
                document_sources[row["entity_id"]].add(row["source_id"])

        document_ids = sorted(document_sources)
        for start in range(0, len(document_ids), 900):
            batch = document_ids[start : start + 900]
            placeholders = ", ".join("?" for _ in batch)
            linked_terms = self.connection.execute(
                """SELECT DISTINCT b.source_entity_id AS document_id,
                          t.entity_id, t.title, t.metadata_json
                   FROM backlink_index b
                   JOIN term_index t ON t.entity_id = b.term_id
                   WHERE b.source_entity_type = 'document'
                     AND b.source_entity_id IN ({})""".format(placeholders),
                batch,
            ).fetchall()
            for row in linked_terms:
                term = {
                    "id": row["entity_id"],
                    "title": row["title"],
                    "entity_type": "term",
                    "metadata": json.loads(row["metadata_json"]),
                }
                for source_id in document_sources[row["document_id"]]:
                    sources[source_id]["related_terms"][row["entity_id"]] = term

        source_ids = list(sources)
        for start in range(0, len(source_ids), 900):
            batch = source_ids[start : start + 900]
            placeholders = ", ".join("?" for _ in batch)
            accepted_terms = self.connection.execute(
                """SELECT DISTINCT r.entity_id AS source_id,
                          t.entity_id, t.title, t.metadata_json
                   FROM term_entity_relations r
                   JOIN term_index t ON t.entity_id = r.term_id
                   WHERE r.entity_type = 'source'
                     AND r.entity_id IN ({})""".format(placeholders),
                batch,
            ).fetchall()
            for row in accepted_terms:
                sources[row["source_id"]]["related_terms"][row["entity_id"]] = {
                    "id": row["entity_id"],
                    "title": row["title"],
                    "entity_type": "term",
                    "metadata": json.loads(row["metadata_json"]),
                }

        result = []
        for source in sources.values():
            terms = sorted(
                source["related_terms"].values(),
                key=lambda item: (item["title"].casefold(), item["id"]),
            )
            result.append({**source, "related_terms": terms})
        return result

    def unfiled_documents(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return Documents that have no Collection entity reference."""
        _validate_page(limit, offset)
        rows = self.connection.execute(
            """SELECT d.entity_id, d.title, d.metadata_json
               FROM document_index d
               WHERE NOT EXISTS (
                   SELECT 1 FROM collection_node_index n
                   WHERE n.kind = 'entity'
                     AND n.entity_type = 'document'
                     AND n.entity_id = d.entity_id
               )
               ORDER BY d.title COLLATE NOCASE, d.entity_id
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return [
            {
                "id": row["entity_id"],
                "title": row["title"],
                "entity_type": "document",
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
        if row is None and entity_type == "term":
            resolved_id = self._resolve_term_alias(entity_id)
            if resolved_id is not None:
                entity_id = resolved_id
                row = self.connection.execute(
                    "SELECT * FROM term_index WHERE entity_id = ?", (entity_id,)
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
            "canonical_content": content,
            "related_terms": self._related_terms(entity_type, entity_id),
            "backlinks": self._backlinks(entity_type, entity_id),
            "detected_mentions": self._detected_mentions(entity_id) if entity_type == "term" else [],
            "evidence": self._evidence(entity_type, entity_id),
            "related_documents": [],
            "term_relations": self._runtime_term_relations(entity_type, entity_id),
        }
        if entity_type == "source":
            result["related_documents"] = self._source_documents(entity_id)
            result["related_terms"] = self._source_terms(
                entity_id,
                [document["id"] for document in result["related_documents"]],
            )
            result["evidence"] = self._source_evidence(entity_id)
        return result

    def _resolve_term_alias(self, query: str) -> Optional[str]:
        normalized_query = normalize_key(query)
        if not normalized_query:
            return None
        matches = set()
        rows = self.connection.execute(
            "SELECT entity_id, title, aliases_json FROM term_index"
        ).fetchall()
        for row in rows:
            values = [row["entity_id"], row["title"], *json.loads(row["aliases_json"])]
            if any(normalize_key(value) == normalized_query for value in values):
                matches.add(row["entity_id"])
        if len(matches) > 1:
            raise LookupError("Term alias '{}' is ambiguous".format(query))
        return next(iter(matches)) if matches else None

    def _runtime_term_relations(self, entity_type: str, entity_id: str) -> list[dict]:
        if entity_type == "term":
            rows = self.connection.execute(
                """SELECT entity_type, entity_id, term_id,
                          created_from_candidate_id, created_at
                   FROM term_entity_relations WHERE term_id = ?
                   ORDER BY entity_type, entity_id""",
                (entity_id,),
            ).fetchall()
            title_column = {
                "document": ("document_index", "entity_id"),
                "source": ("source_index", "entity_id"),
                "research_work": ("research_works", "id"),
            }
            result = []
            for row in rows:
                table, identifier_column = title_column[row["entity_type"]]
                title_row = self.connection.execute(
                    "SELECT title FROM {} WHERE {} = ?".format(table, identifier_column),
                    (row["entity_id"],),
                ).fetchone()
                result.append(
                    {
                        **dict(row),
                        "title": title_row["title"] if title_row is not None else None,
                    }
                )
            return result

        if entity_type not in {"document", "source"}:
            return []
        rows = self.connection.execute(
            """SELECT r.entity_type, r.entity_id, r.term_id,
                      r.created_from_candidate_id, r.created_at, t.title
               FROM term_entity_relations r
               LEFT JOIN term_index t ON t.entity_id = r.term_id
               WHERE r.entity_type = ? AND r.entity_id = ?
               ORDER BY t.title COLLATE NOCASE, r.term_id""",
            (entity_type, entity_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def entity_context_summaries(
        self, entity_keys: set[tuple[str, str]]
    ) -> dict[tuple[str, str], dict]:
        """Load bounded ranking metadata without reading canonical entity files."""
        ids_by_type = {
            entity_type: sorted(
                entity_id
                for candidate_type, entity_id in entity_keys
                if candidate_type == entity_type
            )
            for entity_type in _INDEX_TABLES
        }
        summaries = {}
        batch_size = 800
        for entity_type, ids in ids_by_type.items():
            table, _ = _INDEX_TABLES[entity_type]
            for start in range(0, len(ids), batch_size):
                batch = ids[start : start + batch_size]
                placeholders = ", ".join("?" for _ in batch)
                rows = self.connection.execute(
                    "SELECT entity_id, title, metadata_json FROM {} "
                    "WHERE entity_id IN ({})".format(table, placeholders),
                    batch,
                ).fetchall()
                for row in rows:
                    metadata = json.loads(row["metadata_json"])
                    summaries[(entity_type, row["entity_id"])] = {
                        "title": row["title"],
                        "metadata": {
                            key: metadata[key]
                            for key in ("review", "metadata_review", "topics", "domains")
                            if key in metadata
                        },
                    }
        return summaries

    def topics(self, limit: int = 100, offset: int = 0) -> list[dict]:
        _validate_page(limit, offset)
        rows = self.connection.execute(
            "SELECT entity_id, title FROM taxonomy_index WHERE kind = 'topic' "
            "ORDER BY title COLLATE NOCASE, entity_id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [{"id": row["entity_id"], "title": row["title"]} for row in rows]

    def taxonomy_entries(self, kind: str) -> list[dict]:
        if kind not in {"domain", "topic", "tag"}:
            raise ValueError("kind must be domain, topic, or tag")
        rows = self.connection.execute(
            "SELECT entity_id, title FROM taxonomy_index WHERE kind = ? "
            "ORDER BY title COLLATE NOCASE, entity_id",
            (kind,),
        ).fetchall()
        return [{"id": row["entity_id"], "title": row["title"], "kind": kind} for row in rows]

    def recently_modified(self, limit: int = 10) -> list[dict]:
        _validate_page(limit, 0)
        rows = self.connection.execute(
            "SELECT entity_id, title, path, metadata_json FROM document_index"
        ).fetchall()
        by_path = {row["path"]: row for row in rows}
        if not by_path:
            return []
        result = subprocess.run(
            [
                "git", "-C", str(self.repository_root), "log", "--format=%cI",
                "--name-only", "--", "knowledge/documents",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError("Could not read canonical document history: {}".format(message))
        modified_at = {}
        current_date = None
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if len(line) >= 20 and line[:4].isdigit() and "T" in line:
                current_date = line
            elif current_date and line.replace("\\", "/") in by_path:
                modified_at.setdefault(line.replace("\\", "/"), current_date)
                if len(modified_at) == len(by_path):
                    break
        entries = [
            {
                "id": row["entity_id"],
                "title": row["title"],
                "entity_type": "document",
                "metadata": json.loads(row["metadata_json"]),
                "modified_at": modified_at[path],
            }
            for path, row in by_path.items()
            if path in modified_at
        ]
        return sorted(entries, key=lambda item: (item["modified_at"], item["id"]), reverse=True)[:limit]

    def link_issues(self) -> list[dict]:
        aliases = self._term_aliases()
        issues = []
        rows = self.connection.execute(
            "SELECT entity_id, title, path FROM document_index ORDER BY entity_id"
        ).fetchall()
        for row in rows:
            content = self._canonical_path(row["path"], ".md").read_text(encoding="utf-8")
            parsed = parse_markdown(content)
            for link in parsed.wiki_links:
                candidates = aliases.get(normalize_key(link.target), set())
                if len(candidates) == 1:
                    continue
                issues.append(
                    {
                        "document_id": row["entity_id"],
                        "document_title": row["title"],
                        "target": link.target,
                        "line": link.line,
                        "status": "unresolved" if not candidates else "ambiguous",
                        "candidate_ids": sorted(candidates),
                    }
                )
        return issues

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
                """SELECT b.source_entity_type, b.source_entity_id,
                          b.link_target, b.label, b.line,
                          COALESCE(d.title, t.title) AS source_title
                   FROM backlink_index b
                   LEFT JOIN document_index d
                     ON b.source_entity_type = 'document'
                    AND d.entity_id = b.source_entity_id
                   LEFT JOIN term_index t
                     ON b.source_entity_type = 'term'
                    AND t.entity_id = b.source_entity_id
                   WHERE b.term_id = ?
                   ORDER BY b.source_entity_type, b.source_entity_id, b.line""",
                (entity_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        return []

    def _detected_mentions(self, term_id: str) -> list[dict]:
        term = self.connection.execute(
            "SELECT title, aliases_json FROM term_index WHERE entity_id = ?", (term_id,)
        ).fetchone()
        if term is None:
            return []
        linked_ids = {
            row["source_entity_id"]
            for row in self.connection.execute(
                "SELECT DISTINCT source_entity_id FROM backlink_index "
                "WHERE term_id = ? AND source_entity_type = 'document'",
                (term_id,),
            )
        }
        aliases = [term["title"], term_id] + json.loads(term["aliases_json"])
        patterns = [
            re.compile(
                r"(?<![\w]){}(?![\w])".format(re.escape(alias))
                if re.search(r"[A-Za-z0-9_]", alias)
                else re.escape(alias),
                re.IGNORECASE,
            )
            for alias in sorted(set(aliases), key=len, reverse=True)
            if alias.strip()
        ]
        rows = self.connection.execute(
            "SELECT entity_id, title, path FROM document_index ORDER BY title COLLATE NOCASE"
        ).fetchall()
        mentions = []
        for row in rows:
            if row["entity_id"] in linked_ids:
                continue
            content = self._canonical_path(row["path"], ".md").read_text(encoding="utf-8")
            parsed = parse_markdown(content)
            body = _markdown_body(content, parsed.frontmatter_end_line)
            if any(pattern.search(body) for pattern in patterns):
                mentions.append({"id": row["entity_id"], "title": row["title"]})
        return mentions

    def _term_aliases(self) -> dict[str, set[str]]:
        rows = self.connection.execute(
            "SELECT entity_id, title, aliases_json FROM term_index"
        ).fetchall()
        aliases: dict[str, set[str]] = {}
        for row in rows:
            for value in [row["entity_id"], row["title"]] + json.loads(row["aliases_json"]):
                aliases.setdefault(normalize_key(value), set()).add(row["entity_id"])
        return aliases

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

    def _source_terms(self, source_id: str, document_ids: list[str]) -> list[dict]:
        terms_by_id = {}
        if document_ids:
            placeholders = ", ".join("?" for _ in document_ids)
            rows = self.connection.execute(
                """SELECT DISTINCT t.entity_id, t.title, t.metadata_json
                   FROM backlink_index b JOIN term_index t ON t.entity_id = b.term_id
                   WHERE b.source_entity_type = 'document'
                     AND b.source_entity_id IN ({})""".format(placeholders),
                document_ids,
            ).fetchall()
            terms_by_id.update((row["entity_id"], row) for row in rows)

        accepted_rows = self.connection.execute(
            """SELECT DISTINCT t.entity_id, t.title, t.metadata_json
               FROM term_entity_relations r JOIN term_index t ON t.entity_id = r.term_id
               WHERE r.entity_type = 'source' AND r.entity_id = ?""",
            (source_id,),
        ).fetchall()
        terms_by_id.update((row["entity_id"], row) for row in accepted_rows)

        return [
            {
                "id": row["entity_id"],
                "title": row["title"],
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in sorted(
                terms_by_id.values(),
                key=lambda item: (item["title"].casefold(), item["entity_id"]),
            )
        ]

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
