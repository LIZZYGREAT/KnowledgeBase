import json
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.ui import router
from backend.app.services.ui_summary_service import UiSummaryService


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE term_candidates (status TEXT NOT NULL);
        CREATE TABLE proposals (status TEXT NOT NULL);
        CREATE TABLE presentation_annotations (status TEXT NOT NULL);
        CREATE TABLE import_items (status TEXT NOT NULL);
        CREATE TABLE research_candidates (profile_id TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE document_index (metadata_json TEXT NOT NULL);
        CREATE TABLE term_index (metadata_json TEXT NOT NULL);
        CREATE TABLE source_index (metadata_json TEXT NOT NULL);
        """
    )
    return connection


def test_ui_summary_returns_only_lightweight_counts():
    connection = _connection()
    connection.executemany(
        "INSERT INTO term_candidates VALUES (?)",
        [("pending",), ("drafting",), ("accepted",)],
    )
    connection.executemany(
        "INSERT INTO proposals VALUES (?)", [("proposed",), ("drafted",), ("merged",)]
    )
    connection.executemany(
        "INSERT INTO presentation_annotations VALUES (?)", [("stale",), ("active",)]
    )
    connection.executemany(
        "INSERT INTO import_items VALUES (?)",
        [("ready",), ("needs_review",), ("drafted",)],
    )
    connection.executemany(
        "INSERT INTO research_candidates VALUES (?, ?)",
        [
            ("research-main", "new"),
            ("research-main", "new"),
            ("research-main", "shortlisted"),
            ("retired-profile", "new"),
        ],
    )
    connection.executemany(
        "INSERT INTO document_index VALUES (?)",
        [
            (json.dumps({"review": {"human": {"status": "unreviewed"}}}),),
            (json.dumps({"review": {"human": {"status": "approved"}}, "maintenance": {"status": "needs_revision"}}),),
            (json.dumps({"review": {"human": {"status": "approved"}}}),),
        ],
    )
    connection.execute(
        "INSERT INTO term_index VALUES (?)",
        (json.dumps({"review": {"human": {"status": "approved"}}, "maintenance": {"status": "needs_revision"}}),),
    )
    connection.execute(
        "INSERT INTO source_index VALUES (?)",
        (json.dumps({"metadata_review": {"status": "unreviewed"}}),),
    )
    profile = SimpleNamespace(
        id="research-main",
        inbox=SimpleNamespace(max_new_candidates=5),
    )

    summary = UiSummaryService(connection, [profile]).get_summary()

    assert summary == {
        "terms_open": 2,
        "terms_pending": 1,
        "term_drafts": 1,
        "research_new": 2,
        "research_capacity": 5,
        "research_profiles": 1,
        "pending_imports": 2,
        "maintenance": 7,
    }
    assert all(type(value) is int for value in summary.values())
    connection.close()


def test_ui_summary_api_exposes_counts_without_entity_payloads():
    application = FastAPI()
    application.include_router(router)
    application.state.ui_summary_service = SimpleNamespace(
        get_summary=lambda: {
            "terms_open": 0,
            "terms_pending": 0,
            "term_drafts": 0,
            "research_new": 0,
            "research_capacity": 0,
            "research_profiles": 0,
            "pending_imports": 0,
            "maintenance": 0,
        }
    )

    with TestClient(application) as client:
        response = client.get("/api/ui/summary")

    assert response.status_code == 200
    assert set(response.json()) == {
        "terms_open",
        "terms_pending",
        "term_drafts",
        "research_new",
        "research_capacity",
        "research_profiles",
        "pending_imports",
        "maintenance",
    }
    assert all(type(value) is int for value in response.json().values())
