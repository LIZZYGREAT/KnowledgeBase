"""SQLite persistence for Research Works and discovery provenance."""

from contextlib import contextmanager
import json
import sqlite3
import uuid
from typing import Iterator, Optional

from backend.app.domain.ai import ResearchCandidateAnalysisOutput
from backend.app.domain.research_runtime import (
    ResearchDiscoveryRecord,
    ResearchWorkAnalysisRecord,
    ResearchWorkRecord,
)


_IDENTIFIER_COLUMNS = ("doi", "arxiv_id", "openalex_id", "semantic_scholar_id")
_DISCOVERY_PROVIDER_ORDER = """CASE provider
    WHEN 'crossref' THEN 2
    WHEN 'openalex' THEN 1
    WHEN 'arxiv' THEN 0
    ELSE -1
END"""


class ResearchRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        """Serialize identity lookup and persistence in one short SQLite transaction."""
        if self.connection.in_transaction:
            savepoint = "research_{}".format(uuid.uuid4().hex)
            self.connection.execute("SAVEPOINT {}".format(savepoint))
            try:
                yield
            except BaseException:
                self.connection.execute("ROLLBACK TO SAVEPOINT {}".format(savepoint))
                self.connection.execute("RELEASE SAVEPOINT {}".format(savepoint))
                raise
            else:
                self.connection.execute("RELEASE SAVEPOINT {}".format(savepoint))
            return

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def find_by_identifiers(self, identifiers: dict[str, Optional[str]]) -> list[ResearchWorkRecord]:
        present = [
            (column, identifiers.get(column))
            for column in _IDENTIFIER_COLUMNS
            if identifiers.get(column) is not None
        ]
        if not present:
            return []
        where_clause = " OR ".join("{} = ?".format(column) for column, _ in present)
        rows = self.connection.execute(
            "SELECT * FROM research_works WHERE " + where_clause,
            tuple(value for _, value in present),
        ).fetchall()
        return [_work_from_row(row) for row in rows]

    def find_weak_candidates(self, normalized_title: str, year: int) -> list[ResearchWorkRecord]:
        rows = self.connection.execute(
            """SELECT * FROM research_works
               WHERE normalized_title = ? AND year BETWEEN ? AND ?
               ORDER BY id""",
            (normalized_title, year - 1, year + 1),
        ).fetchall()
        return [_work_from_row(row) for row in rows]

    def preferred_provider(self, work_id: str) -> Optional[str]:
        row = self.connection.execute(
            """SELECT provider FROM research_discoveries
               WHERE work_id = ?
               ORDER BY {} DESC, discovered_at DESC, id DESC
               LIMIT 1""".format(_DISCOVERY_PROVIDER_ORDER),
            (work_id,),
        ).fetchone()
        return row["provider"] if row else None

    def insert_work(self, work: ResearchWorkRecord) -> None:
        self.connection.execute(
            """INSERT INTO research_works (
                   id, canonical_key, title, normalized_title, abstract,
                   authors_json, year, published_at, venue, doi, arxiv_id,
                   openalex_id, semantic_scholar_id, url, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            _work_values(work),
        )

    def get_work(self, work_id: str) -> Optional[ResearchWorkRecord]:
        row = self.connection.execute(
            "SELECT * FROM research_works WHERE id = ?", (work_id,)
        ).fetchone()
        return _work_from_row(row) if row else None

    def update_work(self, work: ResearchWorkRecord) -> None:
        self.connection.execute(
            """UPDATE research_works SET
                   canonical_key = ?, title = ?, normalized_title = ?, abstract = ?,
                   authors_json = ?, year = ?, published_at = ?, venue = ?, doi = ?,
                   arxiv_id = ?, openalex_id = ?, semantic_scholar_id = ?, url = ?,
                   updated_at = ?
               WHERE id = ?""",
            (
                work.canonical_key,
                work.title,
                work.normalized_title,
                work.abstract,
                json.dumps(list(work.authors), ensure_ascii=False),
                work.year,
                work.published_at,
                work.venue,
                work.doi,
                work.arxiv_id,
                work.openalex_id,
                work.semantic_scholar_id,
                work.url,
                work.updated_at,
                work.id,
            ),
        )

    def add_discovery_if_missing(
        self, discovery: ResearchDiscoveryRecord
    ) -> tuple[ResearchDiscoveryRecord, bool]:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO research_discoveries (
                   id, work_id, profile_id, lens_id, provider, provider_record_id,
                   query_key, query_text, metadata_json, discovered_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                discovery.id,
                discovery.work_id,
                discovery.profile_id,
                discovery.lens_id,
                discovery.provider,
                discovery.provider_record_id,
                discovery.query_key,
                discovery.query_text,
                json.dumps(
                    discovery.metadata,
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                ),
                discovery.discovered_at,
            ),
        )
        persisted = (
            discovery
            if cursor.rowcount == 1
            else self.get_discovery(
                discovery.profile_id,
                discovery.lens_id,
                discovery.provider,
                discovery.provider_record_id,
                discovery.query_key,
            )
        )
        if persisted is None:
            raise RuntimeError("Research Discovery insert was ignored without a matching row")
        return persisted, cursor.rowcount == 1

    def get_discovery(
        self,
        profile_id: str,
        lens_id: str,
        provider: str,
        provider_record_id: str,
        query_key: str,
    ) -> Optional[ResearchDiscoveryRecord]:
        row = self.connection.execute(
            """SELECT * FROM research_discoveries
               WHERE profile_id = ? AND lens_id = ? AND provider = ?
                 AND provider_record_id = ? AND query_key = ?""",
            (profile_id, lens_id, provider, provider_record_id, query_key),
        ).fetchone()
        return _discovery_from_row(row) if row else None

    def list_discoveries_for_work(self, work_id: str) -> list[ResearchDiscoveryRecord]:
        rows = self.connection.execute(
            """SELECT * FROM research_discoveries WHERE work_id = ?
               ORDER BY discovered_at, id""",
            (work_id,),
        ).fetchall()
        return [_discovery_from_row(row) for row in rows]

    def list_discoveries_for_candidate_context(
        self, work_id: str, profile_id: str
    ) -> list[ResearchDiscoveryRecord]:
        rows = self.connection.execute(
            """SELECT * FROM research_discoveries
               WHERE work_id = ? AND profile_id = ?
               ORDER BY discovered_at, id""",
            (work_id, profile_id),
        ).fetchall()
        return [_discovery_from_row(row) for row in rows]

    def has_candidate_for_profile(self, work_id: str, profile_id: str) -> bool:
        row = self.connection.execute(
            """SELECT 1 FROM research_candidates
               WHERE work_id = ? AND profile_id = ? LIMIT 1""",
            (work_id, profile_id),
        ).fetchone()
        return row is not None

    def has_analysis_for_profile(
        self, work_id: str, profile_id: str, input_hash: Optional[str] = None
    ) -> bool:
        if input_hash is None:
            row = self.connection.execute(
                """SELECT 1 FROM research_work_analyses
                   WHERE work_id = ? AND profile_id = ? LIMIT 1""",
                (work_id, profile_id),
            ).fetchone()
        else:
            row = self.connection.execute(
                """SELECT 1 FROM research_work_analyses
                   WHERE work_id = ? AND profile_id = ? AND input_hash = ? LIMIT 1""",
                (work_id, profile_id, input_hash),
            ).fetchone()
        return row is not None

    def get_analysis(
        self, work_id: str, profile_id: str, input_hash: str
    ) -> Optional[ResearchWorkAnalysisRecord]:
        row = self.connection.execute(
            """SELECT * FROM research_work_analyses
               WHERE work_id = ? AND profile_id = ? AND input_hash = ?""",
            (work_id, profile_id, input_hash),
        ).fetchone()
        return _analysis_from_row(row) if row else None

    def get_analysis_by_id(self, analysis_id: str) -> Optional[ResearchWorkAnalysisRecord]:
        row = self.connection.execute(
            "SELECT * FROM research_work_analyses WHERE id = ?", (analysis_id,)
        ).fetchone()
        return _analysis_from_row(row) if row else None

    def list_entity_links(self, work_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT entity_type, entity_id, relation_type, created_at
               FROM research_entity_links WHERE work_id = ?
               ORDER BY created_at, entity_type, entity_id""",
            (work_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_links(self, candidate_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT id, group_id, draft_id, intended_entity_type,
                      intended_entity_id, relation_type, created_at
               FROM research_pending_links WHERE candidate_id = ?
               ORDER BY created_at, id""",
            (candidate_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_links_for_group(self, group_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT * FROM research_pending_links WHERE group_id = ?
               ORDER BY created_at, relation_type, id""",
            (group_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_all_pending_links(self) -> list[dict]:
        rows = self.connection.execute(
            """SELECT * FROM research_pending_links
               ORDER BY created_at, id"""
        ).fetchall()
        return [dict(row) for row in rows]

    def get_pending_link_for_candidate(
        self, candidate_id: str, relation_type: str
    ) -> Optional[dict]:
        row = self.connection.execute(
            """SELECT * FROM research_pending_links
               WHERE candidate_id = ? AND relation_type = ?
               ORDER BY created_at, id LIMIT 1""",
            (candidate_id, relation_type),
        ).fetchone()
        return dict(row) if row else None

    def get_pending_link_for_work(self, work_id: str, relation_type: str) -> Optional[dict]:
        row = self.connection.execute(
            """SELECT * FROM research_pending_links
               WHERE work_id = ? AND relation_type = ?
               ORDER BY created_at, id LIMIT 1""",
            (work_id, relation_type),
        ).fetchone()
        return dict(row) if row else None

    def add_pending_link(
        self,
        *,
        group_id: str,
        candidate_id: str,
        work_id: str,
        draft_id: str,
        intended_entity_type: str,
        intended_entity_id: str,
        relation_type: str,
        created_at: str,
    ) -> dict:
        self.connection.execute(
            """INSERT INTO research_pending_links (
                   id, group_id, candidate_id, work_id, draft_id,
                   intended_entity_type, intended_entity_id, relation_type,
                   created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(candidate_id, draft_id, relation_type) DO UPDATE SET
                   group_id = excluded.group_id,
                   intended_entity_type = excluded.intended_entity_type,
                   intended_entity_id = excluded.intended_entity_id""",
            (
                uuid.uuid4().hex,
                group_id,
                candidate_id,
                work_id,
                draft_id,
                intended_entity_type,
                intended_entity_id,
                relation_type,
                created_at,
            ),
        )
        row = self.connection.execute(
            """SELECT * FROM research_pending_links
               WHERE candidate_id = ? AND draft_id = ? AND relation_type = ?""",
            (candidate_id, draft_id, relation_type),
        ).fetchone()
        if row is None:
            raise RuntimeError("Research pending link was not persisted")
        link = dict(row)
        if link["work_id"] != work_id:
            raise ValueError("Research Draft is already linked to a different Work")
        return link

    def pending_links_for_drafts(self, draft_ids: tuple[str, ...]) -> list[dict]:
        if not draft_ids:
            return []
        placeholders = ", ".join("?" for _ in draft_ids)
        rows = self.connection.execute(
            """SELECT * FROM research_pending_links
               WHERE draft_id IN ({})
               ORDER BY group_id, work_id, relation_type, id""".format(placeholders),
            draft_ids,
        ).fetchall()
        return [dict(row) for row in rows]

    def add_entity_link(
        self,
        *,
        work_id: str,
        entity_type: str,
        entity_id: str,
        relation_type: str,
        created_at: str,
    ) -> None:
        self.connection.execute(
            """INSERT OR IGNORE INTO research_entity_links (
                   id, work_id, entity_type, entity_id, relation_type, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, work_id, entity_type, entity_id, relation_type, created_at),
        )

    def delete_pending_links_for_drafts(self, draft_ids: tuple[str, ...]) -> int:
        if not draft_ids:
            return 0
        placeholders = ", ".join("?" for _ in draft_ids)
        cursor = self.connection.execute(
            "DELETE FROM research_pending_links WHERE draft_id IN ({})".format(placeholders),
            draft_ids,
        )
        return cursor.rowcount

    def delete_pending_link_ids(self, pending_ids: tuple[str, ...]) -> int:
        if not pending_ids:
            return 0
        placeholders = ", ".join("?" for _ in pending_ids)
        cursor = self.connection.execute(
            "DELETE FROM research_pending_links WHERE id IN ({})".format(placeholders),
            pending_ids,
        )
        return cursor.rowcount

    def add_analysis_if_missing(
        self, analysis: ResearchWorkAnalysisRecord
    ) -> tuple[ResearchWorkAnalysisRecord, bool]:
        values = _analysis_values(analysis)
        with self.write_transaction():
            cursor = self.connection.execute(
                """INSERT OR IGNORE INTO research_work_analyses (
                       id, work_id, profile_id, input_hash, outcome, analysis_json,
                       provider, model, prompt_version, analysis_version,
                       context_entity_ids_json, analyzed_at, input_context_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            inserted = cursor.rowcount == 1
            persisted = (
                analysis
                if inserted
                else self.get_analysis(analysis.work_id, analysis.profile_id, analysis.input_hash)
            )
        if persisted is None:
            raise RuntimeError("Research Analysis insert was ignored without a matching row")
        return persisted, inserted


def _work_values(work: ResearchWorkRecord) -> tuple:
    return (
        work.id,
        work.canonical_key,
        work.title,
        work.normalized_title,
        work.abstract,
        json.dumps(list(work.authors), ensure_ascii=False),
        work.year,
        work.published_at,
        work.venue,
        work.doi,
        work.arxiv_id,
        work.openalex_id,
        work.semantic_scholar_id,
        work.url,
        work.created_at,
        work.updated_at,
    )


def _work_from_row(row: sqlite3.Row) -> ResearchWorkRecord:
    return ResearchWorkRecord(
        id=row["id"],
        canonical_key=row["canonical_key"],
        title=row["title"],
        normalized_title=row["normalized_title"],
        abstract=row["abstract"],
        authors=tuple(json.loads(row["authors_json"])),
        year=row["year"],
        published_at=row["published_at"],
        venue=row["venue"],
        doi=row["doi"],
        arxiv_id=row["arxiv_id"],
        openalex_id=row["openalex_id"],
        semantic_scholar_id=row["semantic_scholar_id"],
        url=row["url"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _discovery_from_row(row: sqlite3.Row) -> ResearchDiscoveryRecord:
    return ResearchDiscoveryRecord(
        id=row["id"],
        work_id=row["work_id"],
        profile_id=row["profile_id"],
        lens_id=row["lens_id"],
        provider=row["provider"],
        provider_record_id=row["provider_record_id"],
        query_key=row["query_key"],
        query_text=row["query_text"],
        metadata=json.loads(row["metadata_json"]),
        discovered_at=row["discovered_at"],
    )


def _analysis_values(analysis: ResearchWorkAnalysisRecord) -> tuple:
    return (
        analysis.id,
        analysis.work_id,
        analysis.profile_id,
        analysis.input_hash,
        analysis.outcome,
        json.dumps(
            analysis.analysis.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
        analysis.provider,
        analysis.model,
        analysis.prompt_version,
        analysis.analysis_version,
        json.dumps(list(analysis.context_entity_ids), ensure_ascii=False),
        analysis.analyzed_at,
        json.dumps(
            analysis.input_context,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        ),
    )


def _analysis_from_row(row: sqlite3.Row) -> ResearchWorkAnalysisRecord:
    return ResearchWorkAnalysisRecord(
        id=row["id"],
        work_id=row["work_id"],
        profile_id=row["profile_id"],
        input_hash=row["input_hash"],
        outcome=row["outcome"],
        analysis=ResearchCandidateAnalysisOutput.model_validate(
            json.loads(row["analysis_json"])
        ),
        provider=row["provider"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        analysis_version=row["analysis_version"],
        context_entity_ids=tuple(json.loads(row["context_entity_ids_json"])),
        analyzed_at=row["analyzed_at"],
        input_context=json.loads(row["input_context_json"]),
    )
