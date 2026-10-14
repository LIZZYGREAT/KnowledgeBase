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
    batch_sections as _batch_sections,
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
_TOPIC_BILINGUAL_NAMES = {
    "continual-learning": ("持续学习",),
    "lifelong-learning": ("终身学习", "持续学习"),
    "reinforcement-learning": ("强化学习",),
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _merge_index_values(existing, derived, limit=40):
    values = existing if isinstance(existing, list) else []
    result = []
    seen = set()
    for item in [*values, *derived]:
        if not isinstance(item, str):
            continue
        cleaned = " ".join(item.split())[:200]
        key = cleaned.casefold()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _manual_state_signature(status):
    revision = status.get("manual_revision", 0) if isinstance(status, dict) else 0
    if isinstance(revision, bool) or not isinstance(revision, int):
        revision = 0
    legacy = status.get("user_managed_files", []) if isinstance(status, dict) else []
    suppressed = status.get("suppressed_entries", []) if isinstance(status, dict) else []
    return (
        revision,
        tuple(sorted(item for item in legacy if isinstance(item, str)))
        if isinstance(legacy, list)
        else (),
        json.dumps(suppressed, ensure_ascii=False, sort_keys=True)
        if isinstance(suppressed, list)
        else "[]",
    )


def _entry_summary(source_summaries):
    return "\n\n".join(
        "{}：{}".format(source_id, summary)
        for source_id, summary in sorted(source_summaries.items())
        if isinstance(source_id, str) and isinstance(summary, str) and summary.strip()
    )[:2000]


def _migrate_legacy_pins(memory_files, status):
    legacy = status.get("user_managed_files", [])
    if not isinstance(legacy, list):
        status.pop("user_managed_files", None)
        return
    for relative in legacy:
        if not isinstance(relative, str) or relative not in memory_files:
            continue
        for block in reversed(_entry_blocks(memory_files[relative])):
            if block["metadata"].get("pinned"):
                continue
            metadata = deepcopy(block["metadata"])
            metadata["pinned"] = True
            rendered = _render_entry(metadata)
            content = memory_files[relative]
            memory_files[relative] = content[:block["start"]] + rendered + content[block["end"]:]
    status.pop("user_managed_files", None)


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
            self.service._set_sync_progress(
                {
                    "phase": "preparing",
                    "completed_sources": 0,
                    "total_sources": 0,
                    "source_index": 0,
                    "completed_batches": 0,
                    "total_batches": 0,
                    "batch_index": 0,
                    "current_source_id": None,
                    "current_source_title": None,
                }
            )
            try:
                return self._run_locked(
                    dry_run=dry_run, force=force, source_id=source_id
                )
            finally:
                self.service._set_sync_progress(None)

    def _run_locked(self, *, dry_run: bool, force: bool, source_id: Optional[str]):
        selected = self.service._read_sources()
        if source_id is not None and source_id not in selected:
            raise LearningContextError("Reanalysis requires a selected learning document")
        targets = [source_id] if source_id else selected
        self.service._update_sync_progress(
            phase="checking",
            completed_sources=0,
            total_sources=len(targets),
        )
        status_before = deepcopy(self.service._read_status())
        manual_signature_before = _manual_state_signature(status_before)
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
                _migrate_legacy_pins(memory_files, status_before)
                for removed_id in sorted(set(baselines) - set(selected)):
                    self._remove_source(memory_files, removed_id)
                topic_index, active_topic_ids = self._updated_topic_index(
                    memory_files, []
                )
                self._ensure_active_focus(memory_files, selected, active_topic_ids)
                updates = {
                    relative: content
                    for relative, content in memory_files.items()
                    if content != self.service._read_memory(relative)
                }
                if topic_index is not None:
                    updates["index.yaml"] = topic_index
                if updates or status_before.get("state") != "no_sources" or baselines or status_before != self.service._read_status():
                    latest_status = self.service._read_status()
                    if _manual_state_signature(latest_status) != manual_signature_before:
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
        progressed_topic_ids: list[str] = []
        manual_review_entry_ids: dict[str, list[str]] = {}
        analyzed_count = 0
        skipped_count = 0
        try:
            memory_files = self._read_memory_files()
            original_memory_files = dict(memory_files)
            if not dry_run:
                _migrate_legacy_pins(memory_files, status_before)
            for source_index, current_id in enumerate(targets, start=1):
                self.service._update_sync_progress(
                    phase="checking",
                    completed_sources=source_index - 1,
                    total_sources=len(targets),
                    source_index=source_index,
                    completed_batches=0,
                    total_batches=0,
                    batch_index=0,
                    current_source_id=current_id,
                    current_source_title=current_id,
                )
                source = self._read_source(current_id)
                baseline = baselines.get(current_id)
                if source is None:
                    source_results.append(
                        {"source_id": current_id, "action": "missing", "reason": "note is unavailable"}
                    )
                    self.service._update_sync_progress(
                        completed_sources=source_index,
                        current_source_id=None,
                        current_source_title=None,
                    )
                    continue
                current_bytes, metadata, current_text = source
                self.service._update_sync_progress(
                    current_source_title=metadata.title
                )
                current_hash = hashlib.sha256(current_bytes).hexdigest()
                plan = self._plan(current_id, current_bytes, current_text, baseline, force)
                if plan["action"] == "unchanged":
                    source_results.append(plan["summary"])
                    skipped_count += 1
                    self.service._update_sync_progress(
                        completed_sources=source_index,
                        current_source_id=None,
                        current_source_title=None,
                    )
                    continue
                if dry_run:
                    source_results.append(plan["summary"])
                    if plan["action"] == "analyze":
                        analyzed_count += 1
                    else:
                        skipped_count += 1
                    self.service._update_sync_progress(
                        completed_sources=source_index,
                        current_source_id=None,
                        current_source_title=None,
                    )
                    continue

                if plan["action"] == "skip":
                    if force:
                        # A forced reanalysis of an empty note is a complete
                        # result too: it has no current evidence to retain.
                        self._remove_source(memory_files, current_id)
                    pending_baselines[current_id] = self._new_baseline(
                        current_id, metadata, current_bytes, current_hash, "skipped"
                    )
                    source_results.append(plan["summary"])
                    skipped_count += 1
                    self.service._update_sync_progress(
                        completed_sources=source_index,
                        current_source_id=None,
                        current_source_title=None,
                    )
                    continue

                plan["batches"] = self._split_batches_for_related_memory(
                    current_id,
                    metadata.title,
                    plan["batches"],
                    memory_files,
                    force,
                )

                if self.gateway is None:
                    raise LearningContextError("AI gateway is unavailable for a substantive change")
                outcomes = []
                source_heading_updates = {}
                source_section_key_updates = {}
                source_summary_updates = {}
                uncovered_entry_ids = set()
                suppress_progress = (
                    force
                    and isinstance(baseline, dict)
                    and isinstance(baseline.get("content_sha256"), str)
                )
                self.service._update_sync_progress(
                    phase="analyzing",
                    total_batches=len(plan["batches"]),
                )
                for batch_index, batch in enumerate(plan["batches"], start=1):
                    self.service._update_sync_progress(batch_index=batch_index)
                    context, uncovered = self._build_ai_context(
                        current_id,
                        metadata,
                        batch,
                        plan["change_kind"],
                        memory_files,
                        force,
                    )
                    uncovered_entry_ids.update(uncovered)
                    output = self.gateway.run("update_learning_context", context)
                    if not isinstance(output, LearningContextUpdateOutput):
                        output = LearningContextUpdateOutput.model_validate(output)
                    outcomes.append(output.outcome)
                    if output.outcome == "knowledge_changed":
                        allowed_entry_ids = {
                            item["id"] for item in context["existing_related_memory"]
                        }
                        self._apply_changes(
                            memory_files,
                            current_id,
                            [item.model_dump() for item in output.changes],
                            batch,
                            status_before.get("suppressed_entries", []),
                            allowed_entry_ids,
                            source_heading_updates,
                            source_section_key_updates,
                            source_summary_updates,
                            None if suppress_progress else progressed_topic_ids,
                            replace_source_headings=force,
                        )
                    self.service._update_sync_progress(
                        completed_batches=batch_index
                    )
                outcome = (
                    "knowledge_changed"
                    if "knowledge_changed" in outcomes
                    else "no_change"
                )
                pending_baselines[current_id] = self._new_baseline(
                    current_id,
                    metadata,
                    current_bytes,
                    current_hash,
                    outcome,
                )
                source_result = {
                    "source_id": current_id,
                    "action": "analyzed",
                    "outcome": outcome,
                    "changed_sections": len(plan["changed_sections"]),
                    "batch_count": len(plan["batches"]),
                }
                if uncovered_entry_ids:
                    ids = sorted(uncovered_entry_ids)
                    source_result["manual_review_entry_ids"] = ids
                    manual_review_entry_ids[current_id] = ids
                source_results.append(source_result)
                analyzed_count += 1
                self.service._update_sync_progress(
                    phase="checking",
                    completed_sources=source_index,
                    current_source_id=None,
                    current_source_title=None,
                    completed_batches=0,
                    total_batches=0,
                    batch_index=0,
                )

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
                self._remove_source(memory_files, removed_id)
                baselines.pop(removed_id, None)

            topic_index, active_topic_ids = self._updated_topic_index(
                memory_files, progressed_topic_ids
            )
            self._ensure_active_focus(memory_files, selected, active_topic_ids)

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

            manual_review_count = sum(
                len(entry_ids) for entry_ids in manual_review_entry_ids.values()
            )
            completion_message = "同步完成：分析 {} 篇，跳过 {} 篇。".format(
                analyzed_count, skipped_count
            )
            if manual_review_count:
                completion_message += (
                    "有 {} 条旧知识超出单次核对预算，已保留原内容，请人工检查。"
                    .format(manual_review_count)
                )
            state_after = deepcopy(status_before)
            state_after.update(
                {
                    "state": "synced",
                    "message": completion_message,
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
            if topic_index is not None:
                updates["index.yaml"] = topic_index
            if self.service._read_sources() != selected:
                raise _ManualReviewRequired()
            latest_status = self.service._read_status()
            if _manual_state_signature(latest_status) != manual_signature_before:
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
            reason = type(error).__name__
            detail = str(error)
            if reason == "LearningContextError" and detail == (
                "AI gateway is unavailable for a substantive change"
            ):
                reason = "AIUnavailable"
            elif reason == "LearningContextError" and "exceeds the size limit" in detail:
                reason = "LearningNoteTooLarge"
            return self._failed(status_before, baselines, reason)

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
        batches = _batch_sections(changed_sections)
        if not batches:
            return {
                "action": "skip",
                "summary": {"source_id": source_id, "action": "skipped", "reason": "没有可分析的正文内容"},
            }
        return {
            "action": "analyze",
            "changed_sections": changed_sections,
            "batches": batches,
            "change_kind": change_kind,
            "summary": {
                "source_id": source_id,
                "action": "analyze",
                "reason": "需要检查知识变化",
                "changed_sections": len(changed_sections),
                "batch_count": len(batches),
            },
        }

    def _build_ai_context(self, source_id, metadata, sections, change_kind, memory_files, force):
        related, uncovered = self._related_entries(
            source_id,
            metadata.title,
            sections,
            memory_files,
            force=force,
            include_uncovered=True,
        )
        context = {
            "source_document_id": source_id,
            "source_title": metadata.title,
            "change_kind": change_kind,
            "force_reanalysis": force,
            "changed_sections": sections,
            "existing_related_memory": related,
        }
        return context, uncovered

    def _split_batches_for_related_memory(
        self, source_id, source_title, batches, memory_files, force
    ):
        pending = list(reversed(batches))
        result = []
        while pending:
            batch = pending.pop()
            _, uncovered = self._related_entries(
                source_id,
                source_title,
                batch,
                memory_files,
                force=force,
                include_uncovered=True,
            )
            if uncovered and len(batch) > 1:
                middle = max(1, len(batch) // 2)
                pending.append(batch[middle:])
                pending.append(batch[:middle])
                continue
            result.append(batch)
        return result

    def _related_entries(
        self,
        source_id,
        source_title,
        sections,
        memory_files,
        *,
        force=False,
        include_uncovered=False,
    ):
        heading_matches = []
        related_matches = []
        forced_source_matches = []
        selected_ids = {
            item["id"] for item in self.service._selected_source_summaries()
        }
        requested_section_keys = set()
        heading_section_keys = {}
        for item in sections:
            if not isinstance(item, dict):
                continue
            section_key = item.get("section_key")
            heading = item.get("heading")
            if isinstance(section_key, str):
                requested_section_keys.add(section_key)
                if isinstance(heading, str):
                    heading_section_keys.setdefault(heading, set()).add(section_key)
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
                if metadata.get("entry_id") == "current-learning-focus":
                    # This is a derived summary rebuilt from topic entries; it
                    # should not consume the bounded claim-review allowance.
                    continue
                if metadata.get("support_state") in {"needs_review", "source_removed"}:
                    continue
                source_headings = metadata.get("source_headings", {})
                source_section_keys = metadata.get("source_section_keys", {})
                if not isinstance(source_section_keys, dict):
                    source_section_keys = {}
                selected_support = sorted(set(source_headings) & selected_ids)
                source_summaries = metadata.get("source_summaries")
                if isinstance(source_summaries, dict):
                    selected_summaries = {
                        key: value
                        for key, value in source_summaries.items()
                        if key in selected_support and isinstance(value, str)
                    }
                    if not selected_summaries or (
                        metadata.get("pinned")
                        and (
                            set(selected_support) != set(source_headings)
                            or set(selected_summaries) != set(source_headings)
                        )
                    ):
                        continue
                    summary = "\n\n".join(
                        "{}：{}".format(key, value)
                        for key, value in sorted(selected_summaries.items())
                    )[:2000]
                else:
                    if set(source_headings) - selected_ids:
                        continue
                    summary = metadata.get("summary", "")
                related_tokens = _tokens(
                    "{} {}".format(metadata.get("title", ""), summary)
                )
                source_headings_for_source = source_headings.get(source_id, [])
                source_section_keys_for_source = (
                    source_section_keys.get(source_id, [])
                    if isinstance(source_section_keys, dict)
                    else []
                )
                matching_section_keys = (
                    set(source_section_keys_for_source) & requested_section_keys
                    if isinstance(source_section_keys_for_source, list)
                    else set()
                )
                if not matching_section_keys and source_id not in source_section_keys:
                    # Legacy entries only have headings. Use those as a precise
                    # fallback when a heading identifies one section in this batch.
                    matching_section_keys = {
                        section_key
                        for heading in source_headings_for_source
                        if isinstance(heading, str)
                        and len(heading_section_keys.get(heading, ())) == 1
                        for section_key in heading_section_keys[heading]
                    } if isinstance(source_headings_for_source, list) else set()
                entry = {
                    "id": metadata["entry_id"],
                    "title": metadata.get("title", ""),
                    "summary": summary,
                    "layer": metadata.get("layer", "topic"),
                    "topic_id": metadata.get("topic_id"),
                    "topic_title": metadata.get("topic_title"),
                    "source_ids": selected_support,
                    "pinned": bool(metadata.get("pinned")),
                    "source_headings": {
                        key: value for key, value in source_headings.items() if key in selected_ids
                    },
                    "source_section_keys": {
                        key: value
                        for key, value in source_section_keys.items()
                        if key in selected_ids
                    } if isinstance(source_section_keys, dict) else {},
                }
                if matching_section_keys:
                    heading_matches.append(entry)
                elif focus_tokens & related_tokens:
                    related_matches.append(entry)
                elif force and source_id in source_headings:
                    forced_source_matches.append(entry)

        for matches in (heading_matches, related_matches, forced_source_matches):
            matches.sort(key=lambda entry: entry["id"])

        found = []
        uncovered = []
        total = 0
        for entry in [*heading_matches, *related_matches, *forced_source_matches]:
            size = len(entry["title"]) + len(entry["summary"])
            if len(found) < _MAX_RELATED_ENTRIES and total + size <= _MAX_RELATED_CHARS:
                found.append(entry)
                total += size
            elif entry in heading_matches:
                uncovered.append(entry["id"])
        if include_uncovered:
            return found, uncovered
        return found

    def _apply_changes(
        self,
        memory_files,
        source_id,
        changes,
        changed_sections,
        suppressed_entries,
        allowed_entry_ids,
        source_heading_updates,
        source_section_key_updates,
        source_summary_updates,
        progressed_topic_ids=None,
        *,
        replace_source_headings=False,
    ):
        suppressed_ids = {
            item.get("entry_id")
            for item in suppressed_entries
            if isinstance(item, dict) and isinstance(item.get("entry_id"), str)
        } if isinstance(suppressed_entries, list) else set()
        index = self._entry_index(memory_files)
        available_section_headings = {
            item.get("section_key"): item.get("heading", "未分节内容")
            for item in changed_sections
            if isinstance(item.get("section_key"), str) and item.get("heading")
        }
        for change in changes:
            entry_id = change["entry_id"]
            existing = index.get(entry_id)
            if change["action"] == "remove":
                if entry_id in suppressed_ids:
                    continue
                if (
                    entry_id not in allowed_entry_ids
                    or existing is None
                    or source_id not in existing["metadata"].get("source_headings", {})
                ):
                    raise LearningContextError("AI removal did not target a related auto-managed entry")
                old_relative, old_metadata = existing["relative_path"], existing["metadata"]
                if old_metadata.get("pinned"):
                    continue
                updated = deepcopy(old_metadata)
                updated["source_headings"].pop(source_id, None)
                source_section_keys = updated.get("source_section_keys")
                if isinstance(source_section_keys, dict):
                    source_section_keys.pop(source_id, None)
                    if source_section_keys:
                        updated["source_section_keys"] = source_section_keys
                    else:
                        updated.pop("source_section_keys", None)
                source_summaries = updated.get("source_summaries")
                if isinstance(source_summaries, dict):
                    source_summaries.pop(source_id, None)
                    updated["source_summaries"] = source_summaries
                    if source_summaries:
                        updated["summary"] = _entry_summary(source_summaries)
                if updated["source_headings"]:
                    if not isinstance(source_summaries, dict) and updated.get("summary"):
                        updated["support_state"] = "needs_review"
                    _replace_entry(memory_files, old_relative, entry_id, _render_entry(updated))
                else:
                    if old_metadata.get("pinned"):
                        updated["support_state"] = "source_removed"
                        _replace_entry(memory_files, old_relative, entry_id, _render_entry(updated))
                    else:
                        _remove_entry(memory_files, old_relative, entry_id)
                if updated["source_headings"]:
                    index[entry_id] = {"relative_path": old_relative, "metadata": updated}
                else:
                    index.pop(entry_id, None)
                continue

            support_section_keys = change.get("support_section_keys")
            if (
                not isinstance(support_section_keys, list)
                or not support_section_keys
                or len(set(support_section_keys)) != len(support_section_keys)
                or any(key not in available_section_headings for key in support_section_keys)
            ):
                raise LearningContextError(
                    "AI upsert must cite exact section keys from the current batch"
                )
            support_headings = [available_section_headings[key] for key in support_section_keys]
            relative = _layer_path(change["layer"], change.get("topic_id"))
            topic_id = change.get("topic_id")
            if entry_id in suppressed_ids:
                continue
            if existing and existing["metadata"].get("pinned"):
                continue
            if (
                existing
                and entry_id not in allowed_entry_ids
            ):
                raise LearningContextError("AI update did not target a related auto-managed entry")
            if (
                change["layer"] == "topic"
                and isinstance(topic_id, str)
                and isinstance(progressed_topic_ids, list)
                and topic_id not in progressed_topic_ids
                and (
                    existing is None
                    or source_id not in existing["metadata"].get("source_headings", {})
                )
            ):
                progressed_topic_ids.append(topic_id)
            source_headings = deepcopy(existing["metadata"].get("source_headings", {})) if existing else {}
            current_headings = source_heading_updates.setdefault(entry_id, set())
            source_section_keys = (
                deepcopy(existing["metadata"].get("source_section_keys", {}))
                if existing
                else {}
            )
            if not isinstance(source_section_keys, dict):
                source_section_keys = {}
            current_section_keys = source_section_key_updates.setdefault(entry_id, set())
            if existing and not replace_source_headings:
                old_headings = existing["metadata"].get("source_headings", {}).get(source_id, [])
                if isinstance(old_headings, list):
                    current_headings.update(
                        heading for heading in old_headings if isinstance(heading, str)
                    )
                old_section_key_map = existing["metadata"].get("source_section_keys", {})
                old_section_keys = (
                    old_section_key_map.get(source_id, [])
                    if isinstance(old_section_key_map, dict)
                    else []
                )
                if isinstance(old_section_keys, list):
                    current_section_keys.update(
                        key for key in old_section_keys if isinstance(key, str)
                    )
            current_headings.update(support_headings)
            current_section_keys.update(support_section_keys)
            source_headings[source_id] = sorted(current_headings)
            source_section_keys[source_id] = sorted(current_section_keys)
            source_summaries = {}
            legacy_summary = None
            support_state = None
            if existing:
                old_metadata = existing["metadata"]
                stored_summaries = old_metadata.get("source_summaries")
                if isinstance(stored_summaries, dict):
                    source_summaries = deepcopy(stored_summaries)
                    legacy_summary = old_metadata.get("legacy_summary")
                    support_state = old_metadata.get("support_state")
                else:
                    old_sources = list(old_metadata.get("source_headings", {}))
                    old_summary = old_metadata.get("summary", "")
                    if len(old_sources) == 1 and old_summary:
                        source_summaries[old_sources[0]] = old_summary
                    elif old_summary:
                        legacy_summary = old_summary
                        support_state = "needs_review"
            # Upserts are complete replacements for this source's one entry,
            # not delta fragments to concatenate across batches.
            source_summary_updates[entry_id] = change["summary"]
            source_summaries[source_id] = source_summary_updates[entry_id]
            summary = _entry_summary(source_summaries)
            if legacy_summary:
                summary = "旧版合并摘要（来源待复核）：{}\n\n{}".format(legacy_summary, summary)[:2000]
            entry_metadata = {
                "entry_id": entry_id,
                "owner": "auto",
                "source_headings": source_headings,
                "source_section_keys": source_section_keys,
                "layer": change["layer"],
                "topic_id": change.get("topic_id"),
                "topic_title": change.get("topic_title"),
                "title": change["title"],
                "summary": summary or change["summary"],
                "source_summaries": source_summaries,
            }
            if legacy_summary:
                entry_metadata["legacy_summary"] = legacy_summary
            if support_state:
                entry_metadata["support_state"] = support_state
            rendered = _render_entry(entry_metadata)
            if existing:
                _remove_entry(memory_files, existing["relative_path"], entry_id)
            _append_entry(memory_files, relative, rendered)
            index[entry_id] = {"relative_path": relative, "metadata": entry_metadata}

    def _remove_source(self, memory_files, source_id, preserve_entry_ids=None):
        preserve_entry_ids = set(preserve_entry_ids or ())
        for relative, content in list(memory_files.items()):
            for block in list(_entry_blocks(content)):
                metadata = block["metadata"]
                if metadata.get("entry_id") in preserve_entry_ids:
                    continue
                sources = metadata.get("source_headings", {})
                if source_id not in sources:
                    continue
                updated = deepcopy(metadata)
                updated["source_headings"].pop(source_id, None)
                source_section_keys = updated.get("source_section_keys")
                if isinstance(source_section_keys, dict):
                    source_section_keys.pop(source_id, None)
                    if source_section_keys:
                        updated["source_section_keys"] = source_section_keys
                    else:
                        updated.pop("source_section_keys", None)
                if updated["source_headings"]:
                    source_summaries = updated.get("source_summaries")
                    if isinstance(source_summaries, dict):
                        source_summaries.pop(source_id, None)
                        updated["source_summaries"] = source_summaries
                        if source_summaries:
                            updated["summary"] = _entry_summary(source_summaries)
                        elif updated.get("summary"):
                            updated["support_state"] = "needs_review"
                    else:
                        updated["support_state"] = "needs_review"
                    _replace_entry(memory_files, relative, metadata["entry_id"], _render_entry(updated))
                elif metadata.get("pinned"):
                    updated["support_state"] = "source_removed"
                    updated["source_summaries"] = {}
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

    def _ensure_active_focus(self, memory_files, selected_ids, active_topic_ids=None):
        supported = []
        selected = set(selected_ids)
        for relative, content in sorted(memory_files.items()):
            if not relative.startswith("topics/") or not relative.endswith(".md"):
                continue
            for block in _entry_blocks(content):
                metadata = block["metadata"]
                if metadata.get("layer") != "topic" or metadata.get("support_state") in {
                    "needs_review",
                    "source_removed",
                }:
                    continue
                sources = metadata.get("source_headings", {})
                if metadata.get("pinned") and not set(sources).issubset(selected):
                    continue
                selected_sources = {
                    source_id: headings
                    for source_id, headings in sources.items()
                    if source_id in selected
                }
                if selected_sources:
                    source_section_keys = metadata.get("source_section_keys", {})
                    selected_section_keys = {
                        source_id: keys
                        for source_id, keys in source_section_keys.items()
                        if source_id in selected
                    } if isinstance(source_section_keys, dict) else {}
                    supported.append((metadata, selected_sources, selected_section_keys))

        active = memory_files.get("active.md", "")
        active_entries = [
            block
            for block in _entry_blocks(active)
            if block["metadata"].get("entry_id") == "current-learning-focus"
        ]
        if not supported:
            if active_entries and not active_entries[0]["metadata"].get("pinned"):
                _remove_entry(memory_files, "active.md", "current-learning-focus")
            return
        if active_entries and active_entries[0]["metadata"].get("pinned"):
            return

        topics = {}
        for metadata, sources, section_keys in supported:
            topic_id = metadata.get("topic_id")
            title = metadata.get("topic_title")
            if not isinstance(topic_id, str) or not isinstance(title, str):
                continue
            topic = topics.setdefault(
                topic_id,
                {
                    "title": title,
                    "entries": [],
                    "source_headings": {},
                    "source_section_keys": {},
                },
            )
            topic["entries"].append(metadata.get("title", ""))
            for source_id, headings in sources.items():
                current = topic["source_headings"].setdefault(source_id, [])
                current.extend(headings if isinstance(headings, list) else [])
            for source_id, keys in section_keys.items():
                current = topic["source_section_keys"].setdefault(source_id, [])
                current.extend(keys if isinstance(keys, list) else [])
        if not topics:
            return

        selected_topic_ids = (
            list(active_topic_ids)
            if isinstance(active_topic_ids, list)
            else list(topics)
        )
        topics = {
            topic_id: topics[topic_id]
            for topic_id in selected_topic_ids
            if topic_id in topics
        }
        if not topics:
            if active_entries and not active_entries[0]["metadata"].get("pinned"):
                _remove_entry(memory_files, "active.md", "current-learning-focus")
            return

        source_headings = {}
        source_section_keys = {}
        for topic in topics.values():
            for source_id, headings in topic["source_headings"].items():
                source_headings.setdefault(source_id, []).extend(headings)
            for source_id, keys in topic["source_section_keys"].items():
                source_section_keys.setdefault(source_id, []).extend(keys)

        topic_labels = []
        details = []
        for topic_id in topics:
            topic = topics[topic_id]
            topic_labels.append(topic["title"])
            entries = list(dict.fromkeys(item for item in topic["entries"] if item))
            if entries:
                details.append("{}：{}".format(topic["title"], "、".join(entries[:3])))
        summary = "当前纳入资料主要围绕{}。已整理的相关知识包括{}。".format(
            "、".join(topic_labels[:3]), "；".join(details[:3])
        )[:1800]
        metadata = {
            "entry_id": "current-learning-focus",
            "owner": "auto",
            "source_headings": {
                source_id: sorted(set(headings))
                for source_id, headings in sorted(source_headings.items())
            },
            "source_section_keys": {
                source_id: sorted(set(keys))
                for source_id, keys in sorted(source_section_keys.items())
            },
            "layer": "active",
            "title": "当前关注：{}".format("、".join(topic_labels[:2]))[:200],
            "summary": summary,
        }
        rendered = _render_entry(metadata)
        if active_entries:
            _replace_entry(memory_files, "active.md", "current-learning-focus", rendered)
        else:
            _append_entry(memory_files, "active.md", rendered)

    def _updated_topic_index(self, memory_files, progressed_topic_ids=None):
        try:
            index = self.service._read_yaml("index.yaml", {"topics": []})
            if not isinstance(index, dict) or not isinstance(index.get("topics", []), list):
                raise LearningContextError("index.yaml must contain a topics list")
            original_index = deepcopy(index)
            topics = [dict(item) for item in index.get("topics", []) if isinstance(item, dict)]
            by_id = {item.get("id"): item for item in topics if isinstance(item.get("id"), str)}
            discovered = {}
            selected_ids = set(self.service._read_sources())
            source_titles = {
                item["id"]: item["title"]
                for item in self.service._selected_source_summaries()
            }
            for relative, content in memory_files.items():
                if not relative.startswith("topics/") or not relative.endswith(".md"):
                    continue
                topic_file_id = Path(relative).stem
                for block in _entry_blocks(content):
                    metadata = block["metadata"]
                    topic_id = metadata.get("topic_id")
                    topic_title = metadata.get("topic_title")
                    source_headings = metadata.get("source_headings", {})
                    if (
                        metadata.get("layer") == "topic"
                        and topic_id == topic_file_id
                        and isinstance(topic_title, str)
                        and metadata.get("support_state") not in {"needs_review", "source_removed"}
                        and isinstance(source_headings, dict)
                        and set(source_headings) & selected_ids
                    ):
                        item = discovered.setdefault(
                            topic_id,
                            {"title": topic_title, "aliases": [], "keywords": []},
                        )
                        item["aliases"].append(metadata.get("title", ""))
                        item["keywords"].extend(
                            heading
                            for source_id, values in source_headings.items()
                            if source_id in selected_ids
                            if isinstance(values, list)
                            for heading in values
                            if isinstance(heading, str)
                        )
                        item["keywords"].extend(
                            source_titles[source_id]
                            for source_id in source_headings
                            if source_id in selected_ids
                            if source_id in source_titles
                        )
            for topic_id, derived in discovered.items():
                topic = by_id.get(topic_id)
                if topic is None:
                    topic = {
                        "id": topic_id,
                        "title": derived["title"],
                        "aliases": [],
                        "keywords": [],
                    }
                    topics.append(topic)
                    by_id[topic_id] = topic
                topic["title"] = derived["title"]

            for topic in topics:
                topic_id = topic.get("id")
                if not isinstance(topic_id, str):
                    continue
                derived = discovered.get(
                    topic_id, {"title": topic.get("title", ""), "aliases": [], "keywords": []}
                )
                aliases = _merge_index_values(
                    topic.get("aliases", []),
                    [topic_id.replace("-", " "), *_TOPIC_BILINGUAL_NAMES.get(topic_id, ())],
                )
                existing_keywords = topic.get("keywords", [])
                existing_keywords = (
                    existing_keywords if isinstance(existing_keywords, list) else []
                )
                previous_derived = topic.get("derived_keywords", [])
                previous_derived = (
                    previous_derived if isinstance(previous_derived, list) else []
                )
                manual_keywords = topic.get("manual_keywords")
                if not isinstance(manual_keywords, list):
                    # Legacy indexes did not record keyword provenance. Preserve
                    # their values as user-managed rather than deleting intent.
                    previous_derived_keys = {
                        " ".join(item.split()).casefold()
                        for item in previous_derived
                        if isinstance(item, str)
                    }
                    manual_keywords = [
                        item
                        for item in existing_keywords
                        if not isinstance(item, str)
                        or " ".join(item.split()).casefold() not in previous_derived_keys
                    ]
                manual_keys = {
                    " ".join(item.split()).casefold()
                    for item in manual_keywords
                    if isinstance(item, str)
                }
                previous_derived_keys = {
                    " ".join(item.split()).casefold()
                    for item in previous_derived
                    if isinstance(item, str)
                }
                manual_keywords = _merge_index_values(
                    manual_keywords,
                    [
                        item
                        for item in existing_keywords
                        if isinstance(item, str)
                        and " ".join(item.split()).casefold()
                        not in manual_keys | previous_derived_keys
                    ],
                )
                derived_keywords = _merge_index_values(
                    [],
                    [
                        topic_id.replace("-", " "),
                        derived["title"],
                        *derived["aliases"],
                        *derived["keywords"],
                        *sorted(_tokens(" ".join(derived["keywords"]))),
                    ],
                )
                keywords = _merge_index_values(manual_keywords, derived_keywords)
                if (
                    topic.get("aliases") != aliases
                    or topic.get("keywords") != keywords
                    or topic.get("manual_keywords") != manual_keywords
                    or topic.get("derived_keywords") != derived_keywords
                ):
                    topic["aliases"] = aliases
                    topic["keywords"] = keywords
                    topic["manual_keywords"] = manual_keywords
                    topic["derived_keywords"] = derived_keywords

            old_active = index.get("active_topic_ids", [])
            old_active = (
                [topic_id for topic_id in old_active if isinstance(topic_id, str)]
                if isinstance(old_active, list)
                else []
            )
            if not old_active:
                old_active = self._legacy_active_topic_ids(memory_files, discovered)
            progressed = []
            for topic_id in progressed_topic_ids or []:
                if (
                    isinstance(topic_id, str)
                    and topic_id in discovered
                    and topic_id not in progressed
                ):
                    progressed.append(topic_id)
            manually_current = [
                topic["id"]
                for topic in topics
                if topic.get("manual_status") == "current"
                and topic.get("id") in discovered
            ]
            if progressed:
                active_candidates = [*manually_current, *progressed]
            else:
                active_candidates = [*manually_current, *old_active]
            active_topic_ids = []
            for topic_id in active_candidates:
                topic = by_id.get(topic_id)
                if (
                    topic_id not in discovered
                    or topic is None
                    or topic.get("manual_status") == "history"
                    or topic_id in active_topic_ids
                ):
                    continue
                active_topic_ids.append(topic_id)
                if len(active_topic_ids) >= 3:
                    break
            index["active_topic_ids"] = active_topic_ids
            index["topics"] = topics
            rendered = yaml.safe_dump(index, allow_unicode=True, sort_keys=False)
            original_rendered = yaml.safe_dump(
                original_index, allow_unicode=True, sort_keys=False
            )
            return (rendered if rendered != original_rendered else None), active_topic_ids
        except Exception as error:
            raise LearningContextError("Could not update the learning topic index") from error

    @staticmethod
    def _legacy_active_topic_ids(memory_files, discovered):
        active = memory_files.get("active.md", "")
        focus = next(
            (
                block["metadata"].get("title", "")
                for block in _entry_blocks(active)
                if block["metadata"].get("entry_id") == "current-learning-focus"
            ),
            "",
        )
        focus = focus.removeprefix("当前关注：")
        names = [item.strip() for item in re.split(r"[、,，]", focus) if item.strip()]
        by_title = {
            values["title"].casefold(): topic_id for topic_id, values in discovered.items()
        }
        matched = [by_title[name.casefold()] for name in names if name.casefold() in by_title]
        return matched or list(discovered)

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
                "message": "同步期间资料范围或上下文发生变化；为避免覆盖刚保存的内容，请重试。原内容与处理基准均已保留。",
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
        if "AI" in reason or "Gateway" in reason or "DeepSeek" in reason:
            message = "AI 分析失败；学习上下文和已处理基准已保留，可重试。"
        elif reason == "LearningNoteTooLarge":
            message = "所选笔记超过同步大小限制；已有上下文和处理基准已保留。"
        elif reason in {"LearningContextError", "ValidationError", "ValueError", "TypeError"}:
            message = "所选笔记或学习上下文内容无法处理；已有内容和基准已保留。"
        else:
            message = "本地文件或同步过程失败；学习上下文和已处理基准已保留，可重试。"
        status = deepcopy(self.service._read_status())
        status.update(
            {
                "state": "failed",
                "message": message,
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
            "message": message,
            "analyzed_count": 0,
            "skipped_count": 0,
            "source_results": [],
        }
