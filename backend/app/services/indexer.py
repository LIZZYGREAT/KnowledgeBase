"""Build and update disposable SQLite indexes from Canonical Knowledge."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Union
import hashlib
import json
import sqlite3

from backend.app.domain.document import DocumentMetadata
from backend.app.domain.source import SourceMetadata
from backend.app.domain.term import TermMetadata
from backend.app.services.markdown_parser import MarkdownDocument, parse_markdown, parse_yaml
from backend.app.services.resolution import normalize_key
from backend.app.services.taxonomy_registry import TaxonomyRegistry
from backend.app.services.term_registry import AliasIndex, TermRegistry
from backend.app.services.term_resolver import TermResolver


class IndexBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexBuildSummary:
    documents: int
    terms: int
    aliases: int
    taxonomy_entries: int
    backlinks: int
    evidence: int
    sources: int


@dataclass(frozen=True)
class _MarkdownRecord:
    entity_type: str
    entity_id: str
    path: str
    title: str
    metadata: object
    parsed: MarkdownDocument
    text: str
    body: str
    content_hash: str


class Indexer:
    """Indexes are disposable views; all indexed content comes from files."""

    def __init__(self, repository_root: Union[str, Path], connection: sqlite3.Connection):
        self.repository_root = Path(repository_root).resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        self.connection = connection

    def full_rebuild(self) -> IndexBuildSummary:
        documents, terms, sources, taxonomy, markdown = self._snapshot()
        term_records = [record for record in markdown if record.entity_type == "term"]
        backlinks, evidence = self._relations(markdown, term_records)
        with self.connection:
            self._clear_derived_indexes()
            for row in documents:
                self._insert_document(row)
            for row in terms:
                self._insert_term(row)
            for row in sources:
                self._insert_source(row)
            self.connection.executemany(
                "INSERT INTO taxonomy_index (kind, entity_id, title) VALUES (?, ?, ?)",
                taxonomy,
            )
            self._insert_relations(backlinks, evidence)
            self._sync_document_stats()
        counts = self._counts()
        return IndexBuildSummary(
            documents=len(documents),
            terms=len(terms),
            aliases=counts["aliases"],
            taxonomy_entries=len(taxonomy),
            backlinks=len(backlinks),
            evidence=len(evidence),
            sources=len(sources),
        )

    def rebuild(self) -> IndexBuildSummary:
        return self.full_rebuild()

    def update_path(self, path: Union[str, Path]) -> IndexBuildSummary:
        """Refresh one canonical entity and the derived relationships it can affect."""
        target, relative = self._canonical_path(path)
        if len(relative.parts) < 2 or relative.parts[0] != "knowledge":
            raise ValueError("Only canonical knowledge files can be indexed")
        category = relative.parts[1]

        if category == "documents" and target.suffix.lower() == ".md":
            if len(relative.parts) != 4 or relative.parts[2] not in {"papers", "learning", "courses"}:
                raise ValueError("Documents must use their canonical type directory")
            record = self._read_markdown_record(target, "document") if target.is_file() else None
            markdown = self._read_all_markdown()
            terms = [item for item in markdown if item.entity_type == "term"]
            documents = [item for item in markdown if item.entity_type == "document"]
            backlinks, evidence = self._relations(documents + terms, terms)
            with self.connection:
                self.connection.execute(
                    "DELETE FROM document_index WHERE entity_id = ?", (target.stem,)
                )
                self.connection.execute(
                    "DELETE FROM document_fts WHERE entity_id = ?", (target.stem,)
                )
                if record is not None:
                    self._insert_document(self._document_row(record))
                self._replace_relations(backlinks, evidence)
                self._sync_document_stats()
        elif category == "terms" and target.suffix.lower() == ".md":
            if relative.parts != ("knowledge", "terms", target.name):
                raise ValueError("Terms must be stored directly under knowledge/terms/")
            record = self._read_markdown_record(target, "term") if target.is_file() else None
            markdown = self._read_all_markdown()
            terms = [item for item in markdown if item.entity_type == "term"]
            documents = [item for item in markdown if item.entity_type == "document"]
            backlinks, evidence = self._relations(documents + terms, terms)
            with self.connection:
                self.connection.execute("DELETE FROM term_index WHERE entity_id = ?", (target.stem,))
                self.connection.execute("DELETE FROM alias_index WHERE term_id = ?", (target.stem,))
                self.connection.execute("DELETE FROM term_fts WHERE entity_id = ?", (target.stem,))
                if record is not None:
                    self._insert_term(self._term_row(record))
                self._replace_relations(backlinks, evidence)
                self._sync_document_stats()
        elif category == "sources" and target.suffix.lower() == ".yaml":
            if relative.parts != ("knowledge", "sources", target.name):
                raise ValueError("Sources must be stored directly under knowledge/sources/")
            row = self._source_row(target) if target.is_file() else None
            with self.connection:
                self.connection.execute("DELETE FROM source_index WHERE entity_id = ?", (target.stem,))
                self.connection.execute("DELETE FROM source_fts WHERE entity_id = ?", (target.stem,))
                if row is not None:
                    self._insert_source(row)
        elif category == "taxonomy" and target.suffix.lower() == ".yaml":
            if relative.parts not in {
                ("knowledge", "taxonomy", "domains.yaml"),
                ("knowledge", "taxonomy", "topics.yaml"),
                ("knowledge", "taxonomy", "tags.yaml"),
            }:
                raise ValueError("Taxonomy updates must target a canonical registry file")
            rows = self._read_taxonomy_rows()
            with self.connection:
                self.connection.execute("DELETE FROM taxonomy_index")
                self.connection.executemany(
                    "INSERT INTO taxonomy_index (kind, entity_id, title) VALUES (?, ?, ?)",
                    rows,
                )
        else:
            raise ValueError("Unsupported canonical path for incremental indexing: {}".format(relative))

        counts = self._counts()
        return IndexBuildSummary(**counts)

    def incremental_update(self, path: Union[str, Path]) -> IndexBuildSummary:
        return self.update_path(path)

    def backlinks_for(self, term_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT source_entity_type, source_entity_id, source_path,
                      link_target, label, line
               FROM backlink_index WHERE term_id = ?
               ORDER BY source_entity_type, source_entity_id, line""",
            (term_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _snapshot(self):
        markdown = self._read_all_markdown()
        documents = [self._document_row(row) for row in markdown if row.entity_type == "document"]
        terms = [self._term_row(row) for row in markdown if row.entity_type == "term"]
        sources = self._read_all_sources()
        taxonomy = self._read_taxonomy_rows()
        return documents, terms, sources, taxonomy, markdown

    def _read_all_markdown(self) -> List[_MarkdownRecord]:
        records = []
        documents_root = self.knowledge_root / "documents"
        if documents_root.exists():
            for path in sorted(documents_root.rglob("*.md")):
                records.append(self._read_markdown_record(path, "document"))
        terms_root = self.knowledge_root / "terms"
        if terms_root.exists():
            for path in sorted(terms_root.glob("*.md")):
                records.append(self._read_markdown_record(path, "term"))
        identifiers = [(row.entity_type, row.entity_id) for row in records]
        if len(identifiers) != len(set(identifiers)):
            raise IndexBuildError("Canonical Markdown contains duplicate IDs")
        return records

    def _read_markdown_record(self, path: Path, entity_type: str) -> _MarkdownRecord:
        try:
            content_bytes = path.read_bytes()
            text = content_bytes.decode("utf-8")
            parsed = parse_markdown(text)
            if parsed.frontmatter is None:
                raise ValueError("missing or invalid YAML frontmatter")
            metadata = (
                DocumentMetadata.model_validate(parsed.frontmatter)
                if entity_type == "document"
                else TermMetadata.model_validate(parsed.frontmatter)
            )
            if path.stem != metadata.id:
                raise ValueError("filename does not match metadata id")
            if entity_type == "document":
                expected_parent = {
                    "paper-note": "papers",
                    "learning-note": "learning",
                    "course-note": "courses",
                }[metadata.type]
                relative = path.relative_to(self.knowledge_root)
                if relative.parts[:2] != ("documents", expected_parent) or len(relative.parts) != 3:
                    raise ValueError("document is not under its canonical type directory")
            else:
                relative = path.relative_to(self.knowledge_root)
                if relative.parts != ("terms", path.name):
                    raise ValueError("term is not directly under knowledge/terms/")
        except Exception as error:
            raise IndexBuildError("Cannot index {}: {}".format(path, error)) from error

        body = _markdown_body(text, parsed)
        return _MarkdownRecord(
            entity_type=entity_type,
            entity_id=metadata.id,
            path=path.relative_to(self.repository_root).as_posix(),
            title=metadata.title,
            metadata=metadata,
            parsed=parsed,
            text=text,
            body=body,
            content_hash=hashlib.sha256(content_bytes).hexdigest(),
        )

    def _read_all_sources(self) -> List[dict]:
        directory = self.knowledge_root / "sources"
        rows = []
        if not directory.exists():
            return rows
        seen = set()
        for path in sorted(directory.glob("*.yaml")):
            row = self._source_row(path)
            if row["entity_id"] in seen:
                raise IndexBuildError("Source registry contains duplicate IDs")
            seen.add(row["entity_id"])
            rows.append(row)
        return rows

    def _source_row(self, path: Path) -> dict:
        try:
            relative = path.relative_to(self.knowledge_root)
            if relative.parts != ("sources", path.name) or path.suffix.lower() != ".yaml":
                raise ValueError("Source must be knowledge/sources/<id>.yaml")
            content = path.read_bytes()
            metadata = SourceMetadata.model_validate(parse_yaml(content.decode("utf-8")))
            if path.stem != metadata.id:
                raise ValueError("filename does not match metadata id")
        except Exception as error:
            raise IndexBuildError("Cannot index Source {}: {}".format(path, error)) from error
        value = metadata.model_dump(mode="json", exclude_none=True)
        return {
            "entity_id": metadata.id,
            "path": path.relative_to(self.repository_root).as_posix(),
            "title": metadata.title,
            "source_type": metadata.type,
            "metadata_json": _json(value),
            "content_hash": hashlib.sha256(content).hexdigest(),
        }

    def _read_taxonomy_rows(self) -> List[Tuple[str, str, str]]:
        try:
            registry = TaxonomyRegistry.load(self.knowledge_root / "taxonomy")
        except Exception as error:
            raise IndexBuildError("Cannot index Taxonomy: {}".format(error)) from error
        return [
            (record.kind, record.entry.id, record.entry.title)
            for record in registry.records
        ]

    def _document_row(self, record: _MarkdownRecord) -> dict:
        metadata = record.metadata.model_dump(mode="json", exclude_none=True)
        return {
            "entity_id": record.entity_id,
            "path": record.path,
            "title": record.title,
            "document_type": metadata["type"],
            "metadata_json": _json(metadata),
            "content_hash": record.content_hash,
            "body": record.body,
        }

    def _term_row(self, record: _MarkdownRecord) -> dict:
        metadata = record.metadata.model_dump(mode="json", exclude_none=True)
        return {
            "entity_id": record.entity_id,
            "path": record.path,
            "title": record.title,
            "term_type": metadata["type"],
            "depth": metadata["depth"],
            "aliases": list(metadata.get("aliases", [])),
            "metadata_json": _json(metadata),
            "content_hash": record.content_hash,
            "body": record.body,
        }

    def _insert_document(self, row: dict) -> None:
        self.connection.execute(
            """INSERT INTO document_index (
                   entity_id, path, title, document_type, metadata_json, content_hash
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                row["entity_id"], row["path"], row["title"], row["document_type"],
                row["metadata_json"], row["content_hash"],
            ),
        )
        self.connection.execute(
            "INSERT INTO document_fts (entity_id, title, body, metadata) VALUES (?, ?, ?, ?)",
            (row["entity_id"], row["title"], row["body"], row["metadata_json"]),
        )

    def _insert_term(self, row: dict) -> None:
        self.connection.execute(
            """INSERT INTO term_index (
                   entity_id, path, title, term_type, depth, aliases_json,
                   metadata_json, content_hash
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["entity_id"], row["path"], row["title"], row["term_type"],
                row["depth"], _json(row["aliases"]), row["metadata_json"], row["content_hash"],
            ),
        )
        inserted_aliases = set()
        for alias in row["aliases"]:
            normalized = normalize_key(alias)
            if normalized and normalized not in inserted_aliases:
                self.connection.execute(
                    "INSERT INTO alias_index (term_id, alias, normalized_alias) VALUES (?, ?, ?)",
                    (row["entity_id"], alias, normalized),
                )
                inserted_aliases.add(normalized)
        self.connection.execute(
            "INSERT INTO term_fts (entity_id, title, aliases, body, metadata) VALUES (?, ?, ?, ?, ?)",
            (
                row["entity_id"], row["title"], " ".join(row["aliases"]),
                row["body"], row["metadata_json"],
            ),
        )

    def _insert_source(self, row: dict) -> None:
        self.connection.execute(
            """INSERT INTO source_index (
                   entity_id, path, title, source_type, metadata_json, content_hash
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                row["entity_id"], row["path"], row["title"], row["source_type"],
                row["metadata_json"], row["content_hash"],
            ),
        )
        self.connection.execute(
            "INSERT INTO source_fts (entity_id, title, metadata) VALUES (?, ?, ?)",
            (row["entity_id"], row["title"], row["metadata_json"]),
        )

    def _relations(self, markdown: List[_MarkdownRecord], term_rows: List[_MarkdownRecord]):
        terms = tuple(row.metadata for row in term_rows)
        registry = TermRegistry(terms, AliasIndex.from_terms(terms))
        resolver = TermResolver(registry)
        backlinks = []
        evidence = []
        for record in markdown:
            for link in record.parsed.wiki_links:
                resolution = resolver.resolve(link.target)
                if resolution.status != "resolved":
                    continue
                term_id = resolution.entity_id
                row_id = _stable_id(
                    record.entity_type, record.entity_id, "link", link.line,
                    link.start, link.end, link.target,
                )
                backlinks.append(
                    (
                        row_id, record.entity_type, record.entity_id, record.path,
                        term_id, link.target, link.label, link.line,
                    )
                )
            lines = record.text.splitlines()
            for ordinal, citation in enumerate(record.parsed.citations):
                line_text = lines[citation.line - 1] if 0 < citation.line <= len(lines) else ""
                claim = line_text.replace(citation.raw, "").strip(" \t.,;:—–-")
                row_id = _stable_id(
                    record.entity_type, record.entity_id, "citation", citation.line,
                    ordinal, citation.raw,
                )
                evidence.append(
                    (
                        row_id, record.entity_type, record.entity_id, record.path,
                        citation.source_id, citation.locator, citation.line,
                        citation.raw, claim or line_text.strip(),
                    )
                )
        return backlinks, evidence

    def _insert_relations(self, backlinks, evidence) -> None:
        self.connection.executemany(
            """INSERT INTO backlink_index (
                   id, source_entity_type, source_entity_id, source_path, term_id,
                   link_target, label, line
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            backlinks,
        )
        self.connection.executemany(
            """INSERT INTO evidence_index (
                   id, entity_type, entity_id, entity_path, source_id, locator,
                   line, citation, claim
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            evidence,
        )
        self.connection.executemany(
            "INSERT INTO evidence_fts (evidence_id, entity_id, claim) VALUES (?, ?, ?)",
            [(row[0], row[2], row[8]) for row in evidence],
        )

    def _replace_relations(self, backlinks, evidence) -> None:
        self.connection.execute("DELETE FROM backlink_index")
        self.connection.execute("DELETE FROM evidence_index")
        self.connection.execute("DELETE FROM evidence_fts")
        self._insert_relations(backlinks, evidence)

    def _clear_derived_indexes(self) -> None:
        for table in (
            "document_index", "term_index", "source_index", "alias_index",
            "taxonomy_index", "backlink_index", "evidence_index",
            "document_fts", "term_fts", "source_fts", "evidence_fts",
        ):
            self.connection.execute("DELETE FROM {}".format(table))

    def _sync_document_stats(self) -> None:
        self.connection.execute("DELETE FROM document_stats")
        self.connection.execute(
            """INSERT INTO document_stats (
                   document_id, view_count, search_click_count, last_viewed_at
               )
               SELECT entity_id,
                      SUM(CASE WHEN event_type = 'document_open' THEN 1 ELSE 0 END),
                      SUM(CASE WHEN event_type = 'search_result_click' THEN 1 ELSE 0 END),
                      MAX(CASE WHEN event_type = 'document_open' THEN created_at ELSE NULL END)
               FROM usage_events
               WHERE entity_type = 'document'
                 AND entity_id IN (SELECT entity_id FROM document_index)
               GROUP BY entity_id
               ON CONFLICT(document_id) DO UPDATE SET
                   view_count = excluded.view_count,
                   search_click_count = excluded.search_click_count,
                   last_viewed_at = excluded.last_viewed_at"""
        )

    def _counts(self) -> dict:
        def count(table):
            return self.connection.execute("SELECT COUNT(*) FROM {}".format(table)).fetchone()[0]

        return {
            "documents": count("document_index"),
            "terms": count("term_index"),
            "aliases": count("alias_index"),
            "taxonomy_entries": count("taxonomy_index"),
            "backlinks": count("backlink_index"),
            "evidence": count("evidence_index"),
            "sources": count("source_index"),
        }

    def _canonical_path(self, path: Union[str, Path]):
        supplied = Path(path)
        target = supplied if supplied.is_absolute() else self.repository_root / supplied
        target = Path(target.resolve())
        try:
            relative = target.relative_to(self.repository_root)
        except ValueError as error:
            raise ValueError("Indexer path must remain inside the repository") from error
        if any(part in {".git", "runtime", "storage"} for part in relative.parts):
            raise ValueError("Runtime, storage, and Git data cannot be indexed")
        return target, relative


def _markdown_body(text: str, parsed: MarkdownDocument) -> str:
    lines = text.lstrip("\ufeff").splitlines()
    if parsed.frontmatter_end_line is None:
        return text
    return "\n".join(lines[parsed.frontmatter_end_line :]).strip()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(*parts) -> str:
    value = "\0".join(str(part) for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
