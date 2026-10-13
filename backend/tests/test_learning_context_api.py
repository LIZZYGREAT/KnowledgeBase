from pathlib import Path
import asyncio
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api.learning_context import (
    SyncRequest,
    get_learning_context,
    router,
    sync_learning_context,
)
from backend.app.api.research import list_profiles
from backend.app.services.learning_context_service import LearningContextService
from backend.app.services.learning_context_sync_entries import render_entry


def _document(root: Path, document_id: str = "gem-note"):
    path = root / "knowledge" / "documents" / "learning" / "{}.md".format(document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nschema_version: 1\nid: {}\ntitle: GEM Learning Note\n"
        "type: learning-note\ndomains: []\ntopics: []\ntags: []\nsources: []\n---\n"
        "\n# GEM\n\nGradient projection protects previous tasks.\n".format(document_id),
        encoding="utf-8",
    )


def _client(root: Path, gateway=None):
    app = FastAPI()
    app.include_router(router)
    app.state.learning_context_service = LearningContextService(root, gateway)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, error: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(LookupError)
    async def lookup_error_handler(request: Request, error: LookupError):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    return TestClient(app)


def test_api_selection_and_preferences_are_saved_without_ai(tmp_path):
    _document(tmp_path)
    with _client(tmp_path) as client:
        initial = client.get("/api/learning-context")
        selected = client.put(
            "/api/learning-context/sources",
            json={"included_document_ids": ["gem-note"]},
        )
        preferences = client.put(
            "/api/learning-context/preferences",
            json={
                "fixed_direction": "continual learning",
                "keywords": ["GEM", "EWC"],
                "exclude_keywords": ["RLHF"],
                "exploration_directions": ["reinforcement learning basics"],
                "important_anchors": ["Replay"],
            },
        )
        overview = client.get("/api/learning-context")

    assert initial.status_code == 200
    assert initial.json()["sources"]["included_document_ids"] == []
    assert selected.status_code == 200
    assert selected.json()["included_document_ids"] == ["gem-note"]
    assert preferences.status_code == 200
    assert preferences.json()["keywords"] == ["GEM", "EWC"]
    assert overview.json()["status"]["state"] == "pending"
    assert overview.json()["preferences"]["fixed_direction"] == "continual learning"


def test_api_manual_note_is_saved_without_pinning_the_whole_layer(tmp_path):
    with _client(tmp_path) as client:
        saved = client.put(
            "/api/learning-context/memory/active",
            json={"markdown": "# 人工固定的方向\n\n保留这段内容。\n"},
        )
        overview = client.get("/api/learning-context")
        restored = client.post(
            "/api/learning-context/memory/active/restore-automatic"
        )
        after_restore = client.get("/api/learning-context")

    assert saved.status_code == 200
    assert saved.json()["pinned_entry_ids"] == []
    assert overview.json()["active"] == "# 人工固定的方向\n\n保留这段内容。\n"
    assert overview.json()["manual_entries"] == []
    assert restored.status_code == 200
    assert restored.json()["markdown"] == "# 人工固定的方向\n\n保留这段内容。\n"
    assert after_restore.json()["active"] == "# 人工固定的方向\n\n保留这段内容。\n"


def test_api_can_pin_and_restore_one_automatic_entry(tmp_path):
    context_root = tmp_path / "storage" / "learning-context"
    context_root.mkdir(parents=True)
    original = render_entry(
        {
            "entry_id": "current-direction",
            "owner": "auto",
            "source_headings": {"gem-note": ["Mechanism"]},
            "layer": "active",
            "title": "当前方向",
            "summary": "根据所选笔记生成。",
        }
    )
    (context_root / "active.md").write_text(
        original + "\n## 人工补充\n\n保留此说明。\n", encoding="utf-8"
    )
    edited = original.replace("根据所选笔记生成。", "我确认了这条方向。")
    with _client(tmp_path) as client:
        saved = client.put(
            "/api/learning-context/memory/active",
            json={"markdown": edited + "\n## 人工补充\n\n保留此说明。\n"},
        )
        pinned = client.get("/api/learning-context")
        restored = client.post(
            "/api/learning-context/memory/active/restore-automatic?entry_id=current-direction"
        )
        after = client.get("/api/learning-context")

    assert saved.status_code == 200
    assert saved.json()["pinned_entry_ids"] == ["current-direction"]
    assert pinned.json()["manual_entries"][0]["pinned"] is True
    assert "保留此说明。" in pinned.json()["active"]
    assert restored.status_code == 200
    assert after.json()["manual_entries"] == []
    assert "保留此说明。" in after.json()["active"]


