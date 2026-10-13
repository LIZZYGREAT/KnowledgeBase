from pathlib import Path
import json
import shutil
import subprocess

import pytest
import yaml

from backend.app.services.learning_context_service import (
    LearningContextError,
    LearningContextService,
    _truncate_complete_markdown,
)
from backend.app.services.ai_client import AIGatewayError
from backend.app.services.learning_context_sync import LearningContextSync
from backend.app.services.learning_context_sync_entries import entry_blocks, render_entry
from backend.app.services.learning_context_sync_diff import (
    _MAX_DIFF_CHARS,
    _MAX_SECTIONS,
    markdown_body,
    section_units,
    semantic_text,
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


def _topic_changes_with_replay(projection_summary, replay_summary):
    response = _topic_change(projection_summary)
    response["changes"].append(
        {
            "entry_id": "gem-replay",
            "action": "upsert",
            "title": "记忆回放",
            "summary": replay_summary,
            "layer": "topic",
            "topic_id": "continual-learning",
            "topic_title": "持续学习",
            "rationale": "来源章节解释了回放机制。",
        }
    )
    return response


def _memory_entry(entry_id, layer, title, summary, topic_id=None):
    metadata = {
        "entry_id": entry_id,
        "owner": "auto",
        "source_headings": {"cl-note": ["Introduction"]},
        "layer": layer,
        "title": title,
        "summary": summary,
    }
    if topic_id:
        metadata["topic_id"] = topic_id
        metadata["topic_title"] = title
    return render_entry(metadata)


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
    assert service.get_context()["selected_source_ids"] == []
    service.set_sources(["learning-note"])
    context = service.get_context()
    assert context["selected_source_ids"] == ["learning-note"]
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
    service.set_sources(["cl-note"])
    context_root = tmp_path / "storage" / "learning-context"
    (context_root / "topics").mkdir(parents=True)
    (context_root / "active.md").write_text(
        _memory_entry("current-focus", "active", "当前方向", "EWC 与持续学习。"),
        encoding="utf-8",
    )
    (context_root / "important.md").write_text(
        _memory_entry("stable-knowledge", "important", "稳定知识", "Replay。"),
        encoding="utf-8",
    )
    (context_root / "topics" / "continual-learning.md").write_text(
        _memory_entry(
            "continual-learning-entry", "topic", "持续学习", "EWC、GEM 与 iCaRL。", "continual-learning"
        ),
        encoding="utf-8",
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


def test_section_units_keep_h3_details_with_their_h2_chapter():
    units = section_units(
        "# Note\n\n## Method\n\nOverview.\n\n### Detail A\n\nFirst detail.\n\n"
        "### Detail B\n\nSecond detail.\n\n## Results\n\nResult text.\n"
    )

    assert len(units) == 3
    method = next(item for item in units if item["heading"] == "Method")
    assert "### Detail A" in method["text"]
    assert "First detail." in method["text"]
    assert "### Detail B" in method["text"]
    assert "Second detail." in method["text"]


def test_recommendation_context_is_bounded_and_tracks_only_selected_sources(tmp_path):
    _document(tmp_path, "cl-note", "Continual Learning note")
    service = LearningContextService(tmp_path)
    service.set_sources(["cl-note"])
    service.set_preferences(
        {
            "fixed_direction": "Continual Learning",
            "keywords": ["EWC", "GEM"],
            "exclude_keywords": ["RLHF"],
            "exploration_directions": ["reinforcement learning basics"],
            "important_anchors": ["Fisher information"],
        }
    )
    context_root = tmp_path / "storage" / "learning-context"
    (context_root / "topics").mkdir(parents=True)
    (context_root / "active.md").write_text(
        "接下来比较 EWC 与 SI。\n\n"
        + _memory_entry("current-focus", "active", "当前方向", "EWC 与持续学习。"),
        encoding="utf-8",
    )
    (context_root / "important.md").write_text(
        _memory_entry("stable-anchor", "important", "稳定锚点", "Fisher information。"),
        encoding="utf-8",
    )
    (context_root / "topics" / "continual-learning.md").write_text(
        _memory_entry(
            "continual-learning-entry", "topic", "持续学习", "EWC、GEM 与 iCaRL。", "continual-learning"
        ),
        encoding="utf-8",
    )
    (context_root / "index.yaml").write_text(
        "topics:\n"
        "  - id: continual-learning\n"
        "    title: 持续学习\n"
        "    aliases: [continual learning]\n"
        "    keywords: [EWC, GEM, iCaRL]\n",
        encoding="utf-8",
    )

    result = service.get_recommendation_context("GEM continual learning", max_chars=1200)

    assert result["included_source_count"] == 1
    assert result["included_sources"] == [
        {"id": "cl-note", "title": "Continual Learning note", "type": "learning-note"}
    ]
    assert result["preferences"]["exclude_keywords"] == ["RLHF"]
    assert result["active"]
    assert result["important"]
    assert "接下来比较 EWC 与 SI" in result["user_direction"]
    assert [topic["id"] for topic in result["topics"]] == ["continual-learning"]
    assert len(result["active"]) <= 1200
    assert len(result["important"]) <= 1200
    assert len(result["topics"][0]["markdown"]) <= 1200
    assert len(result["user_direction"]) + len(result["active"]) + len(result["important"]) + sum(
        len(topic["markdown"]) for topic in result["topics"]
    ) <= 1200


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


def test_force_reanalysis_reconciles_source_entries_and_upserts_complete_summaries(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(
        _topic_changes_with_replay(
            "Fact A is supported. Fact B was supported by the old note.",
            "Fact B is supported by the old note.",
        ),
        _topic_change("Fact A remains supported."),
        _topic_change("Fact A remains supported and Fact B is corrected."),
    )
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    _document(tmp_path, "other-note", "Other Learning Note")
    service.set_sources(["gem-note", "other-note"])
    topic_path = (
        tmp_path
        / "storage"
        / "learning-context"
        / "topics"
        / "continual-learning.md"
    )
    topic_path.write_text(
        topic_path.read_text(encoding="utf-8")
        + "\n\n"
        + render_entry(
            {
                "entry_id": "shared-method",
                "owner": "auto",
                "source_headings": {
                    "gem-note": ["Mechanism"],
                    "other-note": ["Optimization"],
                },
                "source_summaries": {
                    "gem-note": "The old GEM note supports this shared method.",
                    "other-note": "The other note still supports this method.",
                },
                "layer": "topic",
                "topic_id": "continual-learning",
                "topic_title": "持续学习",
                "title": "Shared method",
                "summary": "Both notes support this shared method.",
            }
        ),
        encoding="utf-8",
    )
    path.write_text(
        path.read_text(encoding="utf-8").split("\n# ", 1)[0]
        + "\n# GEM Learning Note\n"
        + "\n".join(
            "## Section {}\n\nCurrent GEM evidence {}.".format(index, index)
            for index in range(11)
        )
        + "\n",
        encoding="utf-8",
    )

    result = service.sync(force=True, source_id="gem-note")

    assert result["state"] == "synced"
    assert len(gateway.calls) == 3
    topic = service.read_topic("continual-learning")["markdown"]
    entries = {item["metadata"]["entry_id"]: item["metadata"] for item in entry_blocks(topic)}
    assert "gem-replay" not in entries
    assert entries["gem-gradient-projection"]["source_summaries"]["gem-note"] == (
        "Fact A remains supported and Fact B is corrected."
    )
    assert entries["shared-method"]["source_headings"] == {
        "other-note": ["Optimization"]
    }
    assert entries["shared-method"]["source_summaries"] == {
        "other-note": "The other note still supports this method."
    }
    assert "\n\nFact A remains supported." not in topic


def test_failed_forced_reanalysis_keeps_previous_memory_and_baseline(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(
        _topic_change("Original supported fact."),
        _topic_change("Uncommitted first-batch replacement."),
        RuntimeError("provider unavailable"),
    )
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    context_root = tmp_path / "storage" / "learning-context"
    topic_path = context_root / "topics" / "continual-learning.md"
    state_path = context_root / "state.json"
    old_memory = topic_path.read_bytes()
    old_baseline = json.loads(state_path.read_text(encoding="utf-8"))["source_baselines"]["gem-note"]
    path.write_text(
        path.read_text(encoding="utf-8").split("\n# ", 1)[0]
        + "\n# GEM Learning Note\n"
        + "\n".join(
            "## Section {}\n\nCurrent GEM evidence {}.".format(index, index)
            for index in range(11)
        )
        + "\n",
        encoding="utf-8",
    )

    result = service.sync(force=True, source_id="gem-note")

    new_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["state"] == "failed"
    assert topic_path.read_bytes() == old_memory
    assert new_state["source_baselines"]["gem-note"] == old_baseline


def test_topic_index_rebuilds_automatic_keywords_and_keeps_manual_keywords(tmp_path):
    _sync_repo(
        tmp_path,
        "## Unique Obsolete Concept\n\nA unique obsolete concept is explained here.\n",
    )
    gateway = FakeLearningGateway(
        _topic_change("A unique obsolete concept is explained here.")
    )
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    index_path = tmp_path / "storage" / "learning-context" / "index.yaml"
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    topic = index["topics"][0]
    topic["manual_keywords"] = ["my retained focus"]
    topic["keywords"] = [*topic["keywords"], "my retained focus"]
    index_path.write_text(
        yaml.safe_dump(index, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    service.set_sources([])
    service.sync()

    refreshed = service.list_topics()[0]
    assert "my retained focus" in refreshed["keywords"]
    assert "unique obsolete concept" not in refreshed["keywords"]
    assert service.get_context(focus="unique obsolete concept")["topics"] == []


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


def test_editing_one_entry_pins_only_that_entry_and_keeps_manual_notes(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(
        _topic_changes_with_replay("Initial projection summary.", "Initial replay summary."),
        _topic_changes_with_replay("Updated projection summary.", "Updated replay summary."),
    )
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    original = service.read_topic("continual-learning")["markdown"]
    edited = original.replace(
        "gem-note：Initial projection summary.",
        "gem-note：Manually reviewed projection summary.",
    ) + "\n## Personal note\n\nKeep this free-form note.\n"
    saved = service.save_topic("continual-learning", edited)
    state_path = tmp_path / "storage" / "learning-context" / "state.json"
    baseline_before = json.loads(state_path.read_text(encoding="utf-8"))["source_baselines"]["gem-note"]
    path.write_text(path.read_text(encoding="utf-8") + "\nA new method detail.\n", encoding="utf-8")

    result = service.sync()
    memory = service.read_topic("continual-learning")["markdown"]
    blocks = {block["metadata"]["entry_id"]: block for block in entry_blocks(memory)}

    assert saved["pinned_entry_ids"] == ["gem-gradient-projection"]
    assert result["state"] == "synced"
    assert "Manually reviewed projection summary." in memory
    assert "Updated replay summary." in memory
    assert "Keep this free-form note." in memory
    recommendation_context = service.get_context(topic_id="continual-learning")
    assert all(
        "Keep this free-form note." not in topic["markdown"]
        for topic in recommendation_context["topics"]
    )
    assert blocks["gem-gradient-projection"]["metadata"]["pinned"] is True
    assert blocks["gem-replay"]["metadata"].get("pinned") is not True
    assert json.loads(state_path.read_text(encoding="utf-8"))["source_baselines"]["gem-note"] != baseline_before
    assert [item["entry_id"] for item in service.get_overview()["manual_entries"]] == [
        "gem-gradient-projection"
    ]

    service.restore_automatic_memory("topic", "continual-learning", "gem-gradient-projection")
    path.write_text(path.read_text(encoding="utf-8") + "\nAnother method detail.\n", encoding="utf-8")
    gateway.responses.append(_topic_changes_with_replay("Latest projection summary.", "Latest replay summary."))
    retried = service.sync()
    assert retried["state"] == "synced"
    assert "Latest projection summary." in service.read_topic("continual-learning")["markdown"]


def test_new_selected_topic_becomes_current_and_previous_topic_remains_searchable(tmp_path):
    _sync_repo(tmp_path)
    rl_note = _document(tmp_path, "rl-note", "Reinforcement Learning Introduction")
    rl_note.write_text(
        rl_note.read_text(encoding="utf-8")
        + "\n## Policy Learning\n\nReinforcement learning optimizes policies from reward signals.\n",
        encoding="utf-8",
    )
    rl_change = {
        "outcome": "knowledge_changed",
        "changes": [
            {
                "entry_id": "rl-policy-learning",
                "action": "upsert",
                "title": "策略学习",
                "summary": "强化学习根据奖励信号优化策略。",
                "layer": "topic",
                "topic_id": "reinforcement-learning",
                "topic_title": "强化学习",
                "rationale": "来源章节解释了策略优化。",
            }
        ],
    }
    gateway = FakeLearningGateway(_topic_change(), rl_change)
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()

    service.set_sources(["gem-note", "rl-note"])
    result = service.sync()

    index = service._read_yaml("index.yaml", {})
    assert result["state"] == "synced"
    assert index["active_topic_ids"] == ["reinforcement-learning"]
    assert "强化学习" in service.get_overview()["active"]
    assert "GEM" not in service.get_overview()["active"]
    assert service.read_topic("continual-learning")["markdown"]
    historical_context = service.get_context(focus="continual learning")
    assert [item["id"] for item in historical_context["topics"]] == [
        "continual-learning"
    ]


def test_manually_fixed_topic_stays_current_and_can_be_moved_to_history(tmp_path):
    _sync_repo(tmp_path)
    rl_note = _document(tmp_path, "rl-note", "Reinforcement Learning Introduction")
    rl_note.write_text(
        rl_note.read_text(encoding="utf-8")
        + "\n## Policy Learning\n\nReinforcement learning optimizes policies from reward signals.\n",
        encoding="utf-8",
    )
    rl_change = {
        "outcome": "knowledge_changed",
        "changes": [
            {
                "entry_id": "rl-policy-learning",
                "action": "upsert",
                "title": "策略学习",
                "summary": "强化学习根据奖励信号优化策略。",
                "layer": "topic",
                "topic_id": "reinforcement-learning",
                "topic_title": "强化学习",
                "rationale": "来源章节解释了策略优化。",
            }
        ],
    }
    service = LearningContextService(
        tmp_path, FakeLearningGateway(_topic_change(), rl_change)
    )
    service.set_sources(["gem-note"])
    service.sync()
    service.set_topic_status("continual-learning", "current")

    service.set_sources(["gem-note", "rl-note"])
    service.sync()

    assert service._read_yaml("index.yaml", {})["active_topic_ids"] == [
        "continual-learning",
        "reinforcement-learning",
    ]
    assert "强化学习" in service.get_overview()["active"]
    service.set_topic_status("continual-learning", "history")
    assert service._read_yaml("index.yaml", {})["active_topic_ids"] == [
        "reinforcement-learning"
    ]
    assert "强化学习" in service.get_overview()["active"]
    assert service.list_topics()[0]["manual_status"] == "history"


def test_manual_active_notes_are_search_intent_but_not_mastery(tmp_path):
    _sync_repo(tmp_path)
    service = LearningContextService(tmp_path)
    service.set_sources(["gem-note"])
    service._atomic_write(
        "active.md",
        "比较 EWC 与 SI，下一步希望了解 SI。\n\n"
        + render_entry(
            {
                "entry_id": "ewc-knowledge",
                "owner": "auto",
                "source_headings": {"gem-note": ["Elastic Weight Consolidation"]},
                "source_summaries": {"gem-note": "EWC constrains important gradients."},
                "layer": "active",
                "title": "EWC",
                "summary": "EWC constrains important gradients.",
            }
        ),
    )

    context = service.get_recommendation_context("continual learning")

    assert "比较 EWC 与 SI" in context["user_direction"]
    assert "比较 EWC 与 SI" not in context["active"]
    from backend.app.services.term_discovery_service import _covered_by_learning_context

    assert not _covered_by_learning_context(
        "SI",
        {
            "active": context["active"],
            "important": context["important"],
            "topics": context["topics"],
            "covered_term_headings": [],
            "user_direction": context["user_direction"],
        },
    )


def test_unpublished_source_evidence_is_removed_and_legacy_shared_summary_is_flagged(tmp_path):
    _sync_repo(tmp_path)
    _document(tmp_path, "other-note", "Other Note")
    context_root = tmp_path / "storage" / "learning-context"
    (context_root / "topics").mkdir(parents=True)
    (context_root / "sources.yaml").write_text("included_document_ids:\n  - gem-note\n", encoding="utf-8")
    (context_root / "index.yaml").write_text(
        "topics:\n  - id: continual-learning\n    title: 持续学习\n", encoding="utf-8"
    )
    legacy_metadata = {
        "entry_id": "legacy-shared-entry",
        "owner": "auto",
        "source_headings": {"gem-note": ["Mechanism"], "other-note": ["Mechanism"]},
        "layer": "topic",
        "topic_id": "continual-learning",
        "topic_title": "持续学习",
        "title": "旧版共享条目",
        "summary": "来源无法拆分的旧版摘要。",
    }
    (context_root / "topics" / "continual-learning.md").write_text(
        render_entry(legacy_metadata), encoding="utf-8"
    )
    service = LearningContextService(tmp_path)
    service.set_sources(["other-note"])
    memory_files = {"topics/continual-learning.md": render_entry(legacy_metadata)}
    LearningContextSync(service)._remove_source(memory_files, "gem-note")
    service._atomic_write("topics/continual-learning.md", memory_files["topics/continual-learning.md"])

    memory = service.read_topic("continual-learning")["markdown"]
    block = entry_blocks(memory)[0]
    assert block["metadata"]["support_state"] == "needs_review"
    assert "来源无法拆分的旧版摘要" in memory
    assert service.get_context(topic_id="continual-learning")["topics"] == []

    service.restore_automatic_memory(
        "topic",
        "continual-learning",
        "legacy-shared-entry",
        confirm_support=True,
    )
    confirmed = entry_blocks(service.read_topic("continual-learning")["markdown"])[0]
    assert confirmed["metadata"].get("support_state") is None
    assert set(confirmed["metadata"]["source_summaries"]) == {"other-note"}
    assert service.get_context(topic_id="continual-learning")["topics"]


def test_context_truncation_keeps_complete_paragraphs_and_entry_markers():
    markdown = (
        "# Context\n\nA complete first paragraph.\n\n"
        "<!-- learning-context-entry {\"entry_id\":\"valid-entry\",\"owner\":\"auto\",\"source_headings\":{\"gem-note\":[\"Mechanism\"]}} -->\n"
        "### Topic\n\nA complete auto entry.\n<!-- /learning-context-entry -->\n\n"
        "A later paragraph that must not jump ahead.\n"
    )
    bounded = _truncate_complete_markdown(markdown, len("# Context\n\nA complete first paragraph.\n\n") + 12)

    assert bounded == "# Context\n\nA complete first paragraph.\n\n"
    assert "learning-context-entry" not in bounded
    assert "later paragraph" not in bounded


def test_context_truncation_skips_an_oversize_early_entry_and_keeps_later_progress():
    markdown = "An older oversized entry.\n\nRL\n"

    assert _truncate_complete_markdown(markdown, 3) == "RL\n"


def test_legacy_layer_freeze_migrates_to_entry_pins_on_next_sync(tmp_path):
    _sync_repo(tmp_path)
    gateway = FakeLearningGateway(_topic_change())
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    state_path = tmp_path / "storage" / "learning-context" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["user_managed_files"] = ["topics/continual-learning.md"]
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = service.sync()

    migrated_state = json.loads(state_path.read_text(encoding="utf-8"))
    blocks = entry_blocks(service.read_topic("continual-learning")["markdown"])
    assert result["state"] == "synced"
    assert blocks[0]["metadata"]["pinned"] is True
    assert "user_managed_files" not in migrated_state


def test_removed_last_source_preserves_pinned_text_but_excludes_it_from_context(tmp_path):
    path = _sync_repo(tmp_path)
    service = LearningContextService(tmp_path, FakeLearningGateway(_topic_change()))
    service.set_sources(["gem-note"])
    service.sync()
    original = service.read_topic("continual-learning")["markdown"]
    service.save_topic(
        "continual-learning",
        original.replace(
            "gem-note：GEM projects gradients into a feasible region.",
            "gem-note：Manually reviewed summary.",
        ),
    )

    service.set_sources([])
    result = service.sync()

    memory = service.read_topic("continual-learning")["markdown"]
    block = entry_blocks(memory)[0]
    assert result["state"] == "no_sources"
    assert block["metadata"]["support_state"] == "source_removed"
    assert "Manually reviewed summary." in memory
    assert service.get_context(topic_id="continual-learning")["topics"] == []


def test_source_scope_filters_unselected_source_summary_before_sync(tmp_path):
    _sync_repo(tmp_path)
    other_note = _document(tmp_path, "other-note", "GEM Other Note")
    other_note.write_text(
        other_note.read_text(encoding="utf-8")
        + "\n## Mechanism\n\nGEM computes a projection to preserve previous tasks.\n",
        encoding="utf-8",
    )
    response = _topic_change("GEM summary.")
    gateway = FakeLearningGateway(response, response)
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note", "other-note"])
    initial_sync = service.sync()
    assert initial_sync["state"] == "synced", gateway.calls
    service.set_sources(["other-note"])

    context = service.get_context(topic_id="continual-learning")

    topic_context = context["topics"][0]["markdown"]
    assert "other-note：GEM summary." in topic_context
    assert "gem-note：GEM summary." not in topic_context


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


def test_large_initial_sync_failure_does_not_advance_baseline_or_publish_partial_memory(tmp_path):
    body = "\n\n".join(
        "## Chapter {}\n\nThis chapter explains a distinct continual learning method detail {}."
        .format(index, "with enough evidence for bounded batching.")
        for index in range(12)
    )
    _sync_repo(tmp_path, body)
    gateway = FakeLearningGateway(_topic_change(), RuntimeError("provider unavailable"))
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])

    result = service.sync()

    state_path = tmp_path / "storage" / "learning-context" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["state"] == "failed"
    assert len(gateway.calls) == 2
    assert state["source_baselines"] == {}
    assert not (
        tmp_path / "storage" / "learning-context" / "topics" / "continual-learning.md"
    ).exists()


def test_real_learning_notes_sync_in_bounded_complete_batches_and_seed_recommendation_context(tmp_path):
    repository = Path(__file__).resolve().parents[2]
    source_root = repository / "knowledge" / "documents" / "learning"
    source_ids = [
        "gem-gradient-episodic-memory-for-continual-learning",
        "gem-sgd",
        "icarl",
        "icarl-incremental-classifier-and-representation-learning",
    ]
    target_root = tmp_path / "knowledge" / "documents" / "learning"
    target_root.mkdir(parents=True)
    for source_id in source_ids:
        shutil.copy2(source_root / (source_id + ".md"), target_root / (source_id + ".md"))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    class CorpusGateway:
        def __init__(self):
            self.calls = []
            self.first_batch_sources = set()

        def run(self, task_name, context):
            self.calls.append((task_name, context))
            source_id = context["source_document_id"]
            if source_id in self.first_batch_sources:
                return {"outcome": "no_change", "changes": []}
            self.first_batch_sources.add(source_id)
            return {
                "outcome": "knowledge_changed",
                "changes": [
                    {
                        "entry_id": "source-" + source_id[:45],
                        "action": "upsert",
                        "title": "Progress from " + source_id,
                        "summary": "已分析章节：" + context["changed_sections"][0]["heading"],
                        "layer": "topic",
                        "topic_id": "continual-learning",
                        "topic_title": "持续学习",
                        "rationale": "Fake gateway test result from the supplied passage.",
                    }
                ],
            }

    gateway = CorpusGateway()
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(source_ids)

    first = service.sync()

    assert first["state"] == "synced"
    assert first["analyzed_count"] == 4
    assert len(gateway.calls) > len(source_ids)
    captured_by_source = {source_id: [] for source_id in source_ids}
    for task_name, context in gateway.calls:
        assert task_name == "update_learning_context"
        sections = context["changed_sections"]
        assert 0 < len(sections) <= _MAX_SECTIONS
        assert sum(
            len(section["before"]) + len(section["after"]) + len(section["nearby_context"])
            for section in sections
        ) <= _MAX_DIFF_CHARS
        captured_by_source[context["source_document_id"]].extend(
            section["after"] for section in sections
        )

    for source_id in source_ids:
        canonical = (source_root / (source_id + ".md")).read_text(encoding="utf-8")
        assert semantic_text("\n".join(captured_by_source[source_id])) == semantic_text(
            markdown_body(canonical)
        )

    context_root = tmp_path / "storage" / "learning-context"
    active_path = context_root / "active.md"
    topic_path = context_root / "topics" / "continual-learning.md"
    index_path = context_root / "index.yaml"
    state_path = context_root / "state.json"
    topic_memory = topic_path.read_text(encoding="utf-8")
    assert active_path.is_file() and active_path.read_text(encoding="utf-8").strip()
    assert all(source_id in topic_memory for source_id in source_ids)
    topic = service.list_topics()[0]
    assert topic["id"] == "continual-learning"
    assert "continual learning" in topic["aliases"]
    assert "持续学习" in topic["keywords"]
    assert service.get_context(focus="Continual Learning")["topics"][0]["id"] == topic["id"]
    recommendation = service.get_recommendation_context("Continual Learning")
    assert recommendation["active"]
    assert recommendation["topics"][0]["id"] == topic["id"]

    def snapshot():
        paths = [active_path, topic_path, index_path, state_path]
        return {path.relative_to(context_root).as_posix(): path.read_bytes() for path in paths}

    memory_snapshot = snapshot()
    call_count = len(gateway.calls)
    unchanged = service.sync()
    assert unchanged["analyzed_count"] == 0
    assert len(gateway.calls) == call_count
    assert memory_snapshot == snapshot()

    force_start = len(gateway.calls)
    forced = service.sync(force=True)
    assert forced["state"] == "synced"
    assert len(gateway.calls) > force_start
    forced_sources = {context["source_document_id"] for _, context in gateway.calls[force_start:]}
    assert forced_sources == set(source_ids)


def test_sync_if_stale_refreshes_changed_notes_and_skips_unchanged_ai_work(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(
        _topic_change(), _topic_change("Updated GEM projection summary.")
    )
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()

    unchanged = service.sync_if_stale()
    assert unchanged["stale"] is False
    assert unchanged["used_previous_context"] is False
    assert len(gateway.calls) == 1

    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n## Additional detail\n\nThe projection uses a constrained optimization step.\n",
        encoding="utf-8",
    )
    refreshed = service.sync_if_stale()

    assert refreshed["state"] == "synced"
    assert refreshed["stale"] is False
    assert refreshed["used_previous_context"] is False
    assert len(gateway.calls) == 2
    assert "Updated GEM projection summary." in service.read_topic("continual-learning")["markdown"]


def test_sync_if_stale_marks_previous_context_when_ai_sync_fails(tmp_path):
    path = _sync_repo(tmp_path)
    gateway = FakeLearningGateway(
        _topic_change(), AIGatewayError("sensitive provider payload")
    )
    service = LearningContextService(tmp_path, gateway)
    service.set_sources(["gem-note"])
    service.sync()
    old_memory = service.read_topic("continual-learning")["markdown"]
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n## Additional detail\n\nA substantive method change.\n",
        encoding="utf-8",
    )

    result = service.sync_if_stale()

    assert result["state"] == "failed"
    assert result["stale"] is True
    assert result["used_previous_context"] is True
    assert "使用上次保存的学习上下文" in result["message"]
    assert "AI 分析失败" in result["message"]
    assert "sensitive provider payload" not in result["message"]
    assert service.read_topic("continual-learning")["markdown"] == old_memory
