"""Validate and deterministically re-anchor reader-only text annotations."""

from datetime import datetime, timezone
from hashlib import sha256
from typing import Optional

from backend.app.domain.runtime import PresentationAnnotation
from backend.app.repositories.annotation_repository import AnnotationRepository


_PALETTES = {
    "highlight": {"yellow", "green", "blue", "pink", "gray"},
    "text_color": {"red", "orange", "green", "blue", "purple", "muted"},
    "underline": {None},
}
_CONTEXT_UNITS = 40


class AnnotationConflictError(ValueError):
    """The annotation was based on canonical text that has changed."""


class PresentationAnnotationService:
    def __init__(self, repository: AnnotationRepository):
        self.repository = repository

    def get(self, annotation_id: str) -> PresentationAnnotation:
        return self.repository.get(annotation_id)

    def list_for_entity(
        self, entity_type: str, entity_id: str, content: str
    ) -> list[PresentationAnnotation]:
        content_hash = _content_hash(content)
        result = []
        for annotation in self.repository.list_for_entity(entity_type, entity_id):
            if annotation.base_content_hash == content_hash:
                status = (
                    "active"
                    if _utf16_slice(content, annotation.start_offset, annotation.end_offset)
                    == _utf16_bytes(annotation.selected_text)
                    else "stale"
                )
                if annotation.status != status:
                    self.repository.update_anchor(
                        annotation.id,
                        annotation.start_offset,
                        annotation.end_offset,
                        annotation.base_content_hash,
                        status,
                        _now(),
                    )
                    annotation = self.repository.get(annotation.id)
                result.append(annotation)
                continue

            anchor = _reanchor(content, annotation)
            if anchor is None:
                if annotation.status != "stale":
                    self.repository.update_anchor(
                        annotation.id,
                        annotation.start_offset,
                        annotation.end_offset,
                        annotation.base_content_hash,
                        "stale",
                        _now(),
                    )
                    annotation = self.repository.get(annotation.id)
                result.append(annotation)
                continue

            start, end = anchor
            self.repository.update_anchor(
                annotation.id,
                start,
                end,
                content_hash,
                "active",
                _now(),
            )
            result.append(self.repository.get(annotation.id))
        return result

    def create(
        self,
        *,
        entity_type: str,
        entity_id: str,
        style_type: str,
        style_value: Optional[str],
        selected_text: str,
        prefix_text: str,
        suffix_text: str,
        start_offset: int,
        end_offset: int,
        base_content_hash: str,
        content: str,
    ) -> PresentationAnnotation:
        _validate_style(style_type, style_value)
        if entity_type not in {"document", "term"}:
            raise ValueError("Only document and term annotations are supported")
        if not selected_text or start_offset < 0 or end_offset <= start_offset:
            raise ValueError("Annotation selection must be a non-empty valid range")
        if _utf16_slice(content, start_offset, end_offset) != _utf16_bytes(selected_text):
            raise ValueError("selected_text does not match the canonical Markdown range")
        current_hash = _content_hash(content)
        if base_content_hash != current_hash:
            raise AnnotationConflictError("Canonical content changed; reload before annotating")
        actual_prefix = _utf16_slice(
            content, max(0, start_offset - _CONTEXT_UNITS), start_offset
        ).decode("utf-16-le", errors="ignore")
        actual_suffix = _utf16_slice(
            content,
            end_offset,
            min(_utf16_length(content), end_offset + _CONTEXT_UNITS),
        ).decode("utf-16-le", errors="ignore")
        # Context comes from the canonical body so later re-anchoring is deterministic.
        now = _now()
        return self.repository.upsert(
            PresentationAnnotation(
                id="",
                entity_type=entity_type,
                entity_id=entity_id,
                style_type=style_type,
                style_value=style_value,
                selected_text=selected_text,
                prefix_text=actual_prefix,
                suffix_text=actual_suffix,
                start_offset=start_offset,
                end_offset=end_offset,
                base_content_hash=current_hash,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

    def update_style(
        self,
        annotation_id: str,
        style_type: str,
        style_value: Optional[str],
        content: str,
    ) -> PresentationAnnotation:
        _validate_style(style_type, style_value)
        annotation = self.repository.get(annotation_id)
        refreshed = self.list_for_entity(annotation.entity_type, annotation.entity_id, content)
        annotation = next(item for item in refreshed if item.id == annotation_id)
        if annotation.status != "active":
            raise AnnotationConflictError("Stale annotation cannot be restyled until its text is selected again")
        return self.repository.update_style(annotation_id, style_type, style_value, _now())

    def delete(self, annotation_id: str) -> None:
        self.repository.delete(annotation_id)

    def list_stale(self, entities: list[tuple[str, str, str]]) -> list[PresentationAnnotation]:
        for entity_type, entity_id, content in entities:
            self.list_for_entity(entity_type, entity_id, content)
        return self.repository.list_stale()


def _validate_style(style_type: str, style_value: Optional[str]) -> None:
    if style_type not in _PALETTES or style_value not in _PALETTES[style_type]:
        raise ValueError("style_type/style_value must use a supported Presentation Annotation palette")


def _reanchor(content: str, annotation: PresentationAnnotation) -> Optional[tuple[int, int]]:
    source = _utf16_bytes(content)
    selected = _utf16_bytes(annotation.selected_text)
    if not selected:
        return None
    candidates = []
    cursor = 0
    while True:
        found = source.find(selected, cursor)
        if found < 0:
            break
        candidates.append(found // 2)
        cursor = found + 2
    if len(candidates) == 1:
        start = candidates[0]
        return start, start + _utf16_length(annotation.selected_text)
    if not candidates:
        return None

    prefix = _utf16_bytes(annotation.prefix_text)
    suffix = _utf16_bytes(annotation.suffix_text)
    selected_units = _utf16_length(annotation.selected_text)
    scores = []
    for start in candidates:
        start_byte = start * 2
        end_byte = start_byte + len(selected)
        prefix_matches = bool(prefix) and source[max(0, start_byte - len(prefix)):start_byte] == prefix
        suffix_matches = bool(suffix) and source[end_byte:end_byte + len(suffix)] == suffix
        scores.append((int(prefix_matches) + int(suffix_matches), start))
    highest = max(score for score, _ in scores)
    winners = [start for score, start in scores if score == highest]
    if highest == 0 or len(winners) != 1:
        return None
    return winners[0], winners[0] + selected_units


def _content_hash(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _utf16_bytes(value: str) -> bytes:
    return value.encode("utf-16-le", errors="surrogatepass")


def _utf16_length(value: str) -> int:
    return len(_utf16_bytes(value)) // 2


def _utf16_slice(value: str, start: int, end: int) -> bytes:
    encoded = _utf16_bytes(value)
    return encoded[max(0, start) * 2:max(0, end) * 2]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