def test_api_rejects_noncanonical_and_unknown_source_ids(tmp_path):
    _document(tmp_path)
    with _client(tmp_path) as client:
        unknown = client.put(
            "/api/learning-context/sources",
            json={"included_document_ids": ["not-a-document"]},
        )
        malformed = client.put(
            "/api/learning-context/sources",
            json={"included_document_ids": ["../secrets"]},
        )

    assert unknown.status_code == 422
    assert malformed.status_code == 422
    assert not (tmp_path / "storage" / "learning-context" / "sources.yaml").exists()


def test_api_edits_only_an_indexed_topic(tmp_path):
    context_root = tmp_path / "storage" / "learning-context"
    (context_root / "topics").mkdir(parents=True)
    (context_root / "index.yaml").write_text(
        "topics:\n  - id: continual-learning\n    title: 持续学习\n",
        encoding="utf-8",
    )
    (context_root / "topics" / "continual-learning.md").write_text(
        "# 自动整理\n\nGEM。\n", encoding="utf-8"
    )
    with _client(tmp_path) as client:
        topic = client.get("/api/learning-context/topics/continual-learning")
        saved = client.put(
            "/api/learning-context/topics/continual-learning",
            json={"markdown": "# 人工修订\n\nGEM 与 QP。\n"},
        )
        missing = client.put(
            "/api/learning-context/topics/unknown-topic",
            json={"markdown": "不能写入未登记专题。"},
        )

    assert topic.status_code == 200
    assert topic.json()["markdown"] == "# 自动整理\n\nGEM。\n"
    assert saved.status_code == 200
    assert saved.json()["pinned_entry_ids"] == []
    assert missing.status_code == 404
    assert (context_root / "topics" / "continual-learning.md").read_text(encoding="utf-8") == (
        "# 人工修订\n\nGEM 与 QP。\n"
    )


def test_api_manual_sync_dry_run_only_reports_local_changes(tmp_path):
    _document(tmp_path)
    with _client(tmp_path) as client:
        client.put(
            "/api/learning-context/sources",
            json={"included_document_ids": ["gem-note"]},
        )
        response = client.post("/api/learning-context/sync", json={"dry_run": True})
        invalid = client.post("/api/learning-context/sync", json={"force": "yes"})
        overview = client.get("/api/learning-context").json()

    assert response.status_code == 200
    assert response.json()["state"] == "dry_run"
    assert response.json()["source_results"][0]["action"] == "analyze"
    assert invalid.status_code == 422
    assert overview["status"]["state"] == "pending"
    assert "source_baselines" not in overview["status"]


def test_sync_endpoint_keeps_event_loop_responsive():
    sync_finished = threading.Event()
    started = threading.Event()
    loop = asyncio.new_event_loop()

    def blocking_sync(**_kwargs):
        started.set()
        time.sleep(0.08)
        sync_finished.set()
        return {"state": "synced"}

    service = SimpleNamespace(
        sync=blocking_sync,
        get_overview=lambda: {"status": {"state": "synced"}},
    )
    profile = SimpleNamespace(
        id="continual-learning",
        title="Continual Learning",
        description=None,
        enabled=True,
        schedule=SimpleNamespace(mode="manual"),
        search=SimpleNamespace(breadth="balanced"),
        lenses=[SimpleNamespace(id="main", enabled=True)],
        inbox=SimpleNamespace(max_new_candidates=10),
    )
    research_service = SimpleNamespace(
        profile_registry=SimpleNamespace(profiles=[profile]),
        profile_state_repository=SimpleNamespace(get=lambda _profile_id: None),
        run_repository=SimpleNamespace(list_for_profile=lambda _profile_id, limit: []),
        run_request_repository=SimpleNamespace(
            count_pending_and_claimed=lambda _profile_id: (0, 0)
        ),
        candidate_repository=SimpleNamespace(count_new=lambda _profile_id: 0),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                learning_context_service=service, research_service=research_service
            )
        )
    )

    async def exercise():
        sync_task = asyncio.create_task(sync_learning_context(SyncRequest(), request))
        started_in_time = await asyncio.to_thread(started.wait, 1)
        overview = await get_learning_context(request)
        profiles = await list_profiles(request)
        sync_still_running = not sync_finished.is_set()
        result = await sync_task
        return started_in_time, overview, profiles[0].id, sync_still_running, result

    try:
        result = loop.run_until_complete(exercise())
    finally:
        loop.close()

    assert result == (
        True,
        {"status": {"state": "synced"}},
        "continual-learning",
        True,
        {"state": "synced"},
    )
