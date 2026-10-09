"""Normalize provider identifiers and persist deduplicated Research discovery."""

from datetime import datetime, timezone
import json
import re
import unicodedata
from typing import Callable, Optional
from urllib.parse import unquote, urlsplit
import uuid

from backend.app.domain.research_runtime import (
    ResearchDiscoveryRecord,
    ResearchIngestResult,
    ResearchWorkRecord,
)
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.research_providers.base import ProviderWork


_IDENTIFIER_ORDER = (
    ("doi", "doi"),
    ("arxiv_id", "arxiv_id"),
    ("openalex_id", "openalex_id"),
    ("semantic_scholar_id", "semantic_scholar_id"),
)
_PROVIDER_PRIORITY = {"arxiv": 0, "openalex": 1, "crossref": 2}


class ResearchIdentityConflict(RuntimeError):
    """Provider identifiers point at more than one existing Research Work."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        matched_work_ids: tuple[str, ...] = (),
    ):
        super().__init__(message)
        self.reason = reason
        self.matched_work_ids = tuple(sorted(set(matched_work_ids)))


class ResearchDeduplicator:
    def __init__(
        self,
        repository: ResearchRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ):
        self.repository = repository
        self.clock = clock
        self.id_factory = id_factory

    def enrich_existing_work(
        self, work_id: str, provider_work: ProviderWork
    ) -> ResearchWorkRecord:
        """Fill missing Work metadata without recording enrichment as a Discovery."""
        if not isinstance(provider_work, ProviderWork):
            raise ValueError("provider_work must be a ProviderWork")
        incoming = normalize_identifiers(provider_work)
        with self.repository.write_transaction():
            existing = self.repository.get_work(work_id)
            if existing is None:
                raise LookupError("Research Work '{}' does not exist".format(work_id))
            matches = self.repository.find_by_identifiers(incoming)
            if len(matches) > 1:
                raise ResearchIdentityConflict(
                    "Provider identifiers resolve to multiple Research Works",
                    reason="multiple_identifier_matches",
                    matched_work_ids=tuple(work.id for work in matches),
                )
            if matches and matches[0].id != existing.id:
                raise ResearchIdentityConflict(
                    "Enrichment identifiers resolve to a different Research Work",
                    reason="enrichment_target_mismatch",
                    matched_work_ids=(existing.id, matches[0].id),
                )
            if not any(
                value is not None and value == getattr(existing, column)
                for column, value in incoming.items()
            ):
                raise ValueError("Enrichment result does not identify the requested Research Work")

            self._validate_identifier_consistency(existing, incoming)

            identifiers = {
                column: getattr(existing, column) or incoming[column]
                for column in incoming
            }
            title = existing.title or provider_work.title
            abstract = existing.abstract or provider_work.abstract
            authors = existing.authors or provider_work.authors
            year = existing.year or provider_work.year
            normalized_title = normalize_title(title) or existing.normalized_title
            updated = ResearchWorkRecord(
                id=existing.id,
                canonical_key=_canonical_key(
                    identifiers, normalized_title, year, authors
                ),
                title=title,
                normalized_title=normalized_title,
                abstract=abstract,
                authors=authors,
                year=year,
                published_at=existing.published_at or provider_work.published_at,
                venue=existing.venue or provider_work.venue,
                doi=identifiers["doi"],
                arxiv_id=identifiers["arxiv_id"],
                openalex_id=identifiers["openalex_id"],
                semantic_scholar_id=identifiers["semantic_scholar_id"],
                url=existing.url or provider_work.url,
                created_at=existing.created_at,
                updated_at=_utc_timestamp(self.clock()),
            )
            self.repository.update_work(updated)
        return updated

    def record_discovery(
        self,
        profile_id: str,
        lens_id: str,
        query_key: str,
        query_text: str,
        provider_work: ProviderWork,
        discovered_at: Optional[datetime] = None,
    ) -> ResearchIngestResult:
        if not isinstance(provider_work, ProviderWork):
            raise ValueError("provider_work must be a ProviderWork")
        if not isinstance(query_text, str) or not query_text.strip():
            raise ValueError("Research discovery query_text must be non-empty")
        when = discovered_at if discovered_at is not None else self.clock()
        timestamp = _utc_timestamp(when)
        title_key = normalize_title(provider_work.title)
        if not title_key:
            raise ValueError("Research Work title has no searchable characters")
        identifiers = normalize_identifiers(provider_work)
        snapshot = _provider_metadata_snapshot(provider_work, identifiers)
        try:
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("Provider metadata must contain JSON-compatible values") from error

        with self.repository.write_transaction():
            existing, match_method, ambiguous = self._find_existing(
                provider_work, identifiers, title_key
            )
            created_work = existing is None
            if created_work:
                work = self._new_work(provider_work, identifiers, title_key, timestamp)
                self.repository.insert_work(work)
            else:
                preferred_provider = self.repository.preferred_provider(existing.id)
                work = self._merge_work(
                    existing,
                    provider_work,
                    identifiers,
                    title_key,
                    preferred_provider,
                    timestamp,
                )
                self.repository.update_work(work)

            discovery = ResearchDiscoveryRecord(
                id=self.id_factory(),
                work_id=work.id,
                profile_id=profile_id,
                lens_id=lens_id,
                provider=provider_work.provider,
                provider_record_id=provider_work.provider_record_id,
                query_key=query_key,
                query_text=query_text.strip(),
                metadata=snapshot,
                discovered_at=timestamp,
            )
            persisted_discovery, created_discovery = self.repository.add_discovery_if_missing(
                discovery
            )
            if persisted_discovery.work_id != work.id:
                raise ResearchIdentityConflict(
                    "Provider discovery provenance is already linked to another Research Work",
                    reason="discovery_provenance_mismatch",
                    matched_work_ids=(work.id, persisted_discovery.work_id),
                )

        if ambiguous:
            match_method = "ambiguous_weak_match"
        return ResearchIngestResult(
            work=work,
            discovery=persisted_discovery,
            created_work=created_work,
            created_discovery=created_discovery,
            match_method=match_method,
        )

    def _find_existing(
        self,
        provider_work: ProviderWork,
        identifiers: dict[str, Optional[str]],
        title_key: str,
    ) -> tuple[Optional[ResearchWorkRecord], str, bool]:
        matches = self.repository.find_by_identifiers(identifiers)
        if len(matches) > 1:
            raise ResearchIdentityConflict(
                "Provider identifiers resolve to multiple Research Works",
                reason="multiple_identifier_matches",
                matched_work_ids=tuple(work.id for work in matches),
            )
        if matches:
            matched = matches[0]
            self._validate_identifier_consistency(matched, identifiers)
            for identifier_name, column in _IDENTIFIER_ORDER:
                value = identifiers[column]
                if value is not None and getattr(matched, column) == value:
                    return matched, identifier_name, False

        if provider_work.year is None or not provider_work.authors:
            return None, "new", False
        first_author = normalize_author(provider_work.authors[0])
        if not first_author:
            return None, "new", False

        candidates = []
        for candidate in self.repository.find_weak_candidates(title_key, provider_work.year):
            if not candidate.authors or normalize_author(candidate.authors[0]) != first_author:
                continue
            if _has_conflicting_identifiers(candidate, identifiers):
                continue
            candidates.append(candidate)
        if len(candidates) == 1:
            return candidates[0], "title_author_year", False
        return None, "ambiguous_weak_match" if candidates else "new", len(candidates) > 1

    @staticmethod
    def _validate_identifier_consistency(
        existing: ResearchWorkRecord, incoming: dict[str, Optional[str]]
    ) -> None:
        conflicting_fields = tuple(
            column
            for _, column in _IDENTIFIER_ORDER
            if incoming[column] is not None
            and getattr(existing, column) is not None
            and incoming[column] != getattr(existing, column)
        )
        if conflicting_fields:
            raise ResearchIdentityConflict(
                "Incoming strong identifiers conflict with the matched Research Work",
                reason="conflicting_identifier_values:{}".format(",".join(conflicting_fields)),
                matched_work_ids=(existing.id,),
            )

    def _new_work(
        self,
        provider_work: ProviderWork,
        identifiers: dict[str, Optional[str]],
        title_key: str,
        timestamp: str,
    ) -> ResearchWorkRecord:
        return ResearchWorkRecord(
            id=self.id_factory(),
            canonical_key=_canonical_key(
                identifiers, title_key, provider_work.year, provider_work.authors
            ),
            title=provider_work.title,
            normalized_title=title_key,
            abstract=provider_work.abstract,
            authors=provider_work.authors,
            year=provider_work.year,
            published_at=provider_work.published_at,
            venue=provider_work.venue,
            doi=identifiers["doi"],
            arxiv_id=identifiers["arxiv_id"],
            openalex_id=identifiers["openalex_id"],
            semantic_scholar_id=identifiers["semantic_scholar_id"],
            url=provider_work.url,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _merge_work(
        self,
        existing: ResearchWorkRecord,
        provider_work: ProviderWork,
        identifiers: dict[str, Optional[str]],
        title_key: str,
        preferred_provider: Optional[str],
        timestamp: str,
    ) -> ResearchWorkRecord:
        incoming_rank = _PROVIDER_PRIORITY[provider_work.provider]
        current_rank = _PROVIDER_PRIORITY.get(preferred_provider or "", -1)
        can_prefer_incoming = incoming_rank > current_rank or (
            incoming_rank == current_rank and provider_work.provider == preferred_provider
        )

        self._validate_identifier_consistency(existing, identifiers)
        merged_identifiers = {
            column: getattr(existing, column) or identifiers[column]
            for column in ("doi", "arxiv_id", "openalex_id", "semantic_scholar_id")
        }

        title = _choose(existing.title, provider_work.title, can_prefer_incoming)
        normalized_title = normalize_title(title) or title_key
        authors = _choose(existing.authors, provider_work.authors, can_prefer_incoming)
        year = _choose(existing.year, provider_work.year, can_prefer_incoming)
        return ResearchWorkRecord(
            id=existing.id,
            canonical_key=_canonical_key(
                merged_identifiers, normalized_title, year, authors
            ),
            title=title,
            normalized_title=normalized_title,
            abstract=_choose(existing.abstract, provider_work.abstract, can_prefer_incoming),
            authors=authors,
            year=year,
            published_at=_choose(
                existing.published_at, provider_work.published_at, can_prefer_incoming
            ),
            venue=_choose(existing.venue, provider_work.venue, can_prefer_incoming),
            doi=merged_identifiers["doi"],
            arxiv_id=merged_identifiers["arxiv_id"],
            openalex_id=merged_identifiers["openalex_id"],
            semantic_scholar_id=merged_identifiers["semantic_scholar_id"],
            url=_choose(existing.url, provider_work.url, can_prefer_incoming),
            created_at=existing.created_at,
            updated_at=timestamp,
        )


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in normalized
    )
    return " ".join(without_punctuation.split())


def normalize_author(value: str) -> str:
    return normalize_title(value)


def normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value or not value.strip():
        return None
    normalized = unquote(value.strip())
    parsed = urlsplit(normalized)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if host in {"doi.org", "www.doi.org", "dx.doi.org"}:
        normalized = parsed.path.lstrip("/")
    normalized = normalized.strip()
    if normalized[:4].casefold() == "doi:":
        normalized = normalized[4:].strip()
    return normalized.casefold() or None


def normalize_arxiv_id(value: Optional[str]) -> Optional[str]:
    if not value or not value.strip():
        return None
    normalized = unquote(value.strip())
    parsed = urlsplit(normalized)
    if _host_matches(parsed.hostname or "", "arxiv.org"):
        normalized = parsed.path
        for prefix in ("/abs/", "/pdf/"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
    if normalized.casefold().startswith("arxiv:"):
        normalized = normalized[len("arxiv:") :]
    normalized = normalized.strip().strip("/")
    if normalized.casefold().endswith(".pdf"):
        normalized = normalized[:-4]
    normalized = re.sub(r"v[0-9]+$", "", normalized, flags=re.IGNORECASE)
    return normalized.casefold() or None


def normalize_openalex_id(value: Optional[str]) -> Optional[str]:
    return _normalize_url_or_prefixed_id(value, "openalex.org", "openalex:")


def normalize_semantic_scholar_id(value: Optional[str]) -> Optional[str]:
    return _normalize_url_or_prefixed_id(value, "semanticscholar.org", "semantic-scholar:")


def normalize_identifiers(provider_work: ProviderWork) -> dict[str, Optional[str]]:
    return {
        "doi": normalize_doi(provider_work.doi),
        "arxiv_id": normalize_arxiv_id(provider_work.arxiv_id),
        "openalex_id": normalize_openalex_id(provider_work.openalex_id),
        "semantic_scholar_id": normalize_semantic_scholar_id(
            provider_work.semantic_scholar_id
        ),
    }


def _normalize_url_or_prefixed_id(
    value: Optional[str], host_suffix: str, prefix: str
) -> Optional[str]:
    if not value or not value.strip():
        return None
    normalized = unquote(value.strip())
    parsed = urlsplit(normalized)
    if _host_matches(parsed.hostname or "", host_suffix):
        normalized = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    elif normalized.casefold().startswith(prefix):
        normalized = normalized[len(prefix) :]
    normalized = normalized.strip().strip("/")
    return normalized.casefold() or None


def _host_matches(host: str, suffix: str) -> bool:
    normalized_host = host.casefold().rstrip(".")
    normalized_suffix = suffix.casefold()
    return normalized_host == normalized_suffix or normalized_host.endswith(
        "." + normalized_suffix
    )


def _has_conflicting_identifiers(
    candidate: ResearchWorkRecord, incoming: dict[str, Optional[str]]
) -> bool:
    return any(
        incoming[column] is not None
        and getattr(candidate, column) is not None
        and incoming[column] != getattr(candidate, column)
        for _, column in _IDENTIFIER_ORDER
    )


def _canonical_key(
    identifiers: dict[str, Optional[str]],
    title_key: str,
    year: Optional[int],
    authors: tuple[str, ...],
) -> str:
    for _, column in _IDENTIFIER_ORDER:
        if identifiers[column]:
            return "{}:{}".format(column, identifiers[column])
    first_author = normalize_author(authors[0]) if authors else ""
    year_value = year if year is not None else "unknown"
    return "title:{}:{}:{}".format(title_key, year_value, first_author)


def _choose(current, incoming, can_prefer_incoming):
    if incoming is None or incoming == "" or incoming == ():
        return current
    if current is None or current == "" or current == () or can_prefer_incoming:
        return incoming
    return current


def _provider_metadata_snapshot(
    provider_work: ProviderWork, identifiers: dict[str, Optional[str]]
) -> dict:
    """Keep the normalized record subset, never a full provider response."""
    return {
        "provider_record_id": provider_work.provider_record_id,
        "title": provider_work.title,
        "abstract": provider_work.abstract,
        "authors": list(provider_work.authors),
        "year": provider_work.year,
        "published_at": provider_work.published_at,
        "venue": provider_work.venue,
        "identifiers": identifiers,
        "url": provider_work.url,
        "provider_metadata": provider_work.metadata,
    }


def _utc_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Research discovery timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()
