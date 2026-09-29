"""Structured and full-text search over rebuildable SQLite indexes."""

from dataclasses import dataclass
from typing import Dict, Optional, Union
import json
import math
import re
import sqlite3

from backend.app.services.resolution import normalize_key


@dataclass(frozen=True)
class SearchFilters:
    domain: Optional[str] = None
    topic: Optional[str] = None
    tag: Optional[str] = None
    document_type: Optional[str] = None
    review: Optional[str] = None
    maintenance: Optional[str] = None
    source: Optional[str] = None
    term: Optional[str] = None


@dataclass(frozen=True)
class SearchResult:
    entity_type: str
    entity_id: str
    title: str
    path: str
    matched_by: str
    score: float
    snippet: str
    metadata: dict
    view_count: int = 0
    search_click_count: int = 0


_FILTER_FIELDS = {
    "domain", "topic", "tag", "document_type", "review", "maintenance", "source", "term"
}
_MATCH_PRIORITY = {"exact id": 5, "title": 4, "alias": 3, "full text": 2, "evidence": 1, "browse": 0}
_USAGE_ALPHA = 0.4
_USAGE_BETA = 0.2
_USAGE_MAX_BOOST = 3.0
_CJK_CHARACTERS = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)


class SearchService:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def search(
        self,
        query: str = "",
        filters: Optional[Union[SearchFilters, dict]] = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        if not isinstance(query, str):
            raise ValueError("query must be text")
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        filter_values = _filters_dict(filters)
        query = query.strip()
        normalized_query = normalize_key(query)
        results: Dict[tuple, SearchResult] = {}

        documents = self.connection.execute(
            """SELECT d.*, COALESCE(s.view_count, 0) AS view_count,
                      COALESCE(s.search_click_count, 0) AS search_click_count
               FROM document_index d
               LEFT JOIN document_stats s ON s.document_id = d.entity_id"""
        ).fetchall()
        terms = self.connection.execute("SELECT * FROM term_index").fetchall()
        sources = self.connection.execute("SELECT * FROM source_index").fetchall()

        for row in documents:
            metadata = json.loads(row["metadata_json"])
            self._offer(
                results, "document", row["entity_id"], row["title"], row["path"],
                metadata, row["view_count"], row["search_click_count"],
                _canonical_match(query, normalized_query, row["entity_id"], row["title"]),
                100.0 if query and query.casefold() == row["entity_id"].casefold()
                else 80.0 if query and normalized_query == normalize_key(row["title"])
                else 0.0,
                "",
                filter_values,
            )

        for row in terms:
            metadata = json.loads(row["metadata_json"])
            aliases = json.loads(row["aliases_json"])
            match = _canonical_match(query, normalized_query, row["entity_id"], row["title"])
            score = 100.0 if match == "exact id" else 80.0 if match == "title" else 0.0
            if query and match is None and normalized_query in {
                normalize_key(alias) for alias in aliases
            }:
                match, score = "alias", 70.0
            self._offer(
                results, "term", row["entity_id"], row["title"], row["path"],
                metadata, 0, 0, match, score, "", filter_values,
            )

        for row in sources:
            metadata = json.loads(row["metadata_json"])
            match = _canonical_match(query, normalized_query, row["entity_id"], row["title"])
            score = 100.0 if match == "exact id" else 80.0 if match == "title" else 0.0
            self._offer(
                results, "source", row["entity_id"], row["title"], row["path"],
                metadata, 0, 0, match, score, "", filter_values,
            )

        if query:
            fts_query = _fts_query(query)
            if fts_query:
                self._search_fts(results, "document_fts", fts_query, filter_values)
                self._search_fts(results, "term_fts", fts_query, filter_values)
                self._search_fts(results, "source_fts", fts_query, filter_values)
                self._search_evidence(results, fts_query, filter_values)
            if _CJK_CHARACTERS.search(query):
                self._search_cjk_literal(results, query, filter_values)

        ordered = sorted(
            results.values(),
            key=lambda item: (
                -item.score,
                -_MATCH_PRIORITY.get(item.matched_by, -1),
                item.title.casefold(),
                item.entity_type,
                item.entity_id,
            ),
        )
        return ordered[:limit]

    def _search_fts(self, results, table: str, fts_query: str, filters: dict) -> None:
        specs = {
            "document_fts": ("document", "document_index", 2, (0.0, 8.0, 1.0, 0.25)),
            "term_fts": ("term", "term_index", 3, (0.0, 8.0, 2.0, 1.0, 0.25)),
            "source_fts": ("source", "source_index", 2, (0.0, 8.0, 0.5)),
        }
        entity_type, index_table, snippet_column, weights = specs[table]
        weight_args = ", ".join("?" for _ in weights)
        if entity_type == "document":
            usage_columns = (
                ", COALESCE(s.view_count, 0) AS view_count, "
                "COALESCE(s.search_click_count, 0) AS search_click_count"
            )
            usage_join = (
                " LEFT JOIN document_stats AS s "
                "ON s.document_id = document_fts.entity_id"
            )
        else:
            usage_columns = ", 0 AS view_count, 0 AS search_click_count"
            usage_join = ""
        rows = self.connection.execute(
            """SELECT entity_id, bm25({table}, {weights}) AS rank,
                      snippet({table}, {snippet_column}, '<mark>', '</mark>', '…', 12) AS snippet
                      {usage_columns}
               FROM {table}{usage_join}
               WHERE {table} MATCH ? ORDER BY rank LIMIT 200""".format(
                table=table,
                weights=weight_args,
                snippet_column=snippet_column,
                usage_columns=usage_columns,
                usage_join=usage_join,
            ),
            tuple(weights) + (fts_query,),
        ).fetchall()
        for match in rows:
            row = self.connection.execute(
                "SELECT * FROM {} WHERE entity_id = ?".format(index_table),
                (match["entity_id"],),
            ).fetchone()
            if row is None:
                continue
            metadata = json.loads(row["metadata_json"])
            rank = float(match["rank"])
            retrieval_score = min(50.0, 40.0 + max(0.0, -rank) * 1000000.0)
            self._offer(
                results, entity_type, row["entity_id"], row["title"], row["path"],
                metadata, match["view_count"], match["search_click_count"],
                "full text", retrieval_score, match["snippet"] or "", filters,
            )

    def _search_evidence(self, results, fts_query: str, filters: dict) -> None:
        rows = self.connection.execute(
            """SELECT evidence_id, entity_id,
                      bm25(evidence_fts, 1.0, 0.0, 1.0) AS rank,
                      snippet(evidence_fts, 2, '<mark>', '</mark>', '…', 12) AS snippet
               FROM evidence_fts WHERE evidence_fts MATCH ? ORDER BY rank LIMIT 200""",
            (fts_query,),
        ).fetchall()
        for match in rows:
            evidence = self.connection.execute(
                "SELECT * FROM evidence_index WHERE id = ?", (match["evidence_id"],)
            ).fetchone()
            if evidence is None:
                continue
            if evidence["entity_type"] == "document":
                row = self.connection.execute(
                    """SELECT d.*, COALESCE(s.view_count, 0) AS view_count,
                              COALESCE(s.search_click_count, 0) AS search_click_count
                       FROM document_index d LEFT JOIN document_stats s
                         ON s.document_id = d.entity_id WHERE d.entity_id = ?""",
                    (evidence["entity_id"],),
                ).fetchone()
                entity_type = "document"
            else:
                row = self.connection.execute(
                    "SELECT * FROM term_index WHERE entity_id = ?", (evidence["entity_id"],)
                ).fetchone()
                entity_type = "term"
            if row is None:
                continue
            metadata = json.loads(row["metadata_json"])
            rank = float(match["rank"])
            retrieval_score = min(50.0, 35.0 + max(0.0, -rank) * 1000000.0)
            self._offer(
                results, entity_type, row["entity_id"], row["title"], row["path"],
                metadata, row["view_count"] if entity_type == "document" else 0,
                row["search_click_count"] if entity_type == "document" else 0,
                "evidence", retrieval_score, match["snippet"] or evidence["claim"], filters,
            )

    def _search_cjk_literal(self, results, query: str, filters: dict) -> None:
        pattern = "%{}%".format(
            query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        specs = {
            "document_fts": ("document", "document_index", ("title", "body", "metadata")),
            "term_fts": ("term", "term_index", ("title", "aliases", "body", "metadata")),
            "source_fts": ("source", "source_index", ("title", "metadata")),
        }
        for table, (entity_type, index_table, columns) in specs.items():
            predicates = " OR ".join(
                "{} LIKE ? ESCAPE '\\'".format(column) for column in columns
            )
            matches = self.connection.execute(
                "SELECT entity_id FROM {} WHERE {}".format(table, predicates),
                tuple(pattern for _ in columns),
            ).fetchall()
            for match in matches:
                if entity_type == "document":
                    row = self.connection.execute(
                        """SELECT d.*, COALESCE(s.view_count, 0) AS view_count,
                                  COALESCE(s.search_click_count, 0) AS search_click_count
                           FROM document_index d LEFT JOIN document_stats s
                             ON s.document_id = d.entity_id WHERE d.entity_id = ?""",
                        (match["entity_id"],),
                    ).fetchone()
                else:
                    row = self.connection.execute(
                        "SELECT * FROM {} WHERE entity_id = ?".format(index_table),
                        (match["entity_id"],),
                    ).fetchone()
                if row is None:
                    continue
                metadata = json.loads(row["metadata_json"])
                self._offer(
                    results,
                    entity_type,
                    row["entity_id"],
                    row["title"],
                    row["path"],
                    metadata,
                    row["view_count"] if entity_type == "document" else 0,
                    row["search_click_count"] if entity_type == "document" else 0,
                    "full text",
                    40.0,
                    "…{}…".format(query),
                    filters,
                )

        evidence_ids = self.connection.execute(
            "SELECT evidence_id FROM evidence_fts WHERE claim LIKE ? ESCAPE '\\'",
            (pattern,),
        ).fetchall()
        for match in evidence_ids:
            evidence = self.connection.execute(
                "SELECT * FROM evidence_index WHERE id = ?", (match["evidence_id"],)
            ).fetchone()
            if evidence is None:
                continue
            if evidence["entity_type"] == "document":
                row = self.connection.execute(
                    """SELECT d.*, COALESCE(s.view_count, 0) AS view_count,
                              COALESCE(s.search_click_count, 0) AS search_click_count
                       FROM document_index d LEFT JOIN document_stats s
                         ON s.document_id = d.entity_id WHERE d.entity_id = ?""",
                    (evidence["entity_id"],),
                ).fetchone()
                entity_type = "document"
            else:
                row = self.connection.execute(
                    "SELECT * FROM term_index WHERE entity_id = ?",
                    (evidence["entity_id"],),
                ).fetchone()
                entity_type = "term"
            if row is None:
                continue
            metadata = json.loads(row["metadata_json"])
            self._offer(
                results,
                entity_type,
                row["entity_id"],
                row["title"],
                row["path"],
                metadata,
                row["view_count"] if entity_type == "document" else 0,
                row["search_click_count"] if entity_type == "document" else 0,
                "evidence",
                35.0,
                "…{}…".format(query),
                filters,
            )

    def _offer(
        self, results, entity_type, entity_id, title, path, metadata,
        view_count, search_click_count, matched_by, retrieval_score, snippet, filters,
    ) -> None:
        if matched_by is None and retrieval_score <= 0:
            return
        if not _matches_filters(
            self.connection, entity_type, entity_id, metadata, filters
        ):
            return
        matched_by = matched_by or "browse"
        usage_boost = min(
            _USAGE_MAX_BOOST,
            _USAGE_ALPHA * math.log1p(view_count)
            + _USAGE_BETA * math.log1p(search_click_count),
        )
        result = SearchResult(
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            path=path,
            matched_by=matched_by,
            score=retrieval_score + usage_boost,
            snippet=snippet,
            metadata=metadata,
            view_count=view_count,
            search_click_count=search_click_count,
        )
        key = (entity_type, entity_id)
        previous = results.get(key)
        if previous is None or (
            result.score > previous.score
            or (
                result.score == previous.score
                and _MATCH_PRIORITY.get(result.matched_by, -1)
                > _MATCH_PRIORITY.get(previous.matched_by, -1)
            )
        ):
            results[key] = result


def _canonical_match(query: str, normalized_query: str, entity_id: str, title: str):
    if not query:
        return "browse"
    if query.casefold() == entity_id.casefold():
        return "exact id"
    if normalized_query and normalized_query == normalize_key(title):
        return "title"
    return None


def _filters_dict(filters) -> dict:
    if filters is None:
        return {}
    if isinstance(filters, SearchFilters):
        values = {
            key: value for key, value in filters.__dict__.items() if value is not None
        }
    elif isinstance(filters, dict):
        unknown = set(filters) - _FILTER_FIELDS
        if unknown:
            raise ValueError("Unknown search filter(s): {}".format(", ".join(sorted(unknown))))
        values = {key: value for key, value in filters.items() if value is not None}
    else:
        raise ValueError("filters must be SearchFilters or a mapping")
    for key, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Search filter '{}' must be non-empty text".format(key))
    return values


def _matches_filters(connection, entity_type: str, entity_id: str, metadata: dict, filters: dict) -> bool:
    array_fields = {"domain": "domains", "topic": "topics", "tag": "tags"}
    for filter_name, metadata_field in array_fields.items():
        if filter_name in filters and filters[filter_name] not in metadata.get(metadata_field, []):
            return False

    if "document_type" in filters:
        if entity_type != "document" or metadata.get("type") != filters["document_type"]:
            return False
    if "review" in filters:
        review = metadata.get("review") or {}
        statuses = {
            review.get("ai", {}).get("status"),
            review.get("human", {}).get("status"),
        }
        if filters["review"] not in statuses:
            return False
    if "maintenance" in filters:
        if (metadata.get("maintenance") or {}).get("status") != filters["maintenance"]:
            return False
    if "source" in filters:
        if entity_type == "source":
            if entity_id != filters["source"]:
                return False
        elif filters["source"] not in metadata.get("sources", []):
            citation = connection.execute(
                "SELECT 1 FROM evidence_index WHERE entity_type = ? AND entity_id = ? "
                "AND source_id = ? LIMIT 1",
                (entity_type, entity_id, filters["source"]),
            ).fetchone()
            if citation is None:
                return False
    if "term" in filters:
        if entity_type == "term":
            if entity_id != filters["term"]:
                return False
        elif entity_type != "document":
            return False
        else:
            linked = connection.execute(
                "SELECT 1 FROM backlink_index WHERE source_entity_type = 'document' "
                "AND source_entity_id = ? AND term_id = ? LIMIT 1",
                (entity_id, filters["term"]),
            ).fetchone()
            if linked is None:
                return False
    return True


def _fts_query(query: str) -> str:
    tokens = [token for token in re.findall(r"[^\s]+", query) if token]
    if not tokens:
        return ""
    return " AND ".join('"{}"'.format(token.replace('"', '""')) for token in tokens)
