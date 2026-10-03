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

from backend.app.domain.collection import Collection, EntityNode, SectionNode
from backend.app.domain.research_runtime import ResearchCandidateRecord, ResearchWorkRecord
from backend.app.domain.runtime import Draft
from backend.app.domain.source import SourceMetadata
from backend.app.repositories.research_candidate_repository import ResearchCandidateRepository
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.collection_registry import CollectionRegistry
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager
from backend.app.services.source_registry import SourceRegistry


@dataclass(frozen=True)
class ResearchSourceSaveResult:
    action: Literal["linked_existing", "draft_created", "draft_reused"]
    source_id: str
    draft_id: Optional[str]
    candidate: ResearchCandidateRecord


@dataclass(frozen=True)
class ResearchNoteCreateResult:
    group_id: str
    source_draft_id: Optional[str]
    document_draft_id: str
    collection_draft_id: Optional[str]
    collection_id: Optional[str]
    document_id: str
    source_id: Optional[str]


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
            self._link_existing_source(candidate.id, work.id, linked_source)
            updated = self.candidate_repository.get(candidate.id)
            return ResearchSourceSaveResult("linked_existing", linked_source, None, updated or candidate)

        source = self._find_canonical_source(work)
        if source is not None:
            self._link_existing_source(candidate.id, work.id, source.id)
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

    def create_note(
        self,
        candidate_id: str,
        document_type: Literal["paper-note", "learning-note"],
        template: Literal["structured", "blank"],
        collection_id: Optional[str] = None,
        section_id: Optional[str] = None,
    ) -> ResearchNoteCreateResult:
        candidate = self.candidate_repository.get(candidate_id)
        if candidate is None:
            raise LookupError("Research Candidate '{}' does not exist".format(candidate_id))
        work = self.work_repository.get_work(candidate.work_id)
        if work is None:
            raise LookupError("Research Work '{}' does not exist".format(candidate.work_id))
        if section_id is not None and collection_id is None:
            raise ValueError("section_id requires collection_id")

        existing_note = self.work_repository.get_pending_link_for_candidate(candidate.id, "note")
        if existing_note is not None:
            return self._existing_note_group(candidate.id, existing_note)

        group_id = uuid.uuid4().hex
        source_id: Optional[str] = None
        source_draft: Optional[Draft] = None
        source_created = False
        document_draft: Optional[Draft] = None
        document_created = False
        collection_draft: Optional[Draft] = None
        collection_created = False
        prior_collection_content: Optional[str] = None
        prior_collection_revision: Optional[int] = None

        try:
            linked_source = next(
                (
                    link["entity_id"]
                    for link in self.work_repository.list_entity_links(work.id)
                    if link["entity_type"] == "source" and link["relation_type"] == "source"
                ),
                None,
            )
            source = self._find_canonical_source(work) if linked_source is None else None
            source_id = linked_source or (source.id if source is not None else None)
            pending_source = self.work_repository.get_pending_link_for_work(work.id, "source")
            if pending_source is not None:
                source_draft = self._get_or_clear_pending_draft(pending_source)
                if source_draft is not None:
                    source_id = pending_source["intended_entity_id"]
                    group_id = pending_source["group_id"]
            if source_draft is None and source_id is None:
                source_draft, source_id, source_created = self._create_or_get_source_draft(work)

            document_id, document_content = self._create_note_content(
                work, candidate.id, document_type, template, source_id
            )
            document_draft, document_created = self._create_document_draft(
                document_id, document_content
            )

            if collection_id is not None:
                collection_draft, collection_created, prior_collection_content, prior_collection_revision = (
                    self._add_document_to_collection(
                        collection_id, section_id, document_id
                    )
                )

            now = self._now().isoformat()
            with self.work_repository.write_transaction():
                if source_id is not None:
                    self.work_repository.add_pending_link(
                        group_id=group_id,
                        candidate_id=candidate.id,
                        work_id=work.id,
                        draft_id=source_draft.id if source_draft is not None else document_draft.id,
                        intended_entity_type="source",
                        intended_entity_id=source_id,
                        relation_type="source",
                        created_at=now,
                    )
                note_link = self.work_repository.add_pending_link(
                    group_id=group_id,
                    candidate_id=candidate.id,
                    work_id=work.id,
                    draft_id=document_draft.id,
                    intended_entity_type="document",
                    intended_entity_id=document_id,
                    relation_type="note",
                    created_at=now,
                )
                if collection_draft is not None:
                    self.work_repository.add_pending_link(
                        group_id=note_link["group_id"],
                        candidate_id=candidate.id,
                        work_id=work.id,
                        draft_id=collection_draft.id,
                        intended_entity_type="collection",
                        intended_entity_id=collection_id,
                        relation_type="collection",
                        created_at=now,
                    )

            return ResearchNoteCreateResult(
                group_id=note_link["group_id"],
                source_draft_id=source_draft.id if source_draft is not None else None,
                document_draft_id=document_draft.id,
                collection_draft_id=collection_draft.id if collection_draft is not None else None,
                collection_id=collection_id if collection_draft is not None else None,
                document_id=document_id,
                source_id=source_id,
            )
        except Exception:
            if collection_draft is not None and collection_created:
                self._discard_created_draft(collection_draft)
            elif (
                collection_draft is not None
                and prior_collection_content is not None
                and prior_collection_revision is not None
            ):
                try:
                    self.draft_service.save(
                        collection_draft.id,
                        prior_collection_content,
                        collection_draft.revision,
                    )
                except Exception:
                    pass
            if document_draft is not None and document_created:
                self._discard_created_draft(document_draft)
            if source_draft is not None and source_created:
                self._discard_created_draft(source_draft)
            raise

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
            status_by_candidate: dict[str, str] = {}
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
                    candidate_id = link["candidate_id"]
                    prior_status = status_by_candidate.get(candidate_id)
                    if next_status == "note_created" or prior_status is None:
                        status_by_candidate[candidate_id] = next_status
            for candidate_id, status in status_by_candidate.items():
                self.candidate_repository.mark_candidate_converted(
                    candidate_id, status, now
                )
            self.work_repository.delete_pending_links_for_drafts(draft_ids)

    def _link_existing_source(
        self, candidate_id: str, work_id: str, source_id: str
    ) -> None:
        now = self._now().isoformat()
        with self.work_repository.write_transaction():
            self.work_repository.add_entity_link(
                work_id=work_id,
                entity_type="source",
                entity_id=source_id,
                relation_type="source",
                created_at=now,
            )
            self.candidate_repository.mark_candidate_converted(
                candidate_id, "saved_source", now
            )

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

    def _existing_note_group(
        self, candidate_id: str, note_link: dict
    ) -> ResearchNoteCreateResult:
        try:
            document_draft = self.draft_service.get(note_link["draft_id"])
        except LookupError:
            self.cancel_pending_for_draft(note_link["draft_id"])
            raise ValueError("Pending Research Note Draft no longer exists")
        if document_draft.entity_type != "document":
            raise ValueError("Research note link does not reference a Document Draft")
        links = self.work_repository.list_pending_links(candidate_id)
        group_links = [link for link in links if link["group_id"] == note_link["group_id"]]
        source_link = next((link for link in group_links if link["relation_type"] == "source"), None)
        collection_link = next((link for link in group_links if link["relation_type"] == "collection"), None)
        source_draft_id = None
        source_id = None
        if source_link is not None:
            source_id = source_link["intended_entity_id"]
            try:
                source_draft = self.draft_service.get(source_link["draft_id"])
                if source_draft.entity_type == "source":
                    source_draft_id = source_draft.id
            except LookupError:
                pass
        return ResearchNoteCreateResult(
            group_id=note_link["group_id"],
            source_draft_id=source_draft_id,
            document_draft_id=document_draft.id,
            collection_draft_id=collection_link["draft_id"] if collection_link else None,
            collection_id=collection_link["intended_entity_id"] if collection_link else None,
            document_id=document_draft.entity_id,
            source_id=source_id,
        )

    def _create_document_draft(self, document_id: str, content: str) -> tuple[Draft, bool]:
        target = self.canonical_target_resolver.resolve_target("document", document_id, content)
        if target.path.exists():
            raise ValueError("Canonical Document '{}' already exists".format(document_id))
        acquired = self.draft_service.create_or_get(
            "document",
            document_id,
            content,
            self.git.current_revision(),
            self.git.content_hash(target.path),
        )
        if acquired.draft.content != content:
            raise ValueError("A different Document Draft already uses '{}'".format(document_id))
        return acquired.draft, acquired.created

    def _create_note_content(
        self,
        work: ResearchWorkRecord,
        candidate_id: str,
        document_type: Literal["paper-note", "learning-note"],
        template: Literal["structured", "blank"],
        source_id: Optional[str],
    ) -> tuple[str, str]:
        base = _slugify(work.title) or "research-note"
        identity = _slugify(candidate_id) or "candidate"
        candidates = ["{}-{}".format(base, identity)]
        if work.year is not None:
            candidates.insert(0, "{}-{}-{}".format(base, work.year, identity))
        index = 2
        while True:
            for document_id in candidates:
                content = _research_note_content(work.title, document_id, document_type, template, source_id)
                target = self.canonical_target_resolver.resolve_target("document", document_id, content)
                if target.path.exists() or self.draft_service.list_for_target("document", document_id):
                    continue
                return document_id, content
            candidates = ["{}-{}-{}".format(base, identity, index)]
            index += 1

    def _add_document_to_collection(
        self, collection_id: str, section_id: Optional[str], document_id: str
    ) -> tuple[Draft, bool, Optional[str], Optional[int]]:
        collection = CollectionRegistry.load(self.repository_root / "knowledge" / "collections").get(collection_id)
        if collection is None:
            raise LookupError("Collection '{}' does not exist".format(collection_id))
        if collection.status != "active":
            raise ValueError("Cannot add a Research Note to an archived Collection")

        current_drafts = self.draft_service.list_for_target("collection", collection_id)
        collection_draft = current_drafts[0] if current_drafts else None
        current_content = collection_draft.content if collection_draft is not None else yaml.safe_dump(
            collection.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False
        )
        current = Collection.model_validate(yaml.safe_load(current_content))
        if current.status != "active":
            raise ValueError("Cannot add a Research Note to an archived Collection Draft")
        if section_id is not None and not any(
            isinstance(node, SectionNode) and node.id == section_id
            for node in _all_collection_nodes(current.nodes)
        ):
            raise ValueError("Section '{}' does not exist in Collection '{}'".format(section_id, collection_id))

        if not any(
            isinstance(node, EntityNode) and node.entity_type == "document" and node.entity_id == document_id
            for node in _all_collection_nodes(current.nodes)
        ):
            node_id = _collection_node_id(current, document_id)
            document_node = EntityNode(id=node_id, kind="entity", entity_type="document", entity_id=document_id)
            if section_id is None:
                current.nodes.append(document_node)
            elif not _append_to_section(current.nodes, section_id, document_node):
                raise ValueError("Section '{}' is not available".format(section_id))

        content = yaml.safe_dump(
            current.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False
        )
        target = self.canonical_target_resolver.resolve_target("collection", collection_id, content)
        if collection_draft is None:
            acquired = self.draft_service.create_or_get(
                "collection",
                collection_id,
                content,
                self.git.current_revision(),
                self.git.content_hash(target.path),
            )
            return acquired.draft, acquired.created, None, None
        if content == collection_draft.content:
            return collection_draft, False, None, None
        updated = self.draft_service.save(
            collection_draft.id, content, collection_draft.revision
        )
        return updated, False, collection_draft.content, collection_draft.revision

    def _discard_created_draft(self, draft: Draft) -> None:
        try:
            self.cancel_pending_for_draft(draft.id)
            self.draft_service.discard(draft.id, draft.revision)
        except LookupError:
            pass

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


