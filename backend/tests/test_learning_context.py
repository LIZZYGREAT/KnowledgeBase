from pathlib import Path

import pytest

from backend.app.services.learning_context_service import (
    LearningContextError,
    LearningContextService,
)


def _document(root: Path, document_id: str, title: str, kind: str = "learning-note"):
    folder = {
        "learning-note": "learning",
        "paper-note": "papers",
        "course-note": "courses",
    }[kind]
    path = root / "knowledge" / "documents" / folder / "{}.md".format(document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nschema_version: 1\nid: {}\ntitle: {}\ntype: {}\ndomains: []\n"
        "topics: []\ntags: []\nsources: []\n---\n\n# {}\n\n正文内容。\n".format(
            document_id, title, kind, title
        ),
        encoding="utf-8",
    )
    return path


def test_first_read_has_empty_scope_and_does_not_create_storage(tmp_path):
    _document(tmp_path, "selected-note", "已发布学习笔记")
    service = LearningContextService(tmp_path)

    overview = service.get_overview()

    assert overview["sources"]["included_document_ids"] == []
    assert overview["sources"]["available_documents"] == [
        {"id": "selected-note", "title": "已发布学习笔记", "type": "learning-note"}
    ]
    assert overview["active"] == ""
    assert overview["important"] == ""
    assert overview["status"]["state"] == "not_synced"
    assert not (tmp_path / "storage" / "learning-context").exists()


def test_only_valid_published_learning_document_ids_can_be_selected(tmp_path):
    _document(tmp_path, "paper-note", "论文笔记", "paper-note")
    _document(tmp_path, "course-note", "课程笔记", "course-note")
    service = LearningContextService(tmp_path)

    saved = service.set_sources(["course-note", "paper-note", "paper-note"])

    assert saved["included_document_ids"] == ["course-note", "paper-note"]
    assert {item["id"] for item in saved["available_documents"]} == {
        "course-note",
        "paper-note",
    }
    with pytest.raises(LearningContextError, match="existing canonical"):
        service.set_sources(["missing-note"])
    assert service.get_sources()["included_document_ids"] == ["course-note", "paper-note"]


def test_unselected_course_note_never_becomes_a_progress_source(tmp_path):
    _document(tmp_path, "learning-note", "学习笔记")
    _document(tmp_path, "course-note", "课程笔记", "course-note")
    service = LearningContextService(tmp_path)

    assert service.get_context()["included_sources"] == []
    service.set_sources(["learning-note"])
    context = service.get_context()
    assert [item["id"] for item in context["included_sources"]] == ["learning-note"]


def test_preferences_are_normalized_and_do_not_create_mastery_evidence(tmp_path):
    service = LearningContextService(tmp_path)

    saved = service.set_preferences(
        {
            "fixed_direction": "  Continual   Learning ",
            "keywords": ["EWC", " ewc ", "持续学习"],
            "exclude_keywords": ["RLHF"],
            "exploration_directions": ["Reinforcement Learning basics"],
            "important_anchors": ["Replay"],
        }
    )

    assert saved["fixed_direction"] == "Continual Learning"
    assert saved["keywords"] == ["EWC", "持续学习"]
    assert service.get_context()["included_sources"] == []


def test_context_assembly_reads_only_relevant_layers_and_topics(tmp_path):
    _document(tmp_path, "cl-note", "Continual Learning note")
    service = LearningContextService(tmp_path)
    context_root = tmp_path / "storage" / "learning-context"
    (context_root / "topics").mkdir(parents=True)
    (context_root / "active.md").write_text("# 当前方向\n\nEWC 与持续学习。\n", encoding="utf-8")
    (context_root / "important.md").write_text("# 稳定知识\n\nReplay。\n", encoding="utf-8")
    (context_root / "topics" / "continual-learning.md").write_text(
        "# 持续学习\n\nEWC、GEM 与 iCaRL。\n", encoding="utf-8"
    )
    (context_root / "topics" / "ethernet.md").write_text(
        "# Ethernet\n\n课程笔记不应混入。\n", encoding="utf-8"
    )
    (context_root / "index.yaml").write_text(
        "topics:\n"
        "  - id: continual-learning\n"
        "    title: 持续学习\n"
        "    aliases: [continual learning]\n"
        "    keywords: [EWC, GEM, iCaRL]\n"
        "  - id: ethernet\n"
        "    title: Ethernet\n"
        "    aliases: []\n"
        "    keywords: [networking]\n",
        encoding="utf-8",
    )

    result = service.get_context(focus="GEM continual learning")

    assert "EWC 与持续学习" in result["active"]
    assert result["important"] == ""
    assert [item["id"] for item in result["topics"]] == ["continual-learning"]
    assert "EWC、GEM 与 iCaRL" in result["topics"][0]["markdown"]


def test_topic_ids_cannot_escape_context_storage(tmp_path):
    service = LearningContextService(tmp_path)

    with pytest.raises(LearningContextError, match="Invalid topic ID"):
        service.read_topic("..\\outside")
