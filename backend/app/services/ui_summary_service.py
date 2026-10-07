"""Lightweight aggregate counts for the global UI surfaces."""

import sqlite3
from typing import Iterable


class UiSummaryService:
    def __init__(self, connection: sqlite3.Connection, profiles: Iterable):
        self.connection = connection
        self.profiles = tuple(profiles)

    def get_summary(self) -> dict[str, int]:
        row = self.connection.execute(
            """SELECT
                   (SELECT COUNT(*) FROM term_candidates
                    WHERE status IN ('pending', 'drafting')) AS terms_open,
                   (SELECT COUNT(*) FROM term_candidates
                    WHERE status = 'pending') AS terms_pending,
                   (SELECT COUNT(*) FROM term_candidates
                    WHERE status = 'drafting') AS term_drafts,
                   (SELECT COUNT(*) FROM proposals
                    WHERE status IN ('proposed', 'drafted')) AS open_proposals,
                   (SELECT COUNT(*) FROM presentation_annotations
                    WHERE status = 'stale') AS stale_annotations,
                   (SELECT COUNT(*) FROM import_items
                    WHERE status IN ('ready', 'needs_review')) AS pending_imports,
                   (
                       SELECT COUNT(*) FROM document_index
                       WHERE COALESCE(
                           json_extract(metadata_json, '$.review.human.status'),
                           'unreviewed'
                       ) = 'unreviewed'
                          OR json_extract(metadata_json, '$.maintenance.status') = 'needs_revision'
                   ) + (
                       SELECT COUNT(*) FROM term_index
                       WHERE COALESCE(
                           json_extract(metadata_json, '$.review.human.status'),
                           'unreviewed'
                       ) = 'unreviewed'
                          OR json_extract(metadata_json, '$.maintenance.status') = 'needs_revision'
                   ) + (
                       SELECT COUNT(*) FROM source_index
                       WHERE COALESCE(
                           json_extract(metadata_json, '$.metadata_review.status'),
                           'unreviewed'
                       ) = 'unreviewed'
                          OR json_extract(metadata_json, '$.maintenance.status') = 'needs_revision'
                   ) AS entity_maintenance"""
        ).fetchone()

        profile_ids = {profile.id for profile in self.profiles}
        new_by_profile = self.connection.execute(
            """SELECT profile_id, COUNT(*) AS candidate_count
               FROM research_candidates
               WHERE status = 'new'
               GROUP BY profile_id"""
        ).fetchall()
        research_new = sum(
            int(item["candidate_count"])
            for item in new_by_profile
            if item["profile_id"] in profile_ids
        )
        profile_capacity = sum(
            profile.inbox.max_new_candidates for profile in self.profiles
        )

        return {
            "terms_open": int(row["terms_open"]),
            "terms_pending": int(row["terms_pending"]),
            "term_drafts": int(row["term_drafts"]),
            "research_new": research_new,
            "research_capacity": profile_capacity,
            "research_profiles": len(self.profiles),
            "pending_imports": int(row["pending_imports"]),
            # Link issues are deliberately excluded: they are currently discovered
            # by scanning canonical Markdown and do not have a persisted index.
            "maintenance": (
                int(row["entity_maintenance"])
                + int(row["open_proposals"])
                + int(row["stale_annotations"])
            ),
        }
