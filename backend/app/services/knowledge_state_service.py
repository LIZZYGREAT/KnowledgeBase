"""Build an explainable, runtime-only view of current Term knowledge state."""

from datetime import datetime, timedelta, timezone
import re
import sqlite3
from typing import Callable, Optional

from backend.app.services.term_registry import TermRegistry


class KnowledgeStateService:
    def __init__(
        self,
        repository_root,
        connection: sqlite3.Connection,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.repository_root = repository_root
        self.connection = connection
        self.clock = clock

    def build_snapshot(self, focus: list[str]) -> dict:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Knowledge State clock must return a timezone-aware datetime")
        cutoff = (now.astimezone(timezone.utc) - timedelta(days=30)).isoformat()
        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        relations = {
            row["term_id"]: int(row["relation_count"])
            for row in self.connection.execute(
                """SELECT term_id, COUNT(*) AS relation_count
                   FROM term_entity_relations GROUP BY term_id"""
            ).fetchall()
        }
        recent_activity = {
            row["term_id"]
            for row in self.connection.execute(
                """SELECT DISTINCT relation.term_id
                   FROM usage_events activity
                   JOIN term_entity_relations relation
                     ON relation.entity_type = 'document'
                    AND relation.entity_id = activity.entity_id
                   WHERE activity.event_type = 'document_open'
                     AND activity.created_at >= ?""",
                (cutoff,),
            ).fetchall()
        }
        recent_accepted = {
            row["term_id"]
            for row in self.connection.execute(
                """SELECT DISTINCT term_id FROM term_entity_relations
                   WHERE created_at >= ?""",
                (cutoff,),
            ).fetchall()
        }
        exposure = _pdf_exposure(self.connection, registry.terms)
        state_by_term: dict[str, str] = {}
        for term in registry.terms:
            if term.depth == "deep" or (
                term.depth == "standard" and relations.get(term.id, 0) > 0
            ):
                state = "established"
            elif term.id in recent_activity or term.id in recent_accepted:
                state = "learning"
            elif exposure.get(term.id, {}).get("source_count", 0) > 0:
                state = "exposed"
            else:
                state = "unknown"
            state_by_term[term.id] = state

        return {
            "focus": {
                "explicit": list(dict.fromkeys(value.strip() for value in focus if value.strip()))[:20],
            },
            "knowledge": {
                "established": _term_labels(registry.terms, state_by_term, "established"),
                "learning": _term_labels(registry.terms, state_by_term, "learning"),
                "exposed": _term_labels(registry.terms, state_by_term, "exposed"),
                "unknown": _term_labels(registry.terms, state_by_term, "unknown"),
            },
            "exposure": {
                "source_count_sampled": min(
                    self.connection.execute(
                        "SELECT COUNT(*) FROM pdf_corpus WHERE status = 'ready'"
                    ).fetchone()[0],
                    8,
                ),
                "terms": [
                    {"id": term_id, **counts}
                    for term_id, counts in sorted(
                        exposure.items(), key=lambda item: (-item[1]["source_count"], item[0])
                    )[:40]
                ],
            },
            "activity": {
                "window_days": 30,
                "recently_used_terms": [
                    {"id": term.id, "title": term.title, "type": term.type}
                    for term in registry.terms
                    if term.id in recent_activity
                ][:40],
            },
            "term_states": state_by_term,
            "registry": [
                {
                    "id": term.id,
                    "title": term.title,
                    "aliases": list(term.aliases[:8]),
                    "type": term.type,
                    "depth": term.depth,
                    "state": state_by_term[term.id],
                }
                for term in registry.terms[:200]
            ],
        }


def _term_labels(terms, state_by_term: dict[str, str], state: str) -> list[dict]:
    return [
        {"id": term.id, "title": term.title, "type": term.type, "depth": term.depth}
        for term in terms
        if state_by_term.get(term.id) == state
    ][:80]


def _pdf_exposure(connection: sqlite3.Connection, terms) -> dict[str, dict]:
    rows = connection.execute(
        """SELECT source_id, text FROM pdf_corpus WHERE status = 'ready'
           ORDER BY updated_at DESC, source_id LIMIT 8"""
    ).fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        text = (row["text"] or "")[:100_000]
        folded = text.casefold()
        for term in terms:
            if term.id not in result:
                result[term.id] = {"source_count": 0, "mention_count": 0}
            names = (term.title,) + tuple(term.aliases)
            source_mentions = 0
            for name in names:
                if not name.strip():
                    continue
                pattern = _literal_pattern(name.casefold())
                source_mentions += len(pattern.findall(folded))
            if source_mentions:
                result[term.id]["source_count"] += 1
                result[term.id]["mention_count"] += source_mentions
    return {term_id: counts for term_id, counts in result.items() if counts["source_count"]}


def _literal_pattern(value: str) -> re.Pattern:
    escaped = re.escape(value)
    if value and value[0].isalnum() and value[-1].isalnum() and value.isascii():
        escaped = r"(?<![a-z0-9]){}(?![a-z0-9])".format(escaped)
    return re.compile(escaped)
