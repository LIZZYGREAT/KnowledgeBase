"""File-backed learning progress context for Terms and Research recommendations."""

from __future__ import annotations

from pathlib import Path
import json
import os
import re
import tempfile
from typing import Any, Iterable, Optional

import yaml

from backend.app.domain.document import DocumentMetadata
from backend.app.services.markdown_parser import parse_markdown


_SOURCE_TYPES = {"paper-note", "learning-note", "course-note"}
_TOPIC_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_CANONICAL_BYTES = 2 * 1024 * 1024
_MAX_MEMORY_BYTES = 512 * 1024
_MAX_RECOMMENDATION_TOPICS = 3
_MAX_RECOMMENDATION_PREFERENCE_ITEMS = 12
_DEFAULT_PREFERENCES = {
    "fixed_direction": "",
    "keywords": [],
    "exclude_keywords": [],
    "exploration_directions": [],
    "important_anchors": [],
}


def _paragraph_units(markdown: str) -> list[str]:
    units = []
    current = []
    fence = None
    for line in markdown.splitlines(keepends=True):
        current.append(line)
        fence_match = re.match(r"^\s*(```+|~~~+)", line)
        if fence_match:
            marker = fence_match.group(1)[:3]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
        if not line.strip() and fence is None:
            text = "".join(current)
            if text.strip():
                units.append(text)
            current = []
    if current:
        units.append("".join(current))

    # Keep headings with the paragraph they introduce so truncation cannot
    # leave a dangling heading at the end of the recommendation context.
    merged = []
    pending_heading = ""
    for unit in units:
        if re.match(r"^\s{0,3}#{1,6}\s+[^\n]+\s*$", unit):
            pending_heading += unit
            continue
        if pending_heading:
            merged.append(pending_heading + unit)
            pending_heading = ""
        else:
            merged.append(unit)
    if pending_heading:
        merged.append(pending_heading)
    return merged


def _complete_memory_units(markdown: str) -> list[str]:
    from backend.app.services.learning_context_sync_entries import entry_blocks

    units = []
    cursor = 0
    for block in entry_blocks(markdown):
        units.extend(_paragraph_units(markdown[cursor:block["start"]]))
        units.append(block["text"])
        cursor = block["end"]
    units.extend(_paragraph_units(markdown[cursor:]))
    return units


def _truncate_complete_markdown(markdown: str, max_chars: int) -> str:
    if len(markdown) <= max_chars:
        return markdown
    remaining = max_chars
    kept = []
    for unit in _complete_memory_units(markdown):
        if len(unit) > remaining:
            continue
        kept.append(unit)
        remaining -= len(unit)
    return "".join(kept)


def _manual_markdown(markdown: str) -> str:
    """Return user-authored text outside auto-managed entry markers."""
    from backend.app.services.learning_context_sync_entries import entry_blocks

    parts = []
    cursor = 0
    for block in entry_blocks(markdown):
        parts.append(markdown[cursor:block["start"]])
        cursor = block["end"]
    parts.append(markdown[cursor:])
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _selected_memory(markdown: str, selected_source_ids: set[str]) -> str:
    from backend.app.services.learning_context_sync_entries import entry_blocks, render_entry

    selected_blocks = []
    for block in entry_blocks(markdown):
        metadata = block["metadata"]
        if metadata.get("support_state") in {"needs_review", "source_removed"}:
            continue
        source_headings = metadata.get("source_headings", {})
        all_sources = set(source_headings)
        supported_sources = all_sources & selected_source_ids
        if not supported_sources:
            continue
        source_summaries = metadata.get("source_summaries")
        if isinstance(source_summaries, dict):
            supported_summaries = {
                source_id: summary
                for source_id, summary in source_summaries.items()
                if source_id in supported_sources and isinstance(summary, str)
            }
            if not supported_summaries:
                continue
            if metadata.get("pinned") and (
                supported_sources != all_sources
                or set(source_summaries) != all_sources
                or set(supported_summaries) != all_sources
            ):
                continue
            updated = dict(metadata)
            updated["source_headings"] = {
                source_id: source_headings[source_id]
                for source_id in sorted(supported_sources)
            }
            updated["source_summaries"] = supported_summaries
            updated["summary"] = "\n\n".join(
                "{}：{}".format(source_id, summary)
                for source_id, summary in sorted(supported_summaries.items())
            )[:2000]
            selected_blocks.append(
                render_entry(updated)
                if supported_sources != all_sources or set(source_summaries) != all_sources
                else block["text"]
            )
        elif supported_sources != all_sources:
            # Legacy merged summaries cannot be attributed to a subset of their
            # source notes, so exclude them until synchronization marks them for review.
            continue
        else:
            selected_blocks.append(block["text"])
    return "\n\n".join(selected_blocks)


