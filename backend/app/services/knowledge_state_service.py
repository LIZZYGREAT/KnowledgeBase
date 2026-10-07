"""Build an explainable, runtime-only view of current Term knowledge state."""

from datetime import datetime, timedelta, timezone
import re
import sqlite3
from typing import Callable, Optional

from backend.app.domain.document import DocumentMetadata
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.term_registry import TermRegistry
from backend.app.services.term_resolver import TermResolver


RECENT_WINDOW_DAYS = 30
MAX_RECENT_DOCUMENTS = 12
MAX_FOCUS_ITEMS = 20


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
        now_utc = now.astimezone(timezone.utc)
        cutoff = (now_utc - timedelta(days=RECENT_WINDOW_DAYS)).isoformat()
        registry = TermRegistry.load(self.repository_root / "knowledge" / "terms")
        relations = {
            row["term_id"]: int(row["relation_count"])
            for row in self.connection.execute(
                """SELECT term_id, COUNT(*) AS relation_count
                   FROM term_entity_relations GROUP BY term_id"""
            ).fetchall()
        }
        relations_by_document: dict[str, list[str]] = {}
        for row in self.connection.execute(
            """SELECT entity_id, term_id FROM term_entity_relations
               WHERE entity_type = 'document' ORDER BY created_at DESC, term_id"""
        ).fetchall():
            relations_by_document.setdefault(row["entity_id"], []).append(
                row["term_id"]
            )
        recent_documents = _recent_documents(
            self.repository_root,
            self.connection,
            cutoff,
            registry,
            relations_by_document,
        )
        recently_opened_ids = [
            item["id"] for item in recent_documents if item["opened_at"] is not None
        ]
        recent_activity = {
            term_id
            for document_id in recently_opened_ids
            for term_id in relations_by_document.get(document_id, [])
        }
        recent_accepted_rows = self.connection.execute(
            """SELECT term_id, MAX(created_at) AS accepted_at
               FROM term_entity_relations WHERE created_at >= ?
               GROUP BY term_id ORDER BY accepted_at DESC, term_id""",
            (cutoff,),
        ).fetchall()
        recent_accepted = {row["term_id"] for row in recent_accepted_rows}
        exposure = _pdf_exposure(self.connection, registry.terms)
        state_by_term: dict[str, str] = {}
        for term in registry.terms:
            if term.depth in {"standard", "deep"}:
                state = "established"
            elif term.id in recent_activity or term.id in recent_accepted:
                state = "learning"
            elif exposure.get(term.id, {}).get("source_count", 0) > 0:
                state = "exposed"
            else:
                state = "unknown"
            state_by_term[term.id] = state

        recent_topics = _unique_values(
            value for item in recent_documents for value in item["topics"]
        )
        recent_domains = _unique_values(
            value for item in recent_documents for value in item["domains"]
        )
        recent_term_ids = _unique_values(
            term_id
            for item in recent_documents
            for term_id in item["linked_term_ids"] + item["accepted_term_ids"]
        )
        recent_term_ids.extend(
            term_id
            for term_id in (row["term_id"] for row in recent_accepted_rows)
            if term_id not in recent_term_ids
        )
        terms_by_id = {term.id: term for term in registry.terms}
        recent_terms = [
            {"id": term_id, "title": terms_by_id[term_id].title, "type": terms_by_id[term_id].type}
            for term_id in recent_term_ids[:MAX_FOCUS_ITEMS]
            if term_id in terms_by_id
        ]
        recently_used_term_ids = _unique_values(
            term_id
            for document_id in recently_opened_ids
            for term_id in relations_by_document.get(document_id, [])
        )
        recently_used_term_id_set = set(recently_used_term_ids)

        return {
            "focus": {
                "explicit": list(dict.fromkeys(value.strip() for value in focus if value.strip()))[:20],
                "recent_topics": recent_topics[:MAX_FOCUS_ITEMS],
                "recent_domains": recent_domains[:MAX_FOCUS_ITEMS],
                "recent_terms": recent_terms,
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
                "window_days": RECENT_WINDOW_DAYS,
                "recent_documents": [
                    {
                        "id": item["id"],
                        "title": item["title"],
                        "opened_at": item["opened_at"],
                        "modified_at": item["modified_at"],
                    }
                    for item in recent_documents
                ],
                "recently_used_terms": [
                    {"id": term.id, "title": term.title, "type": term.type}
                    for term in registry.terms
                    if term.id in recently_used_term_id_set
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


def _recent_documents(
    repository_root,
    connection: sqlite3.Connection,
    cutoff: str,
    registry: TermRegistry,
    relations_by_document: dict[str, list[str]],
) -> list[dict]:
    opened_at = {
        row["entity_id"]: row["opened_at"]
        for row in connection.execute(
            """SELECT entity_id, MAX(created_at) AS opened_at FROM usage_events
               WHERE entity_type = 'document' AND event_type = 'document_open'
                 AND created_at >= ? GROUP BY entity_id ORDER BY opened_at DESC
               LIMIT ?""",
            (cutoff, MAX_RECENT_DOCUMENTS * 4),
        ).fetchall()
    }
    documents_root = (repository_root / "knowledge" / "documents").resolve()
    cutoff_time = datetime.fromisoformat(cutoff)
    paths = []
    if documents_root.is_dir():
        for path in documents_root.rglob("*.md"):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(documents_root):
                    continue
                modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                opened = opened_at.get(path.stem)
                opened_time = datetime.fromisoformat(opened) if opened else None
                if not (opened_time and opened_time >= cutoff_time) and modified < cutoff_time:
                    continue
                signal_time = max(
                    value for value in (opened_time, modified if modified >= cutoff_time else None)
                    if value is not None
                )
                paths.append((signal_time, path.stem, path, opened, modified))
            except (OSError, ValueError):
                continue
    paths.sort(key=lambda item: (-item[0].timestamp(), item[1]))
    resolver = TermResolver(registry)
    result = []
    for _signal, document_id, path, opened, modified in paths[:MAX_RECENT_DOCUMENTS]:
        try:
            content = path.read_text(encoding="utf-8")
            parsed = parse_markdown(content)
            metadata = DocumentMetadata.model_validate(parsed.frontmatter)
            if metadata.id != document_id:
                continue
            relative = path.relative_to(documents_root)
            expected_directory = {
                "paper-note": "papers",
                "learning-note": "learning",
                "course-note": "courses",
            }[metadata.type]
            if len(relative.parts) != 2 or relative.parts[0] != expected_directory:
                continue
        except (OSError, ValueError, TypeError, KeyError):
            continue
        linked_term_ids = []
        for link in parsed.wiki_links:
            resolution = resolver.resolve(link.target)
            if resolution.status == "resolved" and resolution.entity_id:
                linked_term_ids.append(resolution.entity_id)
        result.append(
            {
                "id": metadata.id,
                "title": metadata.title,
                "opened_at": opened,
                "modified_at": modified.isoformat(timespec="seconds"),
                "domains": metadata.domains,
                "topics": metadata.topics,
                "linked_term_ids": _unique_values(linked_term_ids),
                "accepted_term_ids": _unique_values(
                    relations_by_document.get(metadata.id, [])
                ),
            }
        )
    return result


def _unique_values(values) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


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
