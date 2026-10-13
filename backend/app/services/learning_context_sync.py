"""Incremental, file-backed synchronization for the selected learning notes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import subprocess
import threading
from typing import Any, Optional

import yaml

from backend.app.domain.ai import LearningContextUpdateOutput
from backend.app.domain.document import DocumentMetadata
from backend.app.services.learning_context_service import (
    LearningContextError,
    LearningContextService,
)
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.learning_context_sync_diff import (
    _MAX_DIFF_CHARS,
    _MAX_SECTION_CHARS,
    _MAX_SECTIONS,
    changed_sections as _changed_sections,
    is_minor_wording_change as _is_minor_wording_change,
    markdown_body as _markdown_body,
    semantic_text as _semantic_text,
    tokens as _tokens,
)
from backend.app.services.learning_context_sync_entries import (
    SLUG as _SLUG,
    append_entry as _append_entry,
    entry_blocks as _entry_blocks,
    layer_path as _layer_path,
    remove_entry as _remove_entry,
    render_entry as _render_entry,
    replace_entry as _replace_entry,
)


_SYNC_LOCK = threading.RLock()
logger = logging.getLogger(__name__)
_BASELINE_REF_PREFIX = "refs/learning-context/"
_MAX_RELATED_ENTRIES = 12
_MAX_RELATED_CHARS = 7000


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _ManualReviewRequired(RuntimeError):
    pass


class LearningContextSync:
    """Compare selected note versions and merge validated local memory changes."""

    def __init__(self, service: LearningContextService, gateway=None):
        self.service = service
        self.gateway = gateway

    def run(
        self,
        *,
        dry_run: bool = False,
        force: bool = False,
        source_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if not isinstance(dry_run, bool) or not isinstance(force, bool):
            raise LearningContextError("dry_run and force must be booleans")
        if source_id is not None and (
            not isinstance(source_id, str) or not _SLUG.fullmatch(source_id)
        ):
            raise LearningContextError("Invalid source document ID")
        with _SYNC_LOCK:
            return self._run_locked(dry_run=dry_run, force=force, source_id=source_id)

    def _run_locked(self, *, dry_run: bool, force: bool, source_id: Optional[str]):
        selected = self.service._read_sources()
        if source_id is not None and source_id not in selected:
            raise LearningContextError("Reanalysis requires a selected learning document")
        targets = [source_id] if source_id else selected
        status_before = deepcopy(self.service._read_status())
        baselines = status_before.get("source_baselines", {})
        if not isinstance(baselines, dict):
            baselines = {}
        else:
            baselines = deepcopy(baselines)

        if not targets:
            result = {
                "state": "no_sources",
                "message": "请先选择学习资料，再执行同步。",
                "analyzed_count": 0,
                "skipped_count": 0,
                "source_results": [],
            }
            if not dry_run:
                memory_files = self._read_memory_files()
                original_memory_files = dict(memory_files)
                for removed_id in sorted(set(baselines) - set(selected)):
                    self._remove_source(
                        memory_files,
                        removed_id,
                        status_before.get("user_managed_files", []),
                    )
                updates = {
                    relative: content
                    for relative, content in memory_files.items()
                    if content != self.service._read_memory(relative)
                }
                if updates or status_before.get("state") != "no_sources" or baselines:
                    latest_status = self.service._read_status()
                    if latest_status.get("user_managed_files", []) != status_before.get("user_managed_files", []):
                        return self._needs_manual_review(status_before, baselines)
                    for relative in set(original_memory_files) | set(memory_files):
                        if self.service._read_memory(relative) != original_memory_files.get(relative, ""):
                            return self._needs_manual_review(status_before, baselines)
                    status_before.update(result)
                    status_before["source_baselines"] = {}
                    status_before["pending_added_ids"] = []
                    status_before["pending_removed_ids"] = []
                    status_before.pop("last_error_type", None)
                    updates["state.json"] = json.dumps(status_before, ensure_ascii=False, indent=2) + "\n"
                    self._commit_files(updates)
                    self._delete_baseline_refs(set(baselines) - set(selected))
            return result

        pending_baselines: dict[str, dict[str, Any]] = {}
        source_results: list[dict[str, Any]] = []
        analyzed_count = 0
        skipped_count = 0
        try:
            memory_files = self._read_memory_files()
            original_memory_files = dict(memory_files)
            for current_id in targets:
                source = self._read_source(current_id)
                baseline = baselines.get(current_id)
                if source is None:
                    source_results.append(
                        {"source_id": current_id, "action": "missing", "reason": "note is unavailable"}
                    )
                    continue
                current_bytes, metadata, current_text = source
                current_hash = hashlib.sha256(current_bytes).hexdigest()
                plan = self._plan(current_id, current_bytes, current_text, baseline, force)
                if plan["action"] == "unchanged":
                    source_results.append(plan["summary"])
                    skipped_count += 1
                    continue
                if dry_run:
                    source_results.append(plan["summary"])
                    if plan["action"] == "analyze":
                        analyzed_count += 1
                    else:
                        skipped_count += 1
                    continue

                if plan["action"] == "skip":
                    pending_baselines[current_id] = self._new_baseline(
                        current_id, metadata, current_bytes, current_hash, "skipped"
                    )
                    source_results.append(plan["summary"])
                    skipped_count += 1
                    continue

                context = self._build_ai_context(
                    current_id,
                    metadata,
                    plan["changed_sections"],
                    plan["change_kind"],
                    memory_files,
                    force,
                )
                if self.gateway is None:
                    raise LearningContextError("AI gateway is unavailable for a substantive change")
                output = self.gateway.run("update_learning_context", context)
                if not isinstance(output, LearningContextUpdateOutput):
                    output = LearningContextUpdateOutput.model_validate(output)
                if output.outcome == "knowledge_changed":
                    allowed_entry_ids = {
                        item["id"] for item in context["existing_related_memory"]
                    }
                    self._apply_changes(
                        memory_files,
                        current_id,
                        [item.model_dump() for item in output.changes],
                        plan["changed_sections"],
                        status_before.get("user_managed_files", []),
                        allowed_entry_ids,
                    )
                pending_baselines[current_id] = self._new_baseline(
                    current_id,
                    metadata,
                    current_bytes,
                    current_hash,
                    output.outcome,
                )
                source_results.append(
                    {
                        "source_id": current_id,
                        "action": "analyzed",
                        "outcome": output.outcome,
                        "changed_sections": len(plan["changed_sections"]),
                    }
                )
                analyzed_count += 1

            if dry_run:
                return {
                    "state": "dry_run",
                    "message": "仅检查本地变化；没有调用模型或写入文件。",
                    "analyzed_count": analyzed_count,
                    "skipped_count": skipped_count,
                    "source_results": source_results,
                }

            # A selected document that disappeared, or a document the user
            # explicitly removed from scope, loses only its own auto evidence.
            removed_ids = (set(baselines) | set(selected)) - set(selected)
            removed_ids.update(
                item["source_id"]
                for item in source_results
                if item["action"] == "missing"
            )
            for removed_id in sorted(removed_ids):
                self._remove_source(memory_files, removed_id, status_before.get("user_managed_files", []))
                baselines.pop(removed_id, None)

            baselines.update(pending_baselines)
            updates = {
                relative: content
                for relative, content in memory_files.items()
                if content != self.service._read_memory(relative)
            }
            if any(item["action"] == "missing" for item in source_results):
                for item in source_results:
                    if item["action"] == "missing":
                        baselines.pop(item["source_id"], None)

            state_after = deepcopy(status_before)
            state_after.update(
                {
                    "state": "synced",
                    "message": "同步完成：分析 {} 篇，跳过 {} 篇。".format(
                        analyzed_count, skipped_count
                    ),
                    "source_baselines": baselines,
                    "last_sync_at": _now(),
                    "last_result": source_results,
                    "analyzed_count": analyzed_count,
                    "skipped_count": skipped_count,
                    "pending_added_ids": [],
                    "pending_removed_ids": [],
                }
            )
            state_after.pop("last_error_type", None)
            topic_index = self._updated_topic_index(memory_files, updates)
            if topic_index is not None:
                updates["index.yaml"] = topic_index
            if self.service._read_sources() != selected:
                raise _ManualReviewRequired()
            latest_status = self.service._read_status()
            if latest_status.get("user_managed_files", []) != status_before.get("user_managed_files", []):
                raise _ManualReviewRequired()
            for relative in set(original_memory_files) | set(memory_files):
                if self.service._read_memory(relative) != original_memory_files.get(relative, ""):
                    raise _ManualReviewRequired()
            # Avoid creating a storage tree for an all-unchanged first read.
            if (
                not updates
                and not pending_baselines
                and not removed_ids
                and not any(item["action"] == "missing" for item in source_results)
                and status_before.get("state") == "synced"
            ):
                return {
                    "state": "synced",
                    "message": status_before.get("message", "学习上下文已是最新。"),
                    "analyzed_count": 0,
                    "skipped_count": skipped_count,
                    "source_results": source_results,
                }
            updates["state.json"] = json.dumps(state_after, ensure_ascii=False, indent=2) + "\n"
            previous_refs = self._update_baseline_refs(pending_baselines)
            try:
                self._commit_files(updates)
            except Exception:
                self._restore_baseline_refs(previous_refs)
                raise
            self._delete_baseline_refs(removed_ids)
            return {
                "state": "synced",
                "message": state_after["message"],
                "analyzed_count": analyzed_count,
                "skipped_count": skipped_count,
                "source_results": source_results,
            }
        except _ManualReviewRequired:
            return self._needs_manual_review(status_before, baselines)
        except Exception as error:
            logger.exception("Learning context synchronization failed")
            return self._failed(status_before, baselines, type(error).__name__)

    def _plan(self, source_id, current_bytes, current_text, baseline, force):
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        if not force and isinstance(baseline, dict) and baseline.get("content_sha256") == current_hash:
            return {
                "action": "unchanged",
                "summary": {"source_id": source_id, "action": "unchanged", "reason": "内容未变化"},
            }
        old_bytes = None
        if isinstance(baseline, dict):
            old_bytes = self._read_blob(baseline.get("git_blob"))
        old_text = ""
        if old_bytes is not None:
            try:
                old_text = "" if force else old_bytes.decode("utf-8")
            except UnicodeError:
                old_bytes = None
                old_text = ""
        change_kind = "forced_reanalysis" if force else "initial_analysis" if old_bytes is None else "incremental"
        if old_bytes is not None and not force:
            if _semantic_text(_markdown_body(old_text)) == _semantic_text(_markdown_body(current_text)):
                return {
                    "action": "skip",
                    "summary": {"source_id": source_id, "action": "skipped", "reason": "仅格式或排版变化"},
                }
        changed_sections = _changed_sections(old_text, current_text, full=(old_bytes is None or force))
        if old_bytes is not None and not force and _is_minor_wording_change(
            old_text, current_text, changed_sections
        ):
            return {
                "action": "skip",
                "summary": {"source_id": source_id, "action": "skipped", "reason": "少量普通措辞调整"},
            }
        total = sum(len(item["before"]) + len(item["after"]) + len(item["nearby_context"]) for item in changed_sections)
        if len(changed_sections) > _MAX_SECTIONS or total > _MAX_DIFF_CHARS:
            raise LearningContextError(
                "变化范围过大，暂未发送模型；请按章节拆分修改后重试。"
            )
        return {
            "action": "analyze",
            "changed_sections": changed_sections,
            "change_kind": change_kind,
            "summary": {
                "source_id": source_id,
                "action": "analyze",
                "reason": "需要检查知识变化",
                "changed_sections": len(changed_sections),
            },
        }

    def _build_ai_context(self, source_id, metadata, sections, change_kind, memory_files, force):
        related = self._related_entries(source_id, metadata.title, sections, memory_files)
        return {
            "source_document_id": source_id,
            "source_title": metadata.title,
            "change_kind": change_kind,
            "force_reanalysis": force,
            "changed_sections": sections,
            "existing_related_memory": related,
        }

    def _related_entries(self, source_id, source_title, sections, memory_files):
        found = []
        total = 0
        selected_ids = set(self.service._read_sources())
        focus_tokens = _tokens(
            source_title
            + " "
            + " ".join(
                "{} {} {}".format(item.get("heading", ""), item.get("before", ""), item.get("after", ""))
                for item in sections
            )
        )
        for relative, content in memory_files.items():
            for block in _entry_blocks(content):
                metadata = block["metadata"]
                source_headings = metadata.get("source_headings", {})
                selected_support = sorted(set(source_headings) & selected_ids)
                related_tokens = _tokens(
                    "{} {}".format(metadata.get("title", ""), metadata.get("summary", ""))
                )
                if source_id not in source_headings and not (focus_tokens & related_tokens):
                    continue
                entry = {
                    "id": metadata["entry_id"],
                    "title": metadata.get("title", ""),
                    "summary": metadata.get("summary", ""),
                    "layer": metadata.get("layer", "topic"),
                    "topic_id": metadata.get("topic_id"),
                    "topic_title": metadata.get("topic_title"),
                    "source_ids": selected_support,
                    "source_headings": {
                        key: value for key, value in source_headings.items() if key in selected_ids
                    },
                }
                size = len(entry["title"]) + len(entry["summary"])
                if len(found) < _MAX_RELATED_ENTRIES and total + size <= _MAX_RELATED_CHARS:
                    found.append(entry)
                    total += size
        return found

    def _apply_changes(
        self, memory_files, source_id, changes, changed_sections, user_managed_files, allowed_entry_ids
    ):
        managed = set(user_managed_files) if isinstance(user_managed_files, list) else set()
        index = self._entry_index(memory_files)
        headings = sorted(
            {item.get("heading", "未分节内容") for item in changed_sections if item.get("heading")}
        )
        for change in changes:
            entry_id = change["entry_id"]
            existing = index.get(entry_id)
            if change["action"] == "remove":
                if existing is None or source_id not in existing["metadata"].get("source_headings", {}):
                    raise LearningContextError("AI removal did not target a related auto-managed entry")
                old_relative, old_metadata = existing["relative_path"], existing["metadata"]
                if old_relative in managed:
                    raise _ManualReviewRequired()
                updated = deepcopy(old_metadata)
                updated["source_headings"].pop(source_id, None)
                if updated["source_headings"]:
                    _replace_entry(memory_files, old_relative, entry_id, _render_entry(updated))
                else:
                    _remove_entry(memory_files, old_relative, entry_id)
                index.pop(entry_id, None)
                continue

            relative = _layer_path(change["layer"], change.get("topic_id"))
            if relative in managed or (existing and existing["relative_path"] in managed):
                raise _ManualReviewRequired()
            if (
                existing
                and source_id not in existing["metadata"].get("source_headings", {})
                and entry_id not in allowed_entry_ids
            ):
                raise LearningContextError("AI update collided with an entry from another source")
            source_headings = deepcopy(existing["metadata"].get("source_headings", {})) if existing else {}
            previous_headings = source_headings.get(source_id, [])
            source_headings[source_id] = sorted(set(previous_headings) | set(headings))
            entry_metadata = {
                "entry_id": entry_id,
                "owner": "auto",
                "source_headings": source_headings,
                "layer": change["layer"],
                "topic_id": change.get("topic_id"),
                "topic_title": change.get("topic_title"),
                "title": change["title"],
                "summary": change["summary"],
            }
            rendered = _render_entry(entry_metadata)
            if existing:
                _remove_entry(memory_files, existing["relative_path"], entry_id)
            _append_entry(memory_files, relative, rendered)
            index[entry_id] = {"relative_path": relative, "metadata": entry_metadata}

    def _remove_source(self, memory_files, source_id, user_managed_files):
        managed = set(user_managed_files) if isinstance(user_managed_files, list) else set()
        for relative, content in list(memory_files.items()):
            if relative in managed:
                continue
            for block in list(_entry_blocks(content)):
                metadata = block["metadata"]
                sources = metadata.get("source_headings", {})
                if source_id not in sources:
                    continue
                updated = deepcopy(metadata)
                updated["source_headings"].pop(source_id, None)
                if updated["source_headings"]:
                    _replace_entry(memory_files, relative, metadata["entry_id"], _render_entry(updated))
                else:
                    _remove_entry(memory_files, relative, metadata["entry_id"])

    def _entry_index(self, memory_files):
        indexed = {}
        for relative, content in memory_files.items():
            for block in _entry_blocks(content):
                entry_id = block["metadata"]["entry_id"]
                if entry_id in indexed:
                    raise LearningContextError("Duplicate automatic learning entry ID")
                indexed[entry_id] = {"relative_path": relative, "metadata": block["metadata"]}
        return indexed

    def _read_memory_files(self):
        files = {
            "active.md": self.service._read_memory("active.md"),
            "important.md": self.service._read_memory("important.md"),
        }
        for relative in ("active.md", "important.md"):
            path = self.service._context_path(relative, must_exist=False)
            if path.is_file() and path.stat().st_size > 512 * 1024:
                raise LearningContextError("Learning context file is too large: {}".format(relative))
        topics_dir = self.service.context_root / "topics"
        if topics_dir.is_symlink():
            raise LearningContextError("Learning context directory cannot be a symlink")
        if topics_dir.is_dir():
            for path in sorted(topics_dir.glob("*.md")):
                relative = "topics/" + path.name
                if _SLUG.fullmatch(path.stem):
                    if path.stat().st_size > 512 * 1024:
                        raise LearningContextError("Learning context file is too large: {}".format(relative))
                    files[relative] = self.service._read_memory(relative)
        return files

    def _read_source(self, source_id):
        if not self.service.documents_root.is_dir():
            return None
        for path in sorted(self.service.documents_root.rglob(source_id + ".md")):
            if path.stem != source_id or not self.service._safe_canonical_file(path):
                continue
            try:
                raw = path.read_bytes()
                if len(raw) > 2 * 1024 * 1024:
                    raise LearningContextError("Selected learning document exceeds the size limit")
                text = raw.decode("utf-8")
                parsed = parse_markdown(text)
                metadata = DocumentMetadata.model_validate(parsed.frontmatter)
            except (OSError, UnicodeError, ValueError, TypeError) as error:
                raise LearningContextError("Selected learning document is invalid: {}".format(source_id)) from error
            if metadata.id == source_id and metadata.type in {"paper-note", "learning-note", "course-note"}:
                return raw, metadata, text
        return None

    def _read_blob(self, object_id):
        if not isinstance(object_id, str) or not re.fullmatch(r"[a-f0-9]{40,64}", object_id):
            return None
        result = subprocess.run(
            ["git", "cat-file", "-p", object_id],
            cwd=str(self.service.repository_root),
            capture_output=True,
            check=False,
        )
        return result.stdout if result.returncode == 0 else None

    def _new_baseline(self, source_id, metadata, content, content_hash, result):
        completed = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=str(self.service.repository_root),
            input=content,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise LearningContextError("Could not save the handled source version in Git")
        object_id = completed.stdout.decode("ascii", errors="strict").strip()
        if not re.fullmatch(r"[a-f0-9]{40,64}", object_id):
            raise LearningContextError("Git returned an invalid source version")
        return {
            "git_blob": object_id,
            "content_sha256": content_hash,
            "title": metadata.title,
            "type": metadata.type,
            "handled_at": _now(),
            "result": result,
        }

    def _update_baseline_refs(self, new_baselines):
        previous = {}
        try:
            for source_id, baseline in new_baselines.items():
                reference = _BASELINE_REF_PREFIX + source_id
                existing = subprocess.run(
                    ["git", "rev-parse", "--verify", reference],
                    cwd=str(self.service.repository_root),
                    capture_output=True,
                    check=False,
                )
                previous[source_id] = (
                    existing.stdout.decode("ascii", errors="strict").strip()
                    if existing.returncode == 0
                    else None
                )
                updated = subprocess.run(
                    ["git", "update-ref", reference, baseline["git_blob"]],
                    cwd=str(self.service.repository_root),
                    capture_output=True,
                    check=False,
                )
                if updated.returncode != 0:
                    raise LearningContextError("Could not retain the handled Git source version")
        except Exception:
            self._restore_baseline_refs(previous)
            raise
        return previous

    def _restore_baseline_refs(self, previous):
        for source_id, old_oid in previous.items():
            reference = _BASELINE_REF_PREFIX + source_id
            if old_oid:
                command = ["git", "update-ref", reference, old_oid]
            else:
                command = ["git", "update-ref", "-d", reference]
            subprocess.run(
                command,
                cwd=str(self.service.repository_root),
                capture_output=True,
                check=False,
            )

    def _delete_baseline_refs(self, source_ids):
        for source_id in source_ids:
            subprocess.run(
                ["git", "update-ref", "-d", _BASELINE_REF_PREFIX + source_id],
                cwd=str(self.service.repository_root),
                capture_output=True,
                check=False,
            )

    def _updated_topic_index(self, memory_files, updates):
        try:
            index = self.service._read_yaml("index.yaml", {"topics": []})
            if not isinstance(index, dict) or not isinstance(index.get("topics", []), list):
                raise LearningContextError("index.yaml must contain a topics list")
            topics = [dict(item) for item in index.get("topics", []) if isinstance(item, dict)]
            by_id = {item.get("id"): item for item in topics if isinstance(item.get("id"), str)}
            additions = []
            for relative in updates:
                if not relative.startswith("topics/") or not relative.endswith(".md"):
                    continue
                topic_file_id = Path(relative).stem
                if topic_file_id in by_id:
                    continue
                content = memory_files.get(relative, "")
                for block in _entry_blocks(content):
                    metadata = block["metadata"]
                    topic_id = metadata.get("topic_id")
                    topic_title = metadata.get("topic_title")
                    if metadata.get("layer") == "topic" and topic_id == topic_file_id and topic_title:
                        additions.append(
                            {"id": topic_id, "title": topic_title, "aliases": [], "keywords": []}
                        )
                        by_id[topic_id] = additions[-1]
                        break
            if not additions:
                return None
            topics.extend(additions)
            index["topics"] = topics
            return yaml.safe_dump(index, allow_unicode=True, sort_keys=False)
        except Exception as error:
            raise LearningContextError("Could not update the learning topic index") from error

    def _commit_files(self, updates):
        previous = {}
        for relative in updates:
            path = self.service._context_path(relative, must_exist=False)
            previous[relative] = path.read_text(encoding="utf-8") if path.is_file() else None
        written = []
        try:
            for relative in sorted(item for item in updates if item != "state.json"):
                self.service._atomic_write(relative, updates[relative])
                written.append(relative)
            if "state.json" in updates:
                self.service._atomic_write("state.json", updates["state.json"])
                written.append("state.json")
        except Exception:
            for relative in reversed(written):
                prior = previous[relative]
                path = self.service._context_path(relative, must_exist=False)
                if prior is None:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                else:
                    self.service._atomic_write(relative, prior)
            raise

    def _needs_manual_review(self, status_before, baselines):
        status = deepcopy(self.service._read_status())
        status.update(
            {
                "state": "needs_manual_review",
                "message": "拟更新的上下文层由你固定维护；请先恢复该层自动维护，再重试。原内容与处理基准均已保留。",
                "source_baselines": baselines,
            }
        )
        self.service._write_status(status)
        return {
            "state": "needs_manual_review",
            "message": status["message"],
            "analyzed_count": 0,
            "skipped_count": 0,
            "source_results": [],
        }

    def _failed(self, status_before, baselines, reason):
        status = deepcopy(self.service._read_status())
        status.update(
            {
                "state": "failed",
                "message": "同步失败，可重试；学习上下文和已处理基准已保留。",
                "source_baselines": baselines,
                "last_error_type": reason,
            }
        )
        try:
            self.service._write_status(status)
        except Exception:
            pass
        return {
            "state": "failed",
            "message": status["message"],
            "analyzed_count": 0,
            "skipped_count": 0,
            "source_results": [],
        }