def _recommendation_source_ids(markdowns: Iterable[str]) -> set[str]:
    """Return selected-note IDs attached to entries actually present in context."""
    from backend.app.services.learning_context_sync_entries import entry_blocks

    source_ids = set()
    for markdown in markdowns:
        for block in entry_blocks(markdown):
            metadata = block["metadata"]
            if metadata.get("support_state") in {"needs_review", "source_removed"}:
                continue
            source_headings = metadata.get("source_headings", {})
            if isinstance(source_headings, dict):
                source_ids.update(
                    source_id
                    for source_id in source_headings
                    if isinstance(source_id, str) and source_id
                )
    return source_ids


class LearningContextError(ValueError):
    """Invalid learning context input or unsafe local context path."""


class LearningContextService:
    """Own local learning context files without writing canonical knowledge."""

    def __init__(self, repository_root: Path, ai_gateway=None):
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        self.documents_root = self.knowledge_root / "documents"
        self.context_root = self.repository_root / "storage" / "learning-context"
        self.ai_gateway = ai_gateway
        self._sync_progress: Optional[dict[str, Any]] = None

    def _set_sync_progress(self, value: Optional[dict[str, Any]]) -> None:
        self._sync_progress = dict(value) if isinstance(value, dict) else None

    def _update_sync_progress(self, **values: Any) -> None:
        current = dict(self._sync_progress or {})
        current.update(values)
        self._sync_progress = current

    def sync(
        self,
        *,
        dry_run: bool = False,
        force: bool = False,
        source_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Check selected notes and incrementally update local context."""
        from backend.app.services.learning_context_sync import LearningContextSync

        return LearningContextSync(self, self.ai_gateway).run(
            dry_run=dry_run,
            force=force,
            source_id=source_id,
        )

    def sync_if_stale(self) -> dict[str, Any]:
        """Refresh selected-note evidence when a local check finds pending changes."""
        previous_status = self._read_status()
        try:
            preview = self.sync(dry_run=True)
        except Exception:
            return {
                "state": "check_failed",
                "stale": True,
                "used_previous_context": True,
                "message": "无法确认学习笔记是否有待同步变化；本次使用上次保存的学习上下文。",
            }

        pending_scope = bool(
            previous_status.get("pending_added_ids")
            or previous_status.get("pending_removed_ids")
        )
        changed_sources = any(
            isinstance(item, dict)
            and item.get("action") in {"analyze", "skipped", "missing"}
            for item in preview.get("source_results", [])
        )
        selected = self._read_sources()
        stale_status = bool(selected) and previous_status.get("state") in {
            "not_synced",
            "failed",
            "needs_manual_review",
        }
        stale = pending_scope or changed_sources or stale_status
        if not stale:
            return {
                "state": previous_status.get("state", "synced"),
                "stale": False,
                "used_previous_context": False,
                "message": previous_status.get("message", "学习上下文已是最新。"),
            }

        try:
            result = self.sync()
        except Exception:
            result = {"state": "failed", "message": "同步过程未能完成。"}
        if result.get("state") in {"synced", "no_sources"}:
            return {
                **result,
                "stale": False,
                "used_previous_context": False,
            }
        return {
            **result,
            "stale": True,
            "used_previous_context": True,
            "message": "学习上下文同步未完成；本次使用上次保存的学习上下文。{}".format(
                result.get("message", "")
            ),
        }

    def get_sources(self) -> dict[str, Any]:
        """Return explicit selections and selectable published learning notes."""
        available = self.available_sources()
        selected = self._read_sources()
        available_by_id = {item["id"]: item for item in available}
        # Canonical files can be removed between requests. Preserve the user's
        # selection in the local file but report missing IDs as unresolved.
        return {
            "included_document_ids": selected,
            "missing_document_ids": [item for item in selected if item not in available_by_id],
            "available_documents": available,
        }

    def available_sources(self) -> list[dict[str, str]]:
        if not self.documents_root.is_dir():
            return []
        documents: list[dict[str, str]] = []
        for path in sorted(self.documents_root.rglob("*.md")):
            if not self._safe_canonical_file(path):
                continue
            try:
                if path.stat().st_size > _MAX_CANONICAL_BYTES:
                    continue
                parsed = parse_markdown(path.read_text(encoding="utf-8"))
                metadata = DocumentMetadata.model_validate(parsed.frontmatter)
            except (OSError, UnicodeError, ValueError, TypeError):
                continue
            if path.stem != metadata.id or metadata.type not in _SOURCE_TYPES:
                continue
            documents.append(
                {"id": metadata.id, "title": metadata.title, "type": metadata.type}
            )
        return documents

    def set_sources(self, included_document_ids: Iterable[str]) -> dict[str, Any]:
        ids = self._normalize_ids(included_document_ids, "included_document_ids")
        previous = self._read_sources()
        available_by_id = {item["id"]: item for item in self.available_sources()}
        unknown = [item for item in ids if item not in available_by_id]
        if unknown:
            raise LearningContextError(
                "Only existing canonical learning documents can be selected: {}".format(
                    ", ".join(unknown)
                )
            )
        self._write_yaml("sources.yaml", {"included_document_ids": ids})
        if ids != previous:
            state = self._read_status()
            added = [item for item in ids if item not in previous]
            removed = [item for item in previous if item not in ids]
            state.update(
                {
                    "state": "pending",
                    "message": (
                        "新增 {} 篇待分析".format(len(added))
                        if added and not removed
                        else "学习资料范围已更新，待同步"
                    ),
                    "pending_added_ids": added,
                    "pending_removed_ids": removed,
                }
            )
            self._write_status(state)
        return self.get_sources()

    def get_preferences(self) -> dict[str, Any]:
        stored = self._read_yaml("preferences.yaml", {})
        if not isinstance(stored, dict):
            raise LearningContextError("preferences.yaml must contain a mapping")
        result = dict(_DEFAULT_PREFERENCES)
        result.update(stored)
        return self._validate_preferences(result)

    def set_preferences(self, value: dict[str, Any]) -> dict[str, Any]:
        validated = self._validate_preferences(value)
        self._write_yaml("preferences.yaml", validated)
        return validated

    def get_context(
        self,
        topic_id: Optional[str] = None,
        focus: Optional[str] = None,
        include_important: bool = False,
        max_chars: int = 8000,
    ) -> dict[str, Any]:
        """Assemble only requested layers and relevant topics for a caller."""
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 100 <= max_chars <= 30000:
            raise LearningContextError("max_chars must be between 100 and 30000")
        preferences = self.get_preferences()
        topics = self.list_topics()
        selected_topics: list[dict[str, str]] = []
        if topic_id:
            selected_topics = [self.read_topic(topic_id)]
        elif focus:
            selected_topics = [
                self.read_topic(item["id"])
                for item in self._match_topics(focus, topics)
            ]

        selected_source_ids = {
            item["id"] for item in self._selected_source_summaries()
        }
        raw_active = _selected_memory(
            self._read_memory("active.md"), selected_source_ids
        )
        user_direction = _manual_markdown(self._read_memory("active.md"))[:1000]
        raw_important = (
            _selected_memory(self._read_memory("important.md"), selected_source_ids)
            if include_important
            else ""
        )
        direction_budget = min(len(user_direction), max_chars // 8)
        user_direction = user_direction[:direction_budget]
        remaining_context_chars = max(0, max_chars - direction_budget)
        topic_reserve = remaining_context_chars // 2 if selected_topics else 0
        active = _truncate_complete_markdown(
            raw_active, remaining_context_chars - topic_reserve
        )
        remaining = max(0, remaining_context_chars - len(active))
        important = _truncate_complete_markdown(
            raw_important, min(remaining, max_chars // 4)
        )
        remaining = max(
            0, remaining_context_chars - len(active) - len(important)
        )
        bounded_topics = []
        for topic in selected_topics:
            if remaining == 0:
                break
            filtered = _selected_memory(topic["markdown"], selected_source_ids)
            body = _truncate_complete_markdown(filtered, remaining)
            if not body:
                continue
            bounded_topics.append({**topic, "markdown": body})
            remaining -= len(body)
        return {
            "selected_source_ids": self._read_sources(),
            "included_sources": self._selected_source_summaries(),
            "preferences": preferences,
            "active": active,
            "important": important,
            "user_direction": user_direction,
            "topics": bounded_topics,
            "topic_index": topics,
        }

    def get_recommendation_context(
        self, focus: str, max_chars: int = 8000
    ) -> dict[str, Any]:
        """Return a bounded, selected-source context for recommendation services."""
        raw = self.get_context(
            focus=focus,
            include_important=True,
            max_chars=max_chars,
        )
        preferences = raw["preferences"]
        bounded_preferences = {
            "fixed_direction": preferences["fixed_direction"][:300],
        }
        for field in (
            "keywords",
            "exclude_keywords",
            "exploration_directions",
            "important_anchors",
        ):
            bounded_preferences[field] = [
                " ".join(value.split())[:160]
                for value in preferences[field][:_MAX_RECOMMENDATION_PREFERENCE_ITEMS]
            ]
        contributing_source_ids = _recommendation_source_ids(
            [
                raw["active"],
                raw["important"],
                *(item["markdown"] for item in raw["topics"]),
            ]
        )
        selected_sources = {
            item["id"]: item
            for item in raw["included_sources"]
            if isinstance(item.get("id"), str)
        }
        included_sources = [
            {
                "id": source_id,
                "title": selected_sources[source_id]["title"],
                "type": selected_sources[source_id]["type"],
            }
            for source_id in sorted(contributing_source_ids)
            if source_id in selected_sources
        ]
        return {
            "included_source_count": len(included_sources),
            "included_sources": included_sources,
            "preferences": bounded_preferences,
            "active": raw["active"],
            "important": raw["important"],
            "user_direction": raw["user_direction"],
            "topics": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "aliases": item["aliases"][:12],
                    "keywords": item["keywords"][:12],
                    "markdown": item["markdown"],
                }
                for item in raw["topics"][:_MAX_RECOMMENDATION_TOPICS]
            ],
        }

    def get_overview(self) -> dict[str, Any]:
        status = self._read_status()
        internal_status_keys = {"user_managed_files", "manual_revision", "suppressed_entries"}
        public_status = {
            key: value for key, value in status.items() if key not in internal_status_keys
        }
        if self._sync_progress is not None:
            public_status.update(
                {
                    "state": "syncing",
                    "message": "正在分析所选学习资料",
                    "sync_progress": dict(self._sync_progress),
                }
            )
        return {
            "sources": self.get_sources(),
            "preferences": self.get_preferences(),
            "active": self._read_memory("active.md"),
            "important": self._read_memory("important.md"),
            "topics": self.list_topics(),
            "status": public_status,
            "manual_entries": self._manual_entry_statuses(status),
            "editable_entries": self._editable_entry_details(),
        }

    def save_memory(self, layer: str, markdown: str) -> dict[str, Any]:
        if layer not in {"active", "important"}:
            raise LearningContextError("Memory layer must be active or important")
        pinned_entry_ids = self._save_user_memory("{}.md".format(layer), markdown)
        return {
            "layer": layer,
            "markdown": markdown,
            "pinned_entry_ids": pinned_entry_ids,
        }

    def save_topic(self, topic_id: str, markdown: str) -> dict[str, Any]:
        topic = self.read_topic(topic_id)
        relative = "topics/{}.md".format(topic["id"])
        pinned_entry_ids = self._save_user_memory(relative, markdown)
        return {
            **topic,
            "markdown": markdown,
            "pinned_entry_ids": pinned_entry_ids,
        }

    def update_memory_entry(
        self,
        layer: str,
        entry_id: str,
        title: str,
        summary: str,
        topic_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if layer in {"active", "important"} and topic_id is None:
            relative = "{}.md".format(layer)
        elif layer == "topic" and isinstance(topic_id, str):
            self.read_topic(topic_id)
            relative = "topics/{}.md".format(topic_id)
        else:
            raise LearningContextError("Invalid memory entry layer")
        if not isinstance(entry_id, str) or not _TOPIC_ID.fullmatch(entry_id):
            raise LearningContextError("Invalid learning context entry ID")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            raise LearningContextError("Entry title must contain 1 to 200 characters")
        if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 2000:
            raise LearningContextError("Entry text must contain 1 to 2000 characters")

        from backend.app.services.learning_context_sync_entries import (
            entry_blocks,
            render_entry,
            replace_entry,
        )

        original = self._read_memory(relative)
        block = next(
            (
                item
                for item in entry_blocks(original)
                if item["metadata"].get("entry_id") == entry_id
            ),
            None,
        )
        if block is None:
            raise LookupError("Learning context entry '{}' does not exist".format(entry_id))
        metadata = dict(block["metadata"])
        metadata["title"] = title.strip()
        metadata["summary"] = summary.strip()
        metadata["pinned"] = True
        metadata.pop("user_body", None)
        memory_files = {relative: original}
        replace_entry(memory_files, relative, entry_id, render_entry(metadata))
        state = self._read_status()
        revision = state.get("manual_revision", 0)
        state["manual_revision"] = (
            revision if isinstance(revision, int) and not isinstance(revision, bool) else 0
        ) + 1
        self._atomic_write(relative, memory_files[relative])
        self._write_status(state)
        return {
            "relative_path": relative,
            "entry_id": entry_id,
            "title": metadata["title"],
            "summary": metadata["summary"],
            "pinned": True,
            "markdown": memory_files[relative],
            "manual_entries": self._manual_entry_statuses(state),
        }

    def restore_automatic_memory(
        self,
        layer: str,
        topic_id: Optional[str] = None,
        entry_id: Optional[str] = None,
        confirm_support: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(confirm_support, bool):
            raise LearningContextError("confirm_support must be a boolean")
        if confirm_support and entry_id is None:
            raise LearningContextError("A specific entry is required to confirm source support")
        if layer in {"active", "important"} and topic_id is None:
            relative = "{}.md".format(layer)
        elif layer == "topic" and topic_id is not None:
            self.read_topic(topic_id)
            relative = "topics/{}.md".format(topic_id)
        else:
            raise LearningContextError("Invalid memory layer")
        state = self._read_status()
        from backend.app.services.learning_context_sync_entries import (
            entry_blocks,
            replace_entry,
            render_entry,
        )

        original_content = self._read_memory(relative)
        memory_files = {relative: original_content}
        legacy_files = state.get("user_managed_files", [])
        legacy_managed = isinstance(legacy_files, list) and relative in legacy_files
        if entry_id is not None and legacy_managed:
            for block in reversed(entry_blocks(memory_files[relative])):
                metadata = dict(block["metadata"])
                if not metadata.get("pinned"):
                    metadata["pinned"] = True
                    current_content = memory_files[relative]
                    memory_files[relative] = (
                        current_content[:block["start"]]
                        + render_entry(metadata)
                        + current_content[block["end"]:]
                    )
        if entry_id is not None:
            if not isinstance(entry_id, str) or not _TOPIC_ID.fullmatch(entry_id):
                raise LearningContextError("Invalid learning context entry ID")
            block = next(
                (
                    item
                    for item in entry_blocks(memory_files[relative])
                    if item["metadata"].get("entry_id") == entry_id
                ),
                None,
            )
            if block is not None and confirm_support:
                metadata = dict(block["metadata"])
                if metadata.get("support_state") != "needs_review":
                    raise LearningContextError("Only entries awaiting source review can be confirmed")
                source_ids = set(metadata.get("source_headings", {}))
                selected_ids = set(self._read_sources())
                available_ids = {item["id"] for item in self.available_sources()}
                if not source_ids or not source_ids.issubset(selected_ids & available_ids):
                    raise LearningContextError(
                        "All remaining supporting notes must be selected and available before confirmation"
                    )
                legacy_summary = metadata.get("legacy_summary") or metadata.get("summary")
                if not isinstance(legacy_summary, str) or not legacy_summary.strip():
                    raise LearningContextError("The entry has no summary to confirm")
                metadata["source_summaries"] = {
                    source_id: legacy_summary for source_id in sorted(source_ids)
                }
                metadata["summary"] = "\n\n".join(
                    "{}：{}".format(source_id, legacy_summary)
                    for source_id in sorted(source_ids)
                )[:2000]
                metadata.pop("legacy_summary", None)
                metadata.pop("support_state", None)
                replace_entry(memory_files, relative, entry_id, render_entry(metadata))
            elif block is not None and block["metadata"].get("pinned"):
                metadata = dict(block["metadata"])
                metadata["pinned"] = False
                replace_entry(memory_files, relative, entry_id, render_entry(metadata))
            suppressed = state.get("suppressed_entries", [])
            if not isinstance(suppressed, list):
                suppressed = []
            state["suppressed_entries"] = [
                item
                for item in suppressed
                if not (
                    isinstance(item, dict)
                    and item.get("relative_path") == relative
                    and item.get("entry_id") == entry_id
                )
            ]
        else:
            for block in entry_blocks(memory_files[relative]):
                if block["metadata"].get("pinned"):
                    metadata = dict(block["metadata"])
                    metadata["pinned"] = False
                    replace_entry(memory_files, relative, metadata["entry_id"], render_entry(metadata))
            suppressed = state.get("suppressed_entries", [])
            if not isinstance(suppressed, list):
                suppressed = []
            state["suppressed_entries"] = [
                item
                for item in suppressed
                if not (isinstance(item, dict) and item.get("relative_path") == relative)
            ]
        if isinstance(legacy_files, list):
            remaining_legacy_files = [item for item in legacy_files if item != relative]
            if remaining_legacy_files:
                state["user_managed_files"] = remaining_legacy_files
            else:
                state.pop("user_managed_files", None)
        revision = state.get("manual_revision", 0)
        state["manual_revision"] = (
            revision if isinstance(revision, int) and not isinstance(revision, bool) else 0
        ) + 1
        if memory_files[relative] != original_content:
            self._atomic_write(relative, memory_files[relative])
        self._write_status(state)
        return {
            "relative_path": relative,
            "markdown": memory_files[relative],
            "manual_entries": self._manual_entry_statuses(state),
        }

    def list_topics(self) -> list[dict[str, Any]]:
        index = self._read_yaml("index.yaml", {"topics": []})
        if not isinstance(index, dict) or not isinstance(index.get("topics", []), list):
            raise LearningContextError("index.yaml must contain a topics list")
        listed = []
        seen: set[str] = set()
        active_topic_ids = index.get("active_topic_ids", [])
        active_topic_ids = (
            set(value for value in active_topic_ids if isinstance(value, str))
            if isinstance(active_topic_ids, list)
            else set()
        )
        for item in index.get("topics", []):
            if not isinstance(item, dict):
                continue
            topic_id = item.get("id")
            title = item.get("title")
            if not isinstance(topic_id, str) or not _TOPIC_ID.fullmatch(topic_id):
                continue
            if topic_id in seen or not isinstance(title, str) or not title.strip():
                continue
            seen.add(topic_id)
            manual_status = item.get("manual_status")
            listed.append(
                {
                    "id": topic_id,
                    "title": title.strip(),
                    "aliases": self._clean_text_list(item.get("aliases", []), "aliases"),
                    "keywords": self._clean_text_list(item.get("keywords", []), "keywords"),
                    "is_active": topic_id in active_topic_ids,
                    "manual_status": manual_status
                    if manual_status in {"current", "history"}
                    else None,
                }
            )
        return listed

    def read_topic(self, topic_id: str) -> dict[str, Any]:
        if not isinstance(topic_id, str) or not _TOPIC_ID.fullmatch(topic_id):
            raise LearningContextError("Invalid topic ID")
        for topic in self.list_topics():
            if topic["id"] == topic_id:
                return {
                    **topic,
                    "markdown": self._read_memory("topics/{}.md".format(topic_id)),
                }
        raise LookupError("Learning topic '{}' does not exist".format(topic_id))

    def set_topic_status(self, topic_id: str, status: str) -> dict[str, Any]:
        if not isinstance(topic_id, str) or not _TOPIC_ID.fullmatch(topic_id):
            raise LearningContextError("Invalid topic ID")
        if status not in {"current", "history", "automatic"}:
            raise LearningContextError("Topic status must be current, history, or automatic")

        index = self._read_yaml("index.yaml", {"topics": []})
        if not isinstance(index, dict) or not isinstance(index.get("topics", []), list):
            raise LearningContextError("index.yaml must contain a topics list")
        topics = [dict(item) for item in index["topics"] if isinstance(item, dict)]
        topic = next((item for item in topics if item.get("id") == topic_id), None)
        if topic is None:
            raise LookupError("Learning topic '{}' does not exist".format(topic_id))

        previous_manual_status = topic.get("manual_status")
        if status == "automatic":
            topic.pop("manual_status", None)
        else:
            topic["manual_status"] = status
        active_ids = index.get("active_topic_ids", [])
        active_ids = (
            [value for value in active_ids if isinstance(value, str)]
            if isinstance(active_ids, list)
            else []
        )
        active_ids = [value for value in active_ids if value != topic_id]
        if status == "current":
            pinned_current_count = sum(
                item.get("manual_status") == "current" for item in topics
            )
            if pinned_current_count > 3:
                if previous_manual_status is None:
                    topic.pop("manual_status", None)
                else:
                    topic["manual_status"] = previous_manual_status
                raise LearningContextError("最多可固定 3 个当前方向")
            active_ids.insert(0, topic_id)
        elif status == "automatic":
            active_ids.append(topic_id)
        index["active_topic_ids"] = active_ids[:3]
        index["topics"] = topics

        from backend.app.services.learning_context_sync import LearningContextSync

        sync = LearningContextSync(self)
        memory_files = sync._read_memory_files()
        sync._ensure_active_focus(
            memory_files, self._read_sources(), index["active_topic_ids"]
        )
        updates = {
            relative: content
            for relative, content in memory_files.items()
            if content != self._read_memory(relative)
        }
        updates["index.yaml"] = yaml.safe_dump(
            index, allow_unicode=True, sort_keys=False
        )
        sync._commit_files(updates)
        return self.read_topic(topic_id)

    def _selected_source_summaries(self) -> list[dict[str, str]]:
        selected = set(self._read_sources())
        return [item for item in self.available_sources() if item["id"] in selected]

    def _match_topics(
        self, focus: str, topics: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        tokens = _tokens(focus)
        if not tokens:
            return []
        scored = []
        for topic in topics:
            values = [
                topic["id"].replace("-", " "),
                topic["title"],
                *topic["aliases"],
                *topic["keywords"],
            ]
            topic_tokens = set(_tokens(" ".join(values))) - {"learning"}
            overlap = len(tokens & topic_tokens)
            if overlap:
                scored.append((-overlap, topic["id"], topic))
        return [value[2] for value in sorted(scored)[:3]]

    def _read_sources(self) -> list[str]:
        stored = self._read_yaml("sources.yaml", {"included_document_ids": []})
        if not isinstance(stored, dict):
            raise LearningContextError("sources.yaml must contain a mapping")
        return self._normalize_ids(stored.get("included_document_ids", []), "included_document_ids")

    def _read_status(self) -> dict[str, Any]:
        status_path = self._context_path("state.json", must_exist=False)
        if not status_path.exists():
            return {"state": "not_synced", "message": "尚未同步"}
        try:
            import json

            value = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return {"state": "failed", "message": "同步状态不可读取，可重试"}
        if not isinstance(value, dict):
            return {"state": "failed", "message": "同步状态不可读取，可重试"}
        return value

    def _write_status(self, value: dict[str, Any]) -> None:
        self._atomic_write(
            "state.json",
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        )

    def _manual_entry_statuses(
        self, status: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        from backend.app.services.learning_context_sync_entries import entry_blocks

        state = status if isinstance(status, dict) else self._read_status()
        stored_legacy_files = state.get("user_managed_files", [])
        legacy_files = {
            item for item in stored_legacy_files if isinstance(item, str)
        } if isinstance(stored_legacy_files, list) else set()
        paths = ["active.md", "important.md"] + [
            "topics/{}.md".format(topic["id"]) for topic in self.list_topics()
        ]
        entries = []
        for relative in paths:
            for block in entry_blocks(self._read_memory(relative)):
                metadata = block["metadata"]
                support_state = metadata.get("support_state")
                pinned = bool(metadata.get("pinned")) or relative in legacy_files
                if not pinned and support_state not in {"needs_review", "source_removed"}:
                    continue
                entries.append(
                    {
                        "relative_path": relative,
                        "entry_id": metadata["entry_id"],
                        "title": metadata.get("title", metadata["entry_id"]),
                        "pinned": pinned,
                        "removed": False,
                        "support_state": support_state,
                    }
                )
        suppressed = state.get("suppressed_entries", [])
        if isinstance(suppressed, list):
            for item in suppressed:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("relative_path"), str)
                    or not isinstance(item.get("entry_id"), str)
                ):
                    continue
                entries.append(
                    {
                        "relative_path": item["relative_path"],
                        "entry_id": item["entry_id"],
                        "title": item.get("title") or item["entry_id"],
                        "pinned": False,
                        "removed": True,
                        "support_state": None,
                    }
                )
        return entries

    def _editable_entry_details(self) -> list[dict[str, Any]]:
        from backend.app.services.learning_context_sync_entries import entry_blocks

        paths = ["active.md", "important.md"] + [
            "topics/{}.md".format(topic["id"]) for topic in self.list_topics()
        ]
        entries = []
        for relative in paths:
            for block in entry_blocks(self._read_memory(relative)):
                metadata = block["metadata"]
                entries.append(
                    {
                        "relative_path": relative,
                        "layer": "topic" if relative.startswith("topics/") else relative[:-3],
                        "topic_id": Path(relative).stem if relative.startswith("topics/") else None,
                        "entry_id": metadata["entry_id"],
                        "title": metadata.get("title", metadata["entry_id"]),
                        "summary": metadata.get("summary", ""),
                        "pinned": bool(metadata.get("pinned")),
                        "support_state": metadata.get("support_state"),
                    }
                )
        return entries

    def _save_user_memory(self, relative: str, markdown: str) -> list[str]:
        if not isinstance(markdown, str) or len(markdown.encode("utf-8")) > _MAX_MEMORY_BYTES:
            raise LearningContextError("Markdown context must be text under 512 KB")
        if "\x00" in markdown:
            raise LearningContextError("Markdown context cannot contain NUL characters")
        from backend.app.services.learning_context_sync_entries import (
            ENTRY_END,
            entry_blocks,
            render_entry,
            visible_entry_content,
        )

        state = self._read_status()
        legacy_files = state.get("user_managed_files", [])
        pin_all = isinstance(legacy_files, list) and relative in legacy_files
        original_blocks = entry_blocks(self._read_memory(relative))
        original_by_id = {block["metadata"]["entry_id"]: block for block in original_blocks}
        edited_blocks = entry_blocks(markdown)
        edited_by_id = {block["metadata"]["entry_id"]: block for block in edited_blocks}
        replacements = []
        pinned_entry_ids = []
        removed_entries = []

        for entry_id, old_block in original_by_id.items():
            edited = edited_by_id.get(entry_id)
            if edited is None:
                removed_entries.append(
                    {
                        "relative_path": relative,
                        "entry_id": entry_id,
                        "title": old_block["metadata"].get("title", entry_id),
                    }
                )
                continue
            metadata = dict(old_block["metadata"])
            if pin_all or edited["text"] != old_block["text"] or metadata.get("pinned"):
                edited_metadata = edited["metadata"]
                title, summary, user_body = visible_entry_content(edited)
                if edited_metadata.get("title") != old_block["metadata"].get("title"):
                    title = edited_metadata.get("title")
                if edited_metadata.get("summary") != old_block["metadata"].get("summary"):
                    summary = edited_metadata.get("summary")
                    body_heading = re.match(r"^###\s+.+?(?:\n|$)", user_body)
                    user_body = (
                        (body_heading.group(0) + "\n" if body_heading else "")
                        + str(summary)
                    )
                if not isinstance(title, str) or not title.strip():
                    title = metadata.get("title", entry_id)
                if not isinstance(summary, str) or not summary.strip():
                    summary = "人工固定的学习上下文。"
                metadata["title"] = title.strip()[:200]
                metadata["summary"] = summary.strip()[:2000]
                metadata["user_body"] = user_body
                metadata["pinned"] = True
                replacements.append((edited["start"], edited["end"], render_entry(metadata)))
                pinned_entry_ids.append(entry_id)

        for block in edited_blocks:
            if block["metadata"]["entry_id"] in original_by_id:
                continue
            user_marker = block["text"].replace(
                block["text"].splitlines()[0],
                "<!-- learning-context-user-note -->",
                1,
            ).replace(ENTRY_END, "<!-- /learning-context-user-note -->", 1)
            replacements.append((block["start"], block["end"], user_marker))

        saved = markdown
        for start, end, replacement in sorted(replacements, reverse=True):
            saved = saved[:start] + replacement + saved[end:]
        self._atomic_write(relative, saved)

        suppressed = state.get("suppressed_entries", [])
        if not isinstance(suppressed, list):
            suppressed = []
        suppressed = [
            item
            for item in suppressed
            if not (
                isinstance(item, dict)
                and item.get("relative_path") == relative
                and item.get("entry_id") in edited_by_id
            )
        ]
        suppressed.extend(
            item
            for item in removed_entries
            if not any(
                isinstance(existing, dict)
                and existing.get("relative_path") == item["relative_path"]
                and existing.get("entry_id") == item["entry_id"]
                for existing in suppressed
            )
        )
        state["suppressed_entries"] = suppressed
        if isinstance(legacy_files, list):
            remaining_legacy_files = [item for item in legacy_files if item != relative]
            if remaining_legacy_files:
                state["user_managed_files"] = remaining_legacy_files
            else:
                state.pop("user_managed_files", None)
        revision = state.get("manual_revision", 0)
        state["manual_revision"] = (
            revision if isinstance(revision, int) and not isinstance(revision, bool) else 0
        ) + 1
        self._write_status(state)
        return pinned_entry_ids

    def _read_memory(self, relative: str) -> str:
        path = self._context_path(relative, must_exist=False)
        if not path.is_file() or path.stat().st_size > _MAX_MEMORY_BYTES:
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise LearningContextError("Cannot read learning context file '{}'".format(relative)) from error

    def _read_yaml(self, relative: str, default):
        path = self._context_path(relative, must_exist=False)
        if not path.is_file():
            return default
        try:
            if path.stat().st_size > _MAX_MEMORY_BYTES:
                raise LearningContextError("Learning context file is too large: {}".format(relative))
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise LearningContextError("Cannot read learning context file '{}'".format(relative)) from error

    def _write_yaml(self, relative: str, value: dict[str, Any]) -> None:
        self._atomic_write(relative, yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def _atomic_write(self, relative: str, content: str) -> None:
        path = self._context_path(relative, must_exist=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._context_path(relative, must_exist=False)
        fd, temporary = tempfile.mkstemp(prefix=".learning-context-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _context_path(self, relative: str, must_exist: bool) -> Path:
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise LearningContextError("Learning context paths must be relative")
        candidate = self.context_root / relative
        if any(part in {".", ".."} for part in Path(relative).parts):
            raise LearningContextError("Learning context path traversal is not allowed")
        storage_root = self.repository_root / "storage"
        if storage_root.is_symlink() or self.context_root.is_symlink():
            raise LearningContextError("Learning context directory cannot be a symlink")
        if candidate.exists() and candidate.is_symlink():
            raise LearningContextError("Learning context files cannot be symlinks")
        resolved_root = self.context_root.resolve(strict=False)
        resolved = candidate.resolve(strict=must_exist)
        if not resolved.is_relative_to(resolved_root):
            raise LearningContextError("Learning context path escapes its storage directory")
        return candidate

    def _safe_canonical_file(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.documents_root)
            if path.is_symlink() or not path.is_file():
                return False
            current = path.parent
            while current != self.repository_root:
                if current.is_symlink():
                    return False
                current = current.parent
            return bool(relative.parts) and self.documents_root.is_dir()
        except (OSError, RuntimeError, ValueError):
            return False

    def _normalize_ids(self, values: Iterable[str], label: str) -> list[str]:
        if not isinstance(values, (list, tuple)):
            raise LearningContextError("{} must be a list of document IDs".format(label))
        normalized = []
        seen = set()
        for value in values:
            if not isinstance(value, str) or not _TOPIC_ID.fullmatch(value):
                raise LearningContextError("{} contains an invalid document ID".format(label))
            if value not in seen:
                seen.add(value)
                normalized.append(value)
            if len(normalized) > 500:
                raise LearningContextError("{} cannot contain more than 500 IDs".format(label))
        return normalized

    def _validate_preferences(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise LearningContextError("Preferences must be a mapping")
        unknown = set(value) - set(_DEFAULT_PREFERENCES)
        if unknown:
            raise LearningContextError("Unsupported preference fields: {}".format(", ".join(sorted(unknown))))
        result = dict(_DEFAULT_PREFERENCES)
        result.update(value)
        fixed_direction = result["fixed_direction"]
        if not isinstance(fixed_direction, str) or len(fixed_direction) > 300:
            raise LearningContextError("fixed_direction must be text up to 300 characters")
        result["fixed_direction"] = " ".join(fixed_direction.split())
        for field in ("keywords", "exclude_keywords", "exploration_directions", "important_anchors"):
            if not isinstance(result[field], list):
                raise LearningContextError("{} must be a list of text".format(field))
            result[field] = self._clean_text_list(result[field], field)
        return result

    @staticmethod
    def _clean_text_list(value: Any, label: str) -> list[str]:
        if not isinstance(value, list):
            return []
        output = []
        seen = set()
        for entry in value:
            if not isinstance(entry, str):
                continue
            cleaned = " ".join(entry.split())
            key = cleaned.casefold()
            if cleaned and len(cleaned) <= 200 and key not in seen:
                output.append(cleaned)
                seen.add(key)
            if len(output) >= 100:
                break
        return output


def _tokens(value: str) -> set[str]:
    return {
        item.casefold()
        for item in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+.#-]{1,}|[\u3400-\u9fff]{2,}", value)
    }
