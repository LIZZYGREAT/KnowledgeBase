"""Conservative study anchors and annual exploration of approved knowledge."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Optional

from backend.app.domain.document import DocumentMetadata
from backend.app.domain.term import TermMetadata
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.research_watermark import ResearchSearchPlan, ResearchSearchSlice
from backend.app.services.collection_registry import CollectionRegistry


@dataclass(frozen=True)
class ResearchHistoryContext:
    anchor_year: Optional[int]
    approved_ids: tuple[str, ...]
    selected_note_ids: tuple[str, ...] = ()


def research_history_context(root, profile, sources, selected_note_ids=()):
    years = []
    pinned_documents = set(profile.context.documents)
    pinned_terms = set()
    approved_ids = set()
    collections = CollectionRegistry.load(root / "knowledge" / "collections")
    for collection_id in profile.context.collections:
        collection = collections.get(collection_id)
        nodes = list(collection.nodes) if collection else []
        while nodes:
            node = nodes.pop()
            if node.kind == "section":
                nodes.extend(node.children)
            elif node.entity_type == "document":
                pinned_documents.add(node.entity_id)
            elif node.entity_type == "term":
                pinned_terms.add(node.entity_id)
    phrases = [profile.title, *[q for lens in profile.lenses if lens.enabled for q in lens.queries]]
    for path in (root / "knowledge" / "documents").rglob("*.md"):
        if path.is_symlink():
            continue
        content = path.read_text(encoding="utf-8")
        parsed = parse_markdown(content)
        metadata = DocumentMetadata.model_validate(parsed.frontmatter)
        if not metadata.review or not metadata.review.human or metadata.review.human.status != "approved":
            continue
        body = _body(content, parsed)
        if not _has_content(body) or not (
            metadata.id in pinned_documents
            or _matches(metadata.title + "\n" + body, phrases)
        ):
            continue
        approved_ids.add("document:" + metadata.id)
        pinned_terms.update(link.target for link in parsed.wiki_links)
        for source_id in metadata.sources:
            source = sources.get(source_id)
            if source is not None and source.year is not None:
                years.append(source.year)
    for path in (root / "knowledge" / "terms").rglob("*.md"):
        if path.is_symlink():
            continue
        content = path.read_text(encoding="utf-8")
        parsed = parse_markdown(content)
        metadata = TermMetadata.model_validate(parsed.frontmatter)
        body = _body(content, parsed)
        if (metadata.review and metadata.review.human and metadata.review.human.status == "approved"
                and _has_content(body)
                and (metadata.id in pinned_terms or _matches(metadata.title + "\n" + body, phrases))):
            approved_ids.add("term:" + metadata.id)
    selected_ids, selected_note_years = _selected_note_history_evidence(
        root, sources, selected_note_ids
    )
    # The explicit study stage wins. A selected note can independently seed the
    # historical query window, but does not enter the formal approval scope.
    anchor = profile.search.history_seed_year
    if anchor is None and (years or selected_note_years):
        anchor = min(years + selected_note_years)
    return ResearchHistoryContext(
        anchor,
        tuple(sorted(approved_ids)),
        tuple(sorted(selected_ids)),
    )


def _selected_note_history_evidence(root, sources, selected_note_ids):
    documents_root = root / "knowledge" / "documents"
    selected_ids = set()
    years = []
    for document_id in selected_note_ids:
        if not isinstance(document_id, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", document_id
        ):
            continue
        path = next(
            (
                documents_root / directory / (document_id + ".md")
                for directory in ("papers", "learning", "courses")
                if (documents_root / directory / (document_id + ".md")).is_file()
            ),
            None,
        )
        if path is None or path.is_symlink():
            continue
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(documents_root.resolve(strict=True)):
                continue
            content = path.read_text(encoding="utf-8")
            parsed = parse_markdown(content)
            metadata = DocumentMetadata.model_validate(parsed.frontmatter)
            if metadata.id != document_id or metadata.type not in {
                "paper-note",
                "learning-note",
                "course-note",
            }:
                continue
            body = _body(content, parsed)
            if not _has_content(body):
                continue
        except (OSError, UnicodeError, ValueError, TypeError):
            continue

        selected_ids.add(document_id)
        linked_years = [
            source.year
            for source_id in metadata.sources
            if (source := sources.get(source_id)) is not None
            and source.year is not None
        ]
        years.extend(linked_years or _citation_years(body))
    return selected_ids, years


def _citation_years(body):
    for line in body.splitlines()[:80]:
        if not line.lstrip().startswith(">"):
            continue
        if not re.search(r"论文|paper|citation", line, re.IGNORECASE):
            continue
        matches = re.findall(r"\b(?:19|20)\d{2}\b", line)
        if matches:
            return [int(matches[0])]
    return []


def research_anchor_year(root, profile, sources):
    return research_history_context(root, profile, sources).anchor_year


def _body(content, parsed):
    return "\n".join(content.splitlines()[parsed.frontmatter_end_line or 0:])


def _has_content(body):
    return bool("\n".join(line for line in body.splitlines() if not re.match(r"^#{1,6}\s", line)).strip())


def _matches(text, phrases):
    return any(phrase.casefold() in text.casefold() for phrase in phrases)


def historical_plan(repository, profile, query, provider, anchor, now, approved_ids=()):
    """One annual window per stream per Run, with an independent progress key."""
    key = "history:" + query.query_key
    state = repository.get_state(profile.id, query.lens_id, provider, key)
    previous = datetime.fromisoformat(state.completed_through) if state and state.completed_through else None
    checkpoint = repository.history_checkpoint(profile.id, query.lens_id, provider, key)
    start = datetime.fromisoformat(checkpoint["start"]) if checkpoint else previous or datetime(max(1000, anchor - 2), 1, 1, tzinfo=timezone.utc)
    scope = repository.history_scope(profile.id, query.lens_id, provider, key)
    known_ids = set(scope.get("approved_ids", ()))
    # One newly observed approval batch unlocks at most one additional year.
    # Keep the union so removing/reapproving a known entity cannot extend forever.
    ceiling_year = scope.get("ceiling_year", anchor + 3)
    if profile.search.history_seed_year is not None:
        ceiling_year = max(ceiling_year, profile.search.history_seed_year + 3)
    if scope and set(approved_ids) - known_ids:
        ceiling_year += 1
    ceiling_year = min(9999, ceiling_year)
    ceiling = min(now, datetime(ceiling_year, 1, 1, tzinfo=timezone.utc))
    end = min(ceiling, datetime(start.year + 1, 1, 1, tzinfo=timezone.utc))
    return ResearchSearchPlan(
        profile_id=profile.id, lens_id=query.lens_id, provider=provider,
        query_key=key, query_text=query.text,
        slices=(ResearchSearchSlice(start, end),) if start < end else (),
        manual=False, previous_watermark=previous,
        history_scope={"approved_ids": sorted(known_ids | set(approved_ids)), "ceiling_year": ceiling_year},
    )
