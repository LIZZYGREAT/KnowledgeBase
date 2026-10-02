"""Create and autosave Runtime Drafts without touching Canonical files."""

from datetime import datetime, timezone
import uuid

from backend.app.domain.runtime import Draft, DraftEntityType
from backend.app.repositories.draft_repository import DraftNotFoundError, DraftRepository


_DRAFT_ENTITY_TYPES = {"document", "term", "source", "taxonomy", "collection"}


class DraftService:
    def __init__(self, repository: DraftRepository):
        self.repository = repository

    def create(
        self,
        entity_type: DraftEntityType,
        entity_id: str,
        content: str,
        base_git_revision: str,
        base_content_hash: str,
    ) -> Draft:
        return self.repository.create(
            self._new_draft(
                entity_type, entity_id, content, base_git_revision, base_content_hash
            )
        )

    def create_or_get(
        self,
        entity_type: DraftEntityType,
        entity_id: str,
        content: str,
        base_git_revision: str,
        base_content_hash: str,
    ) -> Draft:
        return self.repository.create_or_get(
            self._new_draft(
                entity_type, entity_id, content, base_git_revision, base_content_hash
            )
        )

    @staticmethod
    def _new_draft(
        entity_type: DraftEntityType,
        entity_id: str,
        content: str,
        base_git_revision: str,
        base_content_hash: str,
    ) -> Draft:
        if entity_type not in _DRAFT_ENTITY_TYPES:
            raise ValueError("Unsupported Draft entity type: {}".format(entity_type))
        _require_text(entity_id, "entity_id")
        _require_text(base_git_revision, "base_git_revision")
        _require_text(base_content_hash, "base_content_hash")
        if not isinstance(content, str):
            raise ValueError("Draft content must be text")

        now = _utc_now()
        return Draft(
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

    def get(self, draft_id: str) -> Draft:
        draft = self.repository.get(draft_id)
        if draft is None:
            raise DraftNotFoundError("Draft '{}' does not exist".format(draft_id))
        return draft

    def list_for_target(self, entity_type: str, entity_id: str) -> list[Draft]:
        if entity_type not in _DRAFT_ENTITY_TYPES:
            raise ValueError("Unsupported Draft entity type: {}".format(entity_type))
        _require_text(entity_id, "entity_id")
        return self.repository.list_for_target(entity_type, entity_id)

    def save(self, draft_id: str, content: str, expected_revision: int) -> Draft:
        if not isinstance(content, str):
            raise ValueError("Draft content must be text")
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        return self.repository.save_content(
            draft_id, content, expected_revision, _utc_now()
        )

    def rebase(
        self,
        draft_id: str,
        content: str,
        expected_revision: int,
        base_git_revision: str,
        base_content_hash: str,
    ) -> Draft:
        if not isinstance(content, str):
            raise ValueError("Draft content must be text")
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        _require_text(base_git_revision, "base_git_revision")
        _require_text(base_content_hash, "base_content_hash")
        return self.repository.rebase(
            draft_id,
            content,
            expected_revision,
            base_git_revision,
            base_content_hash,
            _utc_now(),
        )

    def discard(self, draft_id: str, expected_revision: int) -> None:
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        self.repository.delete(draft_id, expected_revision)


def _require_text(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("{} must be non-empty text".format(field))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
