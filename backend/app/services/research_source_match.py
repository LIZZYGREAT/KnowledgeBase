"""Conservative canonical Source matching for Research Works."""

from dataclasses import dataclass
from typing import Optional, Sequence

from backend.app.domain.research_runtime import ResearchWorkRecord
from backend.app.domain.source import SourceMetadata
from backend.app.services.research_deduplicator import (
    normalize_arxiv_id,
    normalize_author,
    normalize_doi,
    normalize_openalex_id,
    normalize_title,
)


_IDENTIFIER_NORMALIZERS = (
    ("doi", normalize_doi),
    ("arxiv_id", normalize_arxiv_id),
    ("openalex_id", normalize_openalex_id),
)


@dataclass(frozen=True)
class SourceMatchConflict:
    field: str
    existing_value: str
    discovered_value: str


@dataclass(frozen=True)
class SourceMatchCandidate:
    id: str
    title: str
    matched_by: tuple[str, ...]
    conflicts: tuple[SourceMatchConflict, ...] = ()


@dataclass(frozen=True)
class SourceMatch:
    source: Optional[SourceMetadata] = None
    ambiguous: bool = False
    candidates: tuple[SourceMatchCandidate, ...] = ()


def find_matching_source(
    sources: Sequence[SourceMetadata], work: ResearchWorkRecord
) -> SourceMatch:
    """Match strong identifiers first, then one conflict-free weak identity."""
    work_identifiers = {
        field: normalize_identifier(getattr(work, field))
        for field, normalize_identifier in _IDENTIFIER_NORMALIZERS
    }
    strong_sources: dict[
        str, tuple[SourceMetadata, set[str], tuple[SourceMatchConflict, ...]]
    ] = {}
    conflicting_strong_source_ids = set()

    for source in sources:
        source_identifiers = {
            field: normalize_identifier(getattr(source.identifiers, field))
            for field, normalize_identifier in _IDENTIFIER_NORMALIZERS
        }
        matched_fields = {
            field
            for field, work_identifier in work_identifiers.items()
            if work_identifier is not None
            and source_identifiers[field] == work_identifier
        }
        if not matched_fields:
            continue
        conflicts = {
            field
            for field, work_identifier in work_identifiers.items()
            if work_identifier is not None
            and source_identifiers[field] is not None
            and source_identifiers[field] != work_identifier
        }
        conflict_details = tuple(
            SourceMatchConflict(
                field=field,
                existing_value=_display_identifier(
                    field, getattr(source.identifiers, field)
                ),
                discovered_value=_display_identifier(field, getattr(work, field)),
            )
            for field, _ in _IDENTIFIER_NORMALIZERS
            if field in conflicts
        )
        strong_sources[source.id] = (source, matched_fields, conflict_details)
        if conflicts:
            conflicting_strong_source_ids.add(source.id)

    if len(strong_sources) > 1 or conflicting_strong_source_ids:
        return SourceMatch(
            ambiguous=True,
            candidates=tuple(
                SourceMatchCandidate(
                    id=source.id,
                    title=source.title,
                    matched_by=tuple(sorted(matched_fields)),
                    conflicts=conflict_details,
                )
                for source, matched_fields, conflict_details in sorted(
                    strong_sources.values(), key=lambda item: item[0].id
                )
            ),
        )
    if strong_sources:
        return SourceMatch(source=next(iter(strong_sources.values()))[0])

    if work.year is None or not work.authors:
        return SourceMatch()
    normalized_title = normalize_title(work.title)
    first_author = normalize_author(work.authors[0])
    if not normalized_title or not first_author:
        return SourceMatch()

    weak_sources = []
    for source in sources:
        if source.year is None or abs(source.year - work.year) > 1:
            continue
        if normalize_title(source.title) != normalized_title:
            continue
        if not source.authors or normalize_author(source.authors[0]) != first_author:
            continue

        has_identifier_conflict = any(
            work_identifier is not None
            and (source_identifier := normalize_identifier(
                getattr(source.identifiers, field)
            )) is not None
            and source_identifier != work_identifier
            for field, normalize_identifier in _IDENTIFIER_NORMALIZERS
            for work_identifier in (work_identifiers[field],)
        )
        if not has_identifier_conflict:
            weak_sources.append(source)

    if len(weak_sources) > 1:
        return SourceMatch(
            ambiguous=True,
            candidates=tuple(
                SourceMatchCandidate(
                    id=source.id,
                    title=source.title,
                    matched_by=("title_author_year",),
                )
                for source in sorted(weak_sources, key=lambda item: item.id)
            ),
        )
    if weak_sources:
        return SourceMatch(source=weak_sources[0])
    return SourceMatch()


def _display_identifier(field: str, value: Optional[str]) -> str:
    if value is None:
        return ""
    if field == "openalex_id" and value:
        return value[0].upper() + value[1:]
    return value