def _research_note_content(
    title: str,
    document_id: str,
    document_type: Literal["paper-note", "learning-note"],
    template: Literal["structured", "blank"],
    source_id: Optional[str],
) -> str:
    title = " ".join(title.split())
    metadata = {
        "schema_version": 1,
        "id": document_id,
        "title": title,
        "type": document_type,
        "domains": [],
        "topics": [],
        "tags": [],
        "sources": [source_id] if source_id else [],
        "review": {"human": {"status": "unreviewed"}},
        "maintenance": {"status": "current"},
        "provenance": {"origin": "human-authored", "ai_assisted": False},
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    headings = {
        "paper-note": (
            "一、基本信息",
            "二、问题与动机",
            "三、方法",
            "四、实验设计",
            "五、实验结果",
            "六、与已有知识的关系",
            "七、我的理解与问题",
        ),
        "learning-note": (
            "一、前置知识",
            "二、核心概念",
            "三、数学与公式",
            "四、方法逻辑",
            "五、与已有知识的关系",
            "六、我的疑问",
        ),
    }
    body = "# {}\n".format(title)
    if template == "structured":
        body += "\n" + "\n\n".join("## {}".format(heading) for heading in headings[document_type]) + "\n"
    else:
        body += "\n"
    return "---\n{}\n---\n{}".format(frontmatter, body)


def _all_collection_nodes(nodes):
    for node in nodes:
        yield node
        if isinstance(node, SectionNode):
            yield from _all_collection_nodes(node.children)


def _append_to_section(nodes, section_id: str, child: EntityNode) -> bool:
    for node in nodes:
        if not isinstance(node, SectionNode):
            continue
        if node.id == section_id:
            node.children.append(child)
            return True
        if _append_to_section(node.children, section_id, child):
            return True
    return False


def _collection_node_id(collection: Collection, document_id: str) -> str:
    used = {node.id for node in _all_collection_nodes(collection.nodes)}
    base = "{}-note".format(document_id)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = "{}-{}".format(base, suffix)
        suffix += 1
    return candidate


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
