"""Shared canonical Source identity matching for Research Works."""

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


def find_matching_source(
    sources: Sequence[SourceMetadata], work: ResearchWorkRecord
) -> Optional[SourceMetadata]:
    """Match by DOI, arXiv, OpenAlex, then title, first author, and year ±1."""
    for field, normalize_identifier in _IDENTIFIER_NORMALIZERS:
        work_identifier = normalize_identifier(getattr(work, field))
        if work_identifier is None:
            continue
        for source in sources:
            source_identifier = normalize_identifier(
                getattr(source.identifiers, field)
            )
            if source_identifier == work_identifier:
                return source

    if work.year is None or not work.authors:
        return None
    normalized_title = normalize_title(work.title)
    first_author = normalize_author(work.authors[0])
    if not normalized_title or not first_author:
        return None

    for source in sources:
        if (
            source.year is not None
            and abs(source.year - work.year) <= 1
            and normalize_title(source.title) == normalized_title
            and source.authors
            and normalize_author(source.authors[0]) == first_author
        ):
            return source
    return None
