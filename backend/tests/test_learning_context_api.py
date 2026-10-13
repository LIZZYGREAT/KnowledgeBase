from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api.learning_context import router
from backend.app.services.learning_context_service import LearningContextService


def _document(root: Path, document_id: str = "gem-note"):
    path = root / "knowledge" / "documents" / "learning" / "{}.md".format(document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nschema_version: 1\nid: {}\ntitle: GEM Learning Note\n"
        "type: learning-note\ndomains: []\ntopics: []\ntags: []\nsources: []\n---\n"
        "\n# GEM\n\nGradient projection protects previous tasks.\n".format(document_id),
        encoding="utf-8",
    )


def _client(root: Path):
    app = FastAPI()
    app.include_router(router)
    app.state.learning_context_service = LearningContextService(root)

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


def test_api_memory_edit_is_pinned_until_user_restores_automatic_updates(tmp_path):
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
    assert saved.json()["user_managed"] is True
    assert overview.json()["active"] == "# 人工固定的方向\n\n保留这段内容。\n"
    assert "active.md" in overview.json()["user_managed_files"]
    assert restored.status_code == 200
    assert restored.json()["user_managed"] is False
    assert restored.json()["markdown"] == "# 人工固定的方向\n\n保留这段内容。\n"
    assert after_restore.json()["user_managed_files"] == []


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
    assert saved.json()["user_managed"] is True
    assert missing.status_code == 404
    assert (context_root / "topics" / "continual-learning.md").read_text(encoding="utf-8") == (
        "# 人工修订\n\nGEM 与 QP。\n"
    )
