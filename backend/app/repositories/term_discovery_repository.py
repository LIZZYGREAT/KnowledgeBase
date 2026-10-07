"""SQLite storage for Term Discovery settings, corpus state, and run history."""

from datetime import datetime, timezone
import json
import sqlite3
from typing import Optional

from backend.app.domain.term_discovery import (
    TermDiscoveryRun,
    TermDiscoveryRunItem,
    TermDiscoverySettings,
)
from backend.app.domain.term_runtime import TermDiscoveryAssessment


class TermDiscoveryRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get_settings(self) -> TermDiscoverySettings:
        row = self.connection.execute(
            "SELECT * FROM term_discovery_settings WHERE id = 1"
        ).fetchone()
        if row is None:
            return TermDiscoverySettings()
        return TermDiscoverySettings.model_validate(
            {
                "enabled_lanes": json.loads(row["enabled_lanes_json"]),
                "daily_max_new": json.loads(row["quota_json"])["daily_max_new"],
                "lane_capacities": json.loads(row["quota_json"])["lane_capacities"],
                "source_preferences": json.loads(row["source_preferences_json"]),
                "focus_override": row["focus_override"],
                "external_enabled": bool(row["external_enabled"]),
            }
        )

    def save_settings(self, settings: TermDiscoverySettings, updated_at: Optional[str] = None) -> None:
        now = updated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        quota = {
            "daily_max_new": settings.daily_max_new,
            "lane_capacities": settings.lane_capacities,
        }
        with self.connection:
            self.connection.execute(
                """INSERT INTO term_discovery_settings (
                       id, enabled_lanes_json, quota_json, source_preferences_json,
                       focus_override, external_enabled, updated_at
                   ) VALUES (1, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       enabled_lanes_json = excluded.enabled_lanes_json,
                       quota_json = excluded.quota_json,
                       source_preferences_json = excluded.source_preferences_json,
                       focus_override = excluded.focus_override,
                       external_enabled = excluded.external_enabled,
                       updated_at = excluded.updated_at""",
                (
                    json.dumps(settings.enabled_lanes, ensure_ascii=False),
                    json.dumps(quota, ensure_ascii=False, sort_keys=True),
                    json.dumps(settings.source_preferences, ensure_ascii=False),
                    settings.focus_override,
                    int(settings.external_enabled),
                    now,
                ),
            )

    def get_analysis_state(self, source_id: str, lane: str) -> Optional[dict]:
        row = self.connection.execute(
            """SELECT source_id, text_hash, focus_hash, analysis_lane,
                      analysis_version, analyzed_at
               FROM corpus_analysis_state
               WHERE source_id = ? AND analysis_lane = ?""",
            (source_id, lane),
        ).fetchone()
        return dict(row) if row is not None else None

    def save_analysis_state(
        self, source_id: str, text_hash: str, focus_hash: str,
        lane: str, analysis_version: int, analyzed_at: str,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO corpus_analysis_state (
                       source_id, text_hash, focus_hash, analysis_lane,
                       analysis_version, analyzed_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_id, analysis_lane) DO UPDATE SET
                       text_hash = excluded.text_hash,
                       focus_hash = excluded.focus_hash,
                       analysis_version = excluded.analysis_version,
                       analyzed_at = excluded.analyzed_at""",
                (source_id, text_hash, focus_hash, lane, analysis_version, analyzed_at),
            )

    def replace_vocabulary_source_statistics(
        self, source_id: str, text_hash: str, counts: dict[str, tuple[str, int]], updated_at: str
    ) -> bool:
        state = self.get_analysis_state(source_id, "vocabulary")
        if state is not None and state["text_hash"] == text_hash:
            return False
        with self.connection:
            self.connection.execute(
                "DELETE FROM vocabulary_source_statistics WHERE source_id = ?",
                (source_id,),
            )
            self.connection.executemany(
                """INSERT INTO vocabulary_source_statistics (
                       source_id, normalized_term, display_term, term_count,
                       text_hash, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (source_id, normalized, display, count, text_hash, updated_at)
                    for normalized, (display, count) in counts.items()
                ],
            )
            self.connection.execute(
                """INSERT INTO corpus_analysis_state (
                       source_id, text_hash, focus_hash, analysis_lane,
                       analysis_version, analyzed_at
                   ) VALUES (?, ?, '', 'vocabulary', 1, ?)
                   ON CONFLICT(source_id, analysis_lane) DO UPDATE SET
                       text_hash = excluded.text_hash,
                       analysis_version = excluded.analysis_version,
                       analyzed_at = excluded.analyzed_at""",
                (source_id, text_hash, updated_at),
            )
        return True

    def vocabulary_candidates(self, limit: int = 50) -> list[dict]:
        rows = self.connection.execute(
            """SELECT normalized_term, MIN(display_term) AS display_term,
                      SUM(term_count) AS total_count,
                      COUNT(DISTINCT source_id) AS document_frequency,
                      GROUP_CONCAT(source_id, ',') AS source_ids
               FROM vocabulary_source_statistics
               GROUP BY normalized_term
               HAVING COUNT(DISTINCT source_id) >= 2 OR SUM(term_count) >= 8
               ORDER BY document_frequency DESC, total_count DESC, normalized_term
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def retain_vocabulary_sources(self, source_ids: set[str]) -> None:
        placeholders = ", ".join("?" for _ in source_ids)
        if not source_ids:
            with self.connection:
                self.connection.execute("DELETE FROM vocabulary_source_statistics")
            return
        with self.connection:
            self.connection.execute(
                "DELETE FROM vocabulary_source_statistics WHERE source_id NOT IN ({})".format(
                    placeholders
                ),
                tuple(sorted(source_ids)),
            )

    def open_candidate_count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) FROM term_candidates WHERE status IN ('pending', 'drafting')"
        ).fetchone()
        return int(row[0])

    def open_candidate_count_by_lane(self) -> dict[str, int]:
        counts = {"concept": 0, "entity": 0, "vocabulary": 0}
        rows = self.connection.execute(
            """SELECT suggested_type, COUNT(*) AS count FROM term_candidates
               WHERE status IN ('pending', 'drafting') GROUP BY suggested_type"""
        ).fetchall()
        for row in rows:
            if row["suggested_type"] in counts:
                counts[row["suggested_type"]] = int(row["count"])
        return counts

    def daily_candidate_count(self, day_start: str) -> int:
        row = self.connection.execute(
            """SELECT COALESCE(SUM(candidate_count), 0)
               FROM term_discovery_runs
               WHERE started_at >= ? AND status IN ('success', 'partial')""",
            (day_start,),
        ).fetchone()
        return int(row[0])

    def has_scheduled_run_since(self, day_start: str) -> bool:
        row = self.connection.execute(
            """SELECT 1 FROM term_discovery_runs
               WHERE trigger = 'scheduled' AND started_at >= ?
               LIMIT 1""",
            (day_start,),
        ).fetchone()
        return row is not None

    def save_run(self, run: TermDiscoveryRun) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT OR REPLACE INTO term_discovery_runs (
                       id, trigger, status, snapshot_json, lane_budgets_json,
                       raw_counts_json, filtered_counts_json, candidate_count,
                       started_at, finished_at, error_summary
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.id,
                    run.trigger,
                    run.status,
                    _json(run.snapshot),
                    _json(run.lane_budgets),
                    _json(run.raw_counts),
                    _json(run.filtered_counts),
                    run.candidate_count,
                    run.started_at,
                    run.finished_at,
                    run.error_summary,
                ),
            )
            self.connection.execute(
                "DELETE FROM term_discovery_run_items WHERE run_id = ?", (run.id,)
            )
            self.connection.executemany(
                """INSERT INTO term_discovery_run_items (
                       id, run_id, lane, source_id, mention, outcome,
                       candidate_id, assessment_json, rationale,
                       context_excerpt, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item.id,
                        item.run_id,
                        item.lane,
                        item.source_id,
                        item.mention,
                        item.outcome,
                        item.candidate_id,
                        _json(item.assessment.model_dump(mode="json")),
                        item.rationale,
                        item.context_excerpt,
                        item.created_at,
                    )
                    for item in run.items
                ],
            )

    def get_run(self, run_id: str) -> Optional[TermDiscoveryRun]:
        row = self.connection.execute(
            "SELECT * FROM term_discovery_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _run_from_row(row, self._items(run_id)) if row is not None else None

    def list_runs(self, limit: int = 20) -> list[TermDiscoveryRun]:
        rows = self.connection.execute(
            "SELECT * FROM term_discovery_runs ORDER BY started_at DESC, id LIMIT ?",
            (limit,),
        ).fetchall()
        return [_run_from_row(row, self._items(row["id"])) for row in rows]

    def _items(self, run_id: str) -> list[TermDiscoveryRunItem]:
        rows = self.connection.execute(
            """SELECT * FROM term_discovery_run_items
               WHERE run_id = ? ORDER BY rowid""",
            (run_id,),
        ).fetchall()
        return [
            TermDiscoveryRunItem(
                id=row["id"],
                run_id=row["run_id"],
                lane=row["lane"],
                source_id=row["source_id"],
                mention=row["mention"],
                outcome=row["outcome"],
                candidate_id=row["candidate_id"],
                assessment=TermDiscoveryAssessment.model_validate(
                    json.loads(row["assessment_json"])
                ),
                rationale=row["rationale"],
                context_excerpt=row["context_excerpt"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


def _run_from_row(row: sqlite3.Row, items: list[TermDiscoveryRunItem]) -> TermDiscoveryRun:
    return TermDiscoveryRun(
        id=row["id"],
        trigger=row["trigger"],
        status=row["status"],
        snapshot=json.loads(row["snapshot_json"]),
        lane_budgets=json.loads(row["lane_budgets_json"]),
        raw_counts=json.loads(row["raw_counts_json"]),
        filtered_counts=json.loads(row["filtered_counts_json"]),
        candidate_count=row["candidate_count"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error_summary=row["error_summary"],
        items=items,
    )


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
