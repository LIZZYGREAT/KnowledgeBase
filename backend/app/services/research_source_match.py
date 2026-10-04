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
class SourceMatch:
    source: Optional[SourceMetadata] = None
    ambiguous: bool = False


def find_matching_source(
    sources: Sequence[SourceMetadata], work: ResearchWorkRecord
) -> SourceMatch:
    """Match strong identifiers first, then one conflict-free weak identity."""
    work_identifiers = {
        field: normalize_identifier(getattr(work, field))
        for field, normalize_identifier in _IDENTIFIER_NORMALIZERS
    }
    strong_sources: dict[str, SourceMetadata] = {}
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
        strong_sources[source.id] = source
        if conflicts:
            conflicting_strong_source_ids.add(source.id)

    if len(strong_sources) > 1 or conflicting_strong_source_ids:
        return SourceMatch(ambiguous=True)
    if strong_sources:
        return SourceMatch(source=next(iter(strong_sources.values())))

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
        return SourceMatch(ambiguous=True)
    if weak_sources:
        return SourceMatch(source=weak_sources[0])
    return SourceMatch()
