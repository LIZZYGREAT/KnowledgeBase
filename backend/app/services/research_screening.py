"""Deterministic Research filtering and queue-priority scoring."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Optional

from backend.app.domain.research import ResearchProfile
from backend.app.domain.research_runtime import ResearchWorkRecord
from backend.app.services.research_deduplicator import (
    normalize_arxiv_id,
    normalize_author,
    normalize_doi,
    normalize_title,
)
from backend.app.services.research_providers.base import validate_search_request
from backend.app.services.research_query_builder import ResearchQuery
from backend.app.services.research_watermark import ResearchSearchSlice
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.source_registry import SourceRegistry


_PRIORITY_SCORE = {"low": 0.33, "medium": 0.67, "high": 1.0}
_PRE_RANK_WEIGHTS = {"query": 0.4, "lens": 0.2, "recency": 0.2, "metadata": 0.2}


@dataclass(frozen=True)
class PreRankScore:
    score: float
    query_lexical_match: float
    lens_priority: float
    recency: float
    metadata_completeness: float


@dataclass(frozen=True)
class ScreeningDecision:
    eligible: bool
    filtered_reasons: tuple[str, ...]
    metadata_warnings: tuple[str, ...]
    pre_rank: Optional[PreRankScore]


class ResearchScreeningService:
    def __init__(
        self,
        repository: ResearchRepository,
        sources: SourceRegistry,
    ):
        self.repository = repository
        self.sources = sources

    def screen(
        self,
        work: ResearchWorkRecord,
        profile: ResearchProfile,
        query: ResearchQuery,
        search_slice: ResearchSearchSlice,
        now: datetime,
    ) -> ScreeningDecision:
        if query.profile_id != profile.id:
            raise ValueError("Research Query belongs to a different Profile")
        if query.lens_id not in {lens.id for lens in profile.lenses}:
            raise ValueError("Research Query references an unknown Lens")
        lens = next(lens for lens in profile.lenses if lens.id == query.lens_id)
        if (
            query.priority != lens.priority
            or query.lens_title != lens.title
            or query.include_terms != tuple(lens.include_terms)
            or query.exclude_terms != tuple(lens.exclude_terms)
            or query.profile_exclude_terms != tuple(profile.exclude_terms)
        ):
            raise ValueError("Research Query Lens settings do not match the Profile")

        start_at, end_at = validate_search_request("screen", search_slice.start_at, search_slice.end_at)
        now_utc = _as_utc(now, "now")
        reasons = []
        warnings = []

        title = work.title.strip()
        if not title:
            reasons.append("missing_title")
        publication = _publication_interval(work)
        if publication is None:
            reasons.append("missing_publication_date")
            published_at = None
        else:
            publication_start, publication_end, published_at = publication
            if publication_start >= end_at or publication_end <= start_at:
                reasons.append("outside_search_range")

        if not work.abstract or not work.abstract.strip():
            warnings.append("missing_abstract")
        if not work.authors:
            warnings.append("missing_authors")

        searchable_text = normalize_title("{} {}".format(title, work.abstract or ""))
        exclude_terms = tuple(query.exclude_terms) + tuple(query.profile_exclude_terms)
        if any(_contains_term(searchable_text, term) for term in exclude_terms):
            reasons.append("excluded_term")

        include_terms = tuple(query.include_terms)
        if include_terms and not any(
            _contains_term(searchable_text, term) for term in include_terms
        ):
            reasons.append("include_term_not_matched")

        if self._matches_canonical_source(work):
            reasons.append("existing_source")
        if self.repository.has_candidate_for_profile(work.id, profile.id):
            reasons.append("existing_candidate")
        if reasons:
            return ScreeningDecision(
                eligible=False,
                filtered_reasons=tuple(dict.fromkeys(reasons)),
                metadata_warnings=tuple(dict.fromkeys(warnings)),
                pre_rank=None,
            )

        score = _pre_rank(
            work=work,
            query=query,
            published_at=published_at,
            now=now_utc,
        )
        return ScreeningDecision(
            eligible=True,
            filtered_reasons=(),
            metadata_warnings=tuple(dict.fromkeys(warnings)),
            pre_rank=score,
        )

    def _matches_canonical_source(self, work: ResearchWorkRecord) -> bool:
        doi = normalize_doi(work.doi)
        arxiv_id = normalize_arxiv_id(work.arxiv_id)
        normalized_title = normalize_title(work.title)
        first_author = normalize_author(work.authors[0]) if work.authors else ""

        for source in self.sources.sources:
            source_doi = normalize_doi(source.identifiers.doi)
            source_arxiv_id = normalize_arxiv_id(source.identifiers.arxiv_id)
            if doi and source_doi == doi:
                return True
            if arxiv_id and source_arxiv_id == arxiv_id:
                return True
            if (
                normalized_title
                and source.year is not None
                and work.year is not None
                and abs(source.year - work.year) <= 1
                and normalize_title(source.title) == normalized_title
                and source.authors
                and first_author
                and normalize_author(source.authors[0]) == first_author
            ):
                return True
        return False


def _pre_rank(
    work: ResearchWorkRecord,
    query: ResearchQuery,
    published_at: datetime,
    now: datetime,
) -> PreRankScore:
    content_tokens = set(normalize_title("{} {}".format(work.title, work.abstract or "")).split())
    query_tokens = set(normalize_title(query.text).split())
    query_score = (
        len(content_tokens & query_tokens) / len(query_tokens) if query_tokens else 0.0
    )
    lens_score = _PRIORITY_SCORE[query.priority]
    age_days = max(0.0, (now - published_at).total_seconds() / 86_400)
    recency_score = 1.0 / (1.0 + age_days / 365.0)
    metadata_fields = (
        bool(work.title.strip()),
        bool(work.abstract and work.abstract.strip()),
        bool(work.authors),
        work.year is not None or work.published_at is not None,
        bool(work.doi or work.arxiv_id or work.openalex_id or work.semantic_scholar_id),
        bool(work.venue),
        bool(work.url),
    )
    completeness = sum(metadata_fields) / len(metadata_fields)
    score = (
        _PRE_RANK_WEIGHTS["query"] * query_score
        + _PRE_RANK_WEIGHTS["lens"] * lens_score
        + _PRE_RANK_WEIGHTS["recency"] * recency_score
        + _PRE_RANK_WEIGHTS["metadata"] * completeness
    )
    return PreRankScore(
        score=round(score, 6),
        query_lexical_match=round(query_score, 6),
        lens_priority=round(lens_score, 6),
        recency=round(recency_score, 6),
        metadata_completeness=round(completeness, 6),
    )


def _publication_interval(
    work: ResearchWorkRecord,
) -> Optional[tuple[datetime, datetime, datetime]]:
    raw = (work.published_at or "").strip()
    if raw:
        try:
            if re.fullmatch(r"\d{4}", raw):
                start = datetime(int(raw), 1, 1, tzinfo=timezone.utc)
                end = datetime(int(raw) + 1, 1, 1, tzinfo=timezone.utc)
                return start, end, start + (end - start) / 2
            if re.fullmatch(r"\d{4}-\d{2}", raw):
                year, month = (int(part) for part in raw.split("-"))
                start = datetime(year, month, 1, tzinfo=timezone.utc)
                end = (
                    datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                    if month == 12
                    else datetime(year, month + 1, 1, tzinfo=timezone.utc)
                )
                return start, end, start + (end - start) / 2
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                published_day = date.fromisoformat(raw)
                start = datetime.combine(published_day, time.min, tzinfo=timezone.utc)
                return start, start + timedelta(days=1), start + timedelta(hours=12)
            instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            instant = _as_utc(instant, "published_at")
            return instant, instant + timedelta(microseconds=1), instant
        except (ValueError, OverflowError):
            pass

    if work.year is None or work.year < 1 or work.year > 9998:
        return None
    start = datetime(work.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(work.year + 1, 1, 1, tzinfo=timezone.utc)
    return start, end, start + (end - start) / 2


def _contains_term(normalized_text: str, term: str) -> bool:
    normalized_term = normalize_title(term)
    if not normalized_term:
        raise ValueError("Research screening terms must contain searchable text")
    return " {} ".format(normalized_term) in " {} ".format(normalized_text)


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("{} must be timezone-aware".format(label))
    return value.astimezone(timezone.utc)
