from pathlib import Path
import json
import subprocess

import pytest

from backend.app.services.learning_context_service import (
    LearningContextError,
    LearningContextService,
)


class FakeLearningGateway:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, task_name, context):
        self.calls.append((task_name, context))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _sync_repo(tmp_path, body="## Mechanism\n\nGEM computes a projection to preserve previous tasks.\n"):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _document(tmp_path, "gem-note", "GEM Learning Note")
    path = tmp_path / "knowledge" / "documents" / "learning" / "gem-note.md"
    content = path.read_text(encoding="utf-8")
    frontmatter_end = content.index("\n---\n", 4) + len("\n---\n")
    content = content[:frontmatter_end] + "\n" + body
    path.write_text(content, encoding="utf-8")
    return path


def _topic_change(summary="GEM projects gradients into a feasible region."):
    return {
        "outcome": "knowledge_changed",
        "changes": [
            {
                "entry_id": "gem-gradient-projection",
                "action": "upsert",
                "title": "梯度投影",
                "summary": summary,
                "layer": "topic",
                "topic_id": "continual-learning",
                "topic_title": "持续学习",
                "rationale": "来源章节解释了该机制。",
            }
        ],
    }


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


def test_sync_analyzes_only_selected_note_once_and_persists_git_blob_baseline(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(_topic_change())
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])

    result = service.sync()

    assert result["state"] == "synced"
    assert result["analyzed_count"] == 1
    assert len(gateway.calls) == 1
    task_name, context = gateway.calls[0]
    assert task_name == "update_learning_context"
    assert context["source_document_id"] == "gem-note"
    assert len(context["changed_sections"]) == 1
    assert "preserve previous tasks" in context["changed_sections"][0]["after"]
    assert context["existing_related_memory"] == []

    context_root = tmp_path / "storage" / "learning-context"
    memory = (context_root / "topics" / "continual-learning.md").read_text(encoding="utf-8")
    state = json.loads((context_root / "state.json").read_text(encoding="utf-8"))
    baseline = state["source_baselines"]["gem-note"]
    blob = subprocess.run(
        ["git", "cat-file", "-p", baseline["git_blob"]],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout
    assert blob == path.read_bytes()
    reference = subprocess.run(
        ["git", "rev-parse", "--verify", "refs/learning-context/gem-note"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    ).stdout.decode("ascii").strip()
    assert reference == baseline["git_blob"]
    assert '"source_headings":{"gem-note":["Mechanism"]}' in memory
    assert "### 梯度投影" in memory


def test_sync_no_change_and_formatting_only_change_do_not_call_ai_or_rewrite_memory(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(_topic_change())
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    context_path = tmp_path / "storage" / "learning-context" / "topics" / "continual-learning.md"
    state_path = tmp_path / "storage" / "learning-context" / "state.json"
    original_memory = context_path.read_text(encoding="utf-8")
    original_state = state_path.read_text(encoding="utf-8")

    unchanged = service.sync()
    assert unchanged["analyzed_count"] == 0
    assert gateway.calls and len(gateway.calls) == 1
    assert context_path.read_text(encoding="utf-8") == original_memory
    assert state_path.read_text(encoding="utf-8") == original_state

    path.write_text(
        path.read_text(encoding="utf-8").replace("GEM computes", "**GEM** computes"),
        encoding="utf-8",
    )
    formatted = service.sync()

    assert formatted["skipped_count"] == 1
    assert len(gateway.calls) == 1
    assert context_path.read_text(encoding="utf-8") == original_memory
    current_hash = json.loads(state_path.read_text(encoding="utf-8"))["source_baselines"]["gem-note"]["content_sha256"]
    assert current_hash != json.loads(original_state)["source_baselines"]["gem-note"]["content_sha256"]


def test_sync_skips_small_wording_edits_but_analyzes_formula_and_negation_changes(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(_topic_change(), {"outcome": "no_change", "changes": []}, {"outcome": "no_change", "changes": []})
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()

    path.write_text(
        path.read_text(encoding="utf-8").replace("preserve previous tasks", "protect previous tasks"),
        encoding="utf-8",
    )
    minor = service.sync()
    assert minor["skipped_count"] == 1
    assert len(gateway.calls) == 1

    path.write_text(
        path.read_text(encoding="utf-8").replace("projection", "projection only when x<=0"),
        encoding="utf-8",
    )
    formula = service.sync()
    assert formula["analyzed_count"] == 1
    assert len(gateway.calls) == 2

    path.write_text(
        path.read_text(encoding="utf-8").replace("protect previous tasks", "do not protect previous tasks"),
        encoding="utf-8",
    )
    negation = service.sync()
    assert negation["analyzed_count"] == 1
    assert len(gateway.calls) == 3


def test_large_section_diff_sends_the_changed_tail_instead_of_truncating_it(tmp_path):
    paragraphs = "\n\n".join(
        "GEM mechanism paragraph {} describes the projection constraint.".format(index)
        for index in range(110)
    )
    path = _sync_repo(
        tmp_path,
        "## Mechanism\n\n{}\n\nFinal note: previous tasks remain protected.\n".format(paragraphs),
    )
    gateway = FakeLearningGateway(
        {"outcome": "no_change", "changes": []},
        {"outcome": "no_change", "changes": []},
    )
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Final note: previous tasks remain protected.",
            "Final note: the corrected theorem changes the constraint.",
        ),
        encoding="utf-8",
    )

    result = service.sync()

    assert result["analyzed_count"] == 1
    changed_sections = gateway.calls[1][1]["changed_sections"]
    assert len(changed_sections) == 1
    assert "corrected theorem changes the constraint" in changed_sections[0]["after"]
    assert len(changed_sections[0]["before"]) < 5000
    assert len(changed_sections[0]["after"]) < 5000


def test_failed_sync_keeps_context_and_last_successful_baseline_for_retry(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(
        _topic_change(), RuntimeError("provider unavailable"), _topic_change("The corrected condition is recorded.")
    )
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    context_path = tmp_path / "storage" / "learning-context" / "topics" / "continual-learning.md"
    state_path = tmp_path / "storage" / "learning-context" / "state.json"
    old_memory = context_path.read_text(encoding="utf-8")
    old_state = json.loads(state_path.read_text(encoding="utf-8"))
    old_baseline = old_state["source_baselines"]["gem-note"]
    path.write_text(path.read_text(encoding="utf-8") + "\nA corrected condition is important.\n", encoding="utf-8")

    failed = service.sync()

    new_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert failed["state"] == "failed"
    assert context_path.read_text(encoding="utf-8") == old_memory
    assert new_state["source_baselines"]["gem-note"] == old_baseline
    assert new_state["state"] == "failed"

    retried = service.sync()
    retried_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert retried["state"] == "synced"
    assert retried_state["source_baselines"]["gem-note"] != old_baseline
    assert "The corrected condition is recorded." in context_path.read_text(encoding="utf-8")


def test_user_managed_memory_blocks_automatic_overwrite_without_advancing_baseline(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(_topic_change(), _topic_change("Updated automatic summary."), _topic_change("Updated automatic summary."))
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    topic_path = "topics/continual-learning.md"
    service.save_topic("continual-learning", "# My hand-edited context\n\nKeep this wording.\n")
    state_path = tmp_path / "storage" / "learning-context" / "state.json"
    baseline_before = json.loads(state_path.read_text(encoding="utf-8"))["source_baselines"]["gem-note"]
    path.write_text(path.read_text(encoding="utf-8") + "\nA new method detail.\n", encoding="utf-8")

    protected = service.sync()

    assert protected["state"] == "needs_manual_review"
    assert service.read_topic("continual-learning")["markdown"] == "# My hand-edited context\n\nKeep this wording.\n"
    assert json.loads(state_path.read_text(encoding="utf-8"))["source_baselines"]["gem-note"] == baseline_before
    assert topic_path in service.get_overview()["user_managed_files"]

    service.restore_automatic_memory("topic", "continual-learning")
    retried = service.sync()
    assert retried["state"] == "synced"
    assert "Updated automatic summary." in service.read_topic("continual-learning")["markdown"]


def test_removing_one_source_retracts_only_its_auto_entries(tmp_path):
    _sync_repo(tmp_path)
    # Create the second canonical note with its own ID and the same supported concept.
    second_path = _document(tmp_path, "other-note", "Other Learning Note")
    second_path.write_text(
        second_path.read_text(encoding="utf-8") + "## Mechanism\n\nGEM computes a projection to preserve previous tasks.\n",
        encoding="utf-8",
    )
    response = _topic_change()
    gateway = FakeLearningGateway(response, response)
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note", "other-note"])
    service.sync()
    topic_path = tmp_path / "storage" / "learning-context" / "topics" / "continual-learning.md"
    memory = topic_path.read_text(encoding="utf-8")
    assert '"gem-note"' in memory and '"other-note"' in memory

    service.set_sources(["other-note"])
    service.sync()

    memory_after = topic_path.read_text(encoding="utf-8")
    assert '"gem-note"' not in memory_after
    assert '"other-note"' in memory_after
    assert subprocess.run(
        ["git", "rev-parse", "--verify", "refs/learning-context/gem-note"],
        cwd=tmp_path,
        capture_output=True,
    ).returncode != 0
    assert subprocess.run(
        ["git", "rev-parse", "--verify", "refs/learning-context/other-note"],
        cwd=tmp_path,
        capture_output=True,
    ).returncode == 0


def test_clearing_all_sources_retracts_auto_context_and_baseline(tmp_path):
    _sync_repo(tmp_path)
    gateway = FakeLearningGateway(_topic_change())
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    service.set_sources([])

    result = service.sync()

    topic_path = tmp_path / "storage" / "learning-context" / "topics" / "continual-learning.md"
    state = json.loads((tmp_path / "storage" / "learning-context" / "state.json").read_text(encoding="utf-8"))
    assert result["state"] == "no_sources"
    assert "gem-gradient-projection" not in topic_path.read_text(encoding="utf-8")
    assert state["source_baselines"] == {}
    assert gateway.calls and len(gateway.calls) == 1
    assert subprocess.run(
        ["git", "rev-parse", "--verify", "refs/learning-context/gem-note"],
        cwd=tmp_path,
        capture_output=True,
    ).returncode != 0
