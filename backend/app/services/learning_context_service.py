"""File-backed learning progress context for Terms and Research recommendations."""

from __future__ import annotations

from pathlib import Path
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
_DEFAULT_PREFERENCES = {
    "fixed_direction": "",
    "keywords": [],
    "exclude_keywords": [],
    "exploration_directions": [],
    "important_anchors": [],
}


class LearningContextError(ValueError):
    """Invalid learning context input or unsafe local context path."""


class LearningContextService:
    """Own local learning context files without writing canonical knowledge."""

    def __init__(self, repository_root: Path):
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        self.documents_root = self.knowledge_root / "documents"
        self.context_root = self.repository_root / "storage" / "learning-context"

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
        available_by_id = {item["id"]: item for item in self.available_sources()}
        unknown = [item for item in ids if item not in available_by_id]
        if unknown:
            raise LearningContextError(
                "Only existing canonical learning documents can be selected: {}".format(
                    ", ".join(unknown)
                )
            )
        self._write_yaml("sources.yaml", {"included_document_ids": ids})
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

        raw_active = self._read_memory("active.md")
        raw_important = self._read_memory("important.md") if include_important else ""
        topic_reserve = max_chars // 2 if selected_topics else 0
        active = raw_active[:max_chars - topic_reserve]
        remaining = max(0, max_chars - len(active))
        important = raw_important[: min(remaining, max_chars // 4)]
        remaining = max(0, max_chars - len(active) - len(important))
        bounded_topics = []
        for topic in selected_topics:
            if remaining == 0:
                break
            body = topic["markdown"][:remaining]
            bounded_topics.append({**topic, "markdown": body})
            remaining -= len(body)
        return {
            "included_sources": self._selected_source_summaries(),
            "preferences": preferences,
            "active": active,
            "important": important,
            "topics": bounded_topics,
            "topic_index": topics,
        }

    def get_overview(self) -> dict[str, Any]:
        return {
            "sources": self.get_sources(),
            "preferences": self.get_preferences(),
            "active": self._read_memory("active.md"),
            "important": self._read_memory("important.md"),
            "topics": self.list_topics(),
            "status": self._read_status(),
        }

    def list_topics(self) -> list[dict[str, Any]]:
        index = self._read_yaml("index.yaml", {"topics": []})
        if not isinstance(index, dict) or not isinstance(index.get("topics", []), list):
            raise LearningContextError("index.yaml must contain a topics list")
        listed = []
        seen: set[str] = set()
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
            listed.append(
                {
                    "id": topic_id,
                    "title": title.strip(),
                    "aliases": self._clean_text_list(item.get("aliases", []), "aliases"),
                    "keywords": self._clean_text_list(item.get("keywords", []), "keywords"),
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
            values = [topic["title"], *topic["aliases"], *topic["keywords"]]
            topic_tokens = set(_tokens(" ".join(values)))
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
