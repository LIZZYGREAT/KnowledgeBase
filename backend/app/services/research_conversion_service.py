"""Publisher-backed conversion of Research Works into canonical Source Drafts."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
from typing import Callable, Literal, Optional, Sequence
import uuid

import yaml
from pydantic import ValidationError

from backend.app.domain.research_runtime import ResearchCandidateRecord, ResearchWorkRecord
from backend.app.domain.runtime import Draft
from backend.app.domain.source import SourceMetadata
from backend.app.repositories.research_candidate_repository import ResearchCandidateRepository
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager
from backend.app.services.source_registry import SourceRegistry


@dataclass(frozen=True)
class ResearchSourceSaveResult:
    action: Literal["linked_existing", "draft_created", "draft_reused"]
    source_id: str
    draft_id: Optional[str]
    candidate: ResearchCandidateRecord


class ResearchConversionService:
    def __init__(
        self,
        repository_root: Path,
        connection: sqlite3.Connection,
        draft_service: DraftService,
        git_manager: GitManager,
        canonical_target_resolver: CanonicalTargetResolver,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.repository_root = Path(repository_root).expanduser().resolve()
        self.sources_root = self.repository_root / "knowledge" / "sources"
        self.connection = connection
        self.work_repository = ResearchRepository(connection)
        self.candidate_repository = ResearchCandidateRepository(connection)
        self.draft_service = draft_service
        self.git = git_manager
        self.canonical_target_resolver = canonical_target_resolver
        self.clock = clock

    def save_source(self, candidate_id: str) -> ResearchSourceSaveResult:
        candidate = self.candidate_repository.get(candidate_id)
        if candidate is None:
            raise LookupError("Research Candidate '{}' does not exist".format(candidate_id))
        work = self.work_repository.get_work(candidate.work_id)
        if work is None:
            raise LookupError("Research Work '{}' does not exist".format(candidate.work_id))

        pending = self.work_repository.get_pending_link_for_candidate(candidate.id, "source")
        if pending is not None:
            draft = self._get_or_clear_pending_draft(pending)
            if draft is not None:
                return ResearchSourceSaveResult(
                    "draft_reused", pending["intended_entity_id"], draft.id, candidate
                )

        linked_source = next(
            (
                link["entity_id"]
                for link in self.work_repository.list_entity_links(work.id)
                if link["entity_type"] == "source" and link["relation_type"] == "source"
            ),
            None,
        )
        if linked_source is not None:
            self._link_existing_source(work.id, linked_source)
            updated = self.candidate_repository.get(candidate.id)
            return ResearchSourceSaveResult("linked_existing", linked_source, None, updated or candidate)

        source = self._find_canonical_source(work)
        if source is not None:
            self._link_existing_source(work.id, source.id)
            updated = self.candidate_repository.get(candidate.id)
            return ResearchSourceSaveResult("linked_existing", source.id, None, updated or candidate)

        pending_for_work = self.work_repository.get_pending_link_for_work(work.id, "source")
        if pending_for_work is not None:
            draft = self._get_or_clear_pending_draft(pending_for_work)
            if draft is not None:
                return ResearchSourceSaveResult(
                    "draft_reused", pending_for_work["intended_entity_id"], draft.id, candidate
                )

        draft, source_id, created = self._create_or_get_source_draft(work)
        now = self._now().isoformat()
        existing_pending = None
        with self.work_repository.write_transaction():
            existing = self.work_repository.get_pending_link_for_work(work.id, "source")
            if existing is None:
                self.work_repository.add_pending_link(
                    group_id=uuid.uuid4().hex,
                    candidate_id=candidate.id,
                    work_id=work.id,
                    draft_id=draft.id,
                    intended_entity_type="source",
                    intended_entity_id=source_id,
                    relation_type="source",
                    created_at=now,
                )
                action: Literal["draft_created", "draft_reused"] = (
                    "draft_created" if created else "draft_reused"
                )
            else:
                existing_pending = existing

        if existing_pending is not None:
            existing_draft = self._get_or_clear_pending_draft(existing_pending)
            if existing_draft is None:
                return self.save_source(candidate.id)
            draft = existing_draft
            source_id = existing_pending["intended_entity_id"]
            action = "draft_reused"

        return ResearchSourceSaveResult(action, source_id, draft.id, candidate)

    def cancel_pending_for_draft(self, draft_id: str) -> int:
        with self.work_repository.write_transaction():
            return self.work_repository.delete_pending_links_for_drafts((draft_id,))

    def finalize_published_drafts(self, drafts: Sequence[Draft]) -> None:
        draft_ids = tuple(dict.fromkeys(draft.id for draft in drafts))
        if not draft_ids:
            return
        now = self._now().isoformat()
        with self.work_repository.write_transaction():
            pending = self.work_repository.pending_links_for_drafts(draft_ids)
            status_by_work: dict[str, str] = {}
            for link in pending:
                entity_type = link["intended_entity_type"]
                entity_id = link["intended_entity_id"]
                relation = link["relation_type"]
                if (entity_type, relation) in {("source", "source"), ("document", "note")}:
                    self.work_repository.add_entity_link(
                        work_id=link["work_id"],
                        entity_type=entity_type,
                        entity_id=entity_id,
                        relation_type=relation,
                        created_at=now,
                    )
                    next_status = "note_created" if relation == "note" else "saved_source"
                    prior_status = status_by_work.get(link["work_id"])
                    if next_status == "note_created" or prior_status is None:
                        status_by_work[link["work_id"]] = next_status
            for work_id, status in status_by_work.items():
                self.candidate_repository.mark_work_converted(work_id, status, now)
            self.work_repository.delete_pending_links_for_drafts(draft_ids)

    def _link_existing_source(self, work_id: str, source_id: str) -> None:
        now = self._now().isoformat()
        with self.work_repository.write_transaction():
            self.work_repository.add_entity_link(
                work_id=work_id,
                entity_type="source",
                entity_id=source_id,
                relation_type="source",
                created_at=now,
            )
            self.candidate_repository.mark_work_converted(work_id, "saved_source", now)

    def _find_canonical_source(self, work: ResearchWorkRecord) -> Optional[SourceMetadata]:
        sources = SourceRegistry.load(self.sources_root).sources
        for field in ("doi", "arxiv_id", "openalex_id"):
            work_identifier = getattr(work, field)
            normalized = _normalize_identifier(field, work_identifier)
            if normalized is None:
                continue
            for source in sources:
                source_identifier = _normalize_identifier(
                    field, getattr(source.identifiers, field)
                )
                if source_identifier == normalized:
                    return source

        if work.year is None or not work.authors:
            return None
        title = _normalize_title(work.title)
        author = _normalize_author(work.authors[0])
        if not title or not author:
            return None
        for source in sources:
            if (
                source.year == work.year
                and _normalize_title(source.title) == title
                and source.authors
                and _normalize_author(source.authors[0]) == author
            ):
                return source
        return None

    def _create_or_get_source_draft(self, work: ResearchWorkRecord) -> tuple[Draft, str, bool]:
        for source_id in _source_id_candidates(work):
            canonical_path = self.sources_root / "{}.yaml".format(source_id)
            if canonical_path.exists():
                continue
            current_drafts = self.draft_service.list_for_target("source", source_id)
            if current_drafts:
                reusable = next(
                    (draft for draft in current_drafts if _draft_matches_work(draft.content, work)),
                    None,
                )
                if reusable is not None:
                    return reusable, source_id, False
                continue

            content = _source_content(work, source_id)
            target = self.canonical_target_resolver.resolve_target("source", source_id, content)
            acquisition = self.draft_service.create_or_get(
                "source",
                source_id,
                content,
                self.git.current_revision(),
                self.git.content_hash(target.path),
            )
            if acquisition.draft.content != content:
                if _draft_matches_work(acquisition.draft.content, work):
                    return acquisition.draft, source_id, False
                continue
            return acquisition.draft, source_id, acquisition.created
        raise RuntimeError("Could not allocate a unique canonical Source id for this Work")

    def _get_or_clear_pending_draft(self, pending: dict) -> Optional[Draft]:
        try:
            draft = self.draft_service.get(pending["draft_id"])
        except LookupError:
            self.cancel_pending_for_draft(pending["draft_id"])
            return None
        if draft.entity_type != "source" or draft.entity_id != pending["intended_entity_id"]:
            raise ValueError("Research pending link does not match its Source Draft")
        return draft

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Research conversion clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


def _source_content(work: ResearchWorkRecord, source_id: str) -> str:
    identifiers = {
        "doi": work.doi,
        "arxiv_id": work.arxiv_id,
        "openalex_id": work.openalex_id,
    }
    value = {
        "schema_version": 1,
        "id": source_id,
        "type": "paper",
        "title": work.title,
        "authors": list(work.authors),
        "identifiers": identifiers,
        "metadata_review": {"status": "unreviewed"},
    }
    if work.year is not None and 1000 <= work.year <= 9999:
        value["year"] = work.year
    if work.url and work.url.startswith(("http://", "https://")):
        value["url"] = work.url
    source = SourceMetadata.model_validate(value)
    return yaml.safe_dump(
        source.model_dump(mode="json", exclude_none=True),
        allow_unicode=True,
        sort_keys=False,
    )


def _draft_matches_work(content: str, work: ResearchWorkRecord) -> bool:
    try:
        metadata = SourceMetadata.model_validate(yaml.safe_load(content))
    except (ValidationError, yaml.YAMLError, TypeError):
        return False
    for field in ("doi", "arxiv_id", "openalex_id"):
        work_identifier = _normalize_identifier(field, getattr(work, field))
        if work_identifier and work_identifier == _normalize_identifier(field, getattr(metadata.identifiers, field)):
            return True
    return bool(
        work.year is not None
        and metadata.year == work.year
        and work.authors
        and metadata.authors
        and _normalize_title(metadata.title) == _normalize_title(work.title)
        and _normalize_author(metadata.authors[0]) == _normalize_author(work.authors[0])
    )


def _source_id_candidates(work: ResearchWorkRecord):
    base = _slugify(work.title)
    if not base:
        stable = " ".join((work.normalized_title, str(work.year or ""), work.authors[0] if work.authors else ""))
        base = "research-work-{}".format(hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12])
    roots = [base]
    if work.year is not None:
        roots.append("{}-{}".format(base, work.year))
    if work.authors and work.year is not None:
        author = _slugify(work.authors[0].split()[-1]) or "paper"
        roots.append("{}-{}-{}".format(base, author, work.year))
    seen = set()
    for root in roots:
        if root not in seen:
            seen.add(root)
            yield root
    counter = 2
    while True:
        yield "{}-{}".format(base, counter)
        counter += 1


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _normalize_identifier(field: str, value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().casefold()
    if field == "doi":
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                break
    elif field == "arxiv_id":
        for prefix in ("https://arxiv.org/abs/", "http://arxiv.org/abs/", "arxiv:"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                break
    elif field == "openalex_id":
        normalized = normalized.rstrip("/").rsplit("/", 1)[-1]
    return normalized or None


def _normalize_title(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


def _normalize_author(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))
