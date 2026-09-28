"""Create and autosave Runtime Drafts without touching Canonical files."""

from datetime import datetime, timezone
import uuid

from backend.app.domain.runtime import Draft, EntityType
from backend.app.repositories.draft_repository import DraftNotFoundError, DraftRepository


_ENTITY_TYPES = {"document", "term", "source", "taxonomy"}


class DraftService:
    def __init__(self, repository: DraftRepository):
        self.repository = repository

    def create(
        self,
        entity_type: EntityType,
        entity_id: str,
        content: str,
        base_git_revision: str,
        base_content_hash: str,
    ) -> Draft:
        if entity_type not in _ENTITY_TYPES:
            raise ValueError("Unsupported Draft entity type: {}".format(entity_type))
        _require_text(entity_id, "entity_id")
        _require_text(base_git_revision, "base_git_revision")
        _require_text(base_content_hash, "base_content_hash")
        if not isinstance(content, str):
            raise ValueError("Draft content must be text")

        now = _utc_now()
        draft = Draft(
            id=uuid.uuid4().hex,
            entity_type=entity_type,
            entity_id=entity_id,
            base_git_revision=base_git_revision,
            base_content_hash=base_content_hash,
            content=content,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        return self.repository.create(draft)

    def get(self, draft_id: str) -> Draft:
        draft = self.repository.get(draft_id)
        if draft is None:
            raise DraftNotFoundError("Draft '{}' does not exist".format(draft_id))
        return draft

    def save(self, draft_id: str, content: str, expected_revision: int) -> Draft:
        if not isinstance(content, str):
            raise ValueError("Draft content must be text")
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        return self.repository.save_content(
            draft_id, content, expected_revision, _utc_now()
        )


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be non-empty text".format(field))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
