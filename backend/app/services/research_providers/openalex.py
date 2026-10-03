"""Adapter for OpenAlex Works search and cursor pagination."""

from datetime import datetime
from typing import Any, Optional

from pydantic import ValidationError

from .base import (
    ProviderPage,
    ProviderResponseError,
    ProviderWork,
    ResearchHttpClient,
    build_url,
    validate_search_request,
)


_WORKS_ENDPOINT = "https://api.openalex.org/works"


class OpenAlexProvider:
    name = "openalex"

    def __init__(
        self,
        timeout_seconds: float = 20,
        max_retries: int = 3,
        page_size: int = 100,
        client: Optional[ResearchHttpClient] = None,
    ):
        if page_size < 1 or page_size > 100:
            raise ValueError("OpenAlex page_size must be from 1 to 100")
        self.page_size = page_size
        self.client = client or ResearchHttpClient(
            self.name,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    def search(
        self,
        query: str,
        start_at: datetime,
        end_at: datetime,
        cursor: Optional[str] = None,
    ) -> ProviderPage:
        start_utc, end_utc = validate_search_request(query, start_at, end_at)
        parameters = [
            ("search", query.strip()),
            (
                "filter",
                "from_publication_date:{},to_publication_date:{}".format(
                    start_utc.date().isoformat(), end_utc.date().isoformat()
                ),
            ),
            ("per_page", str(self.page_size)),
            ("cursor", cursor or "*"),
        ]
        payload = self.client.get_json(build_url(_WORKS_ENDPOINT, parameters))
        meta = payload.get("meta")
        results = payload.get("results")
        if not isinstance(meta, dict) or not isinstance(results, list):
            raise ProviderResponseError(self.name, "response is missing meta or results")
        works = tuple(_parse_work(item) for item in results)
        next_cursor = meta.get("next_cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ProviderResponseError(self.name, "meta.next_cursor must be text or null")
        total_count = _integer(meta.get("count"))
        return ProviderPage(
            works=works,
            next_cursor=next_cursor,
            total_count=total_count,
        )


def _parse_work(value: Any) -> ProviderWork:
    if not isinstance(value, dict):
        raise ProviderResponseError("openalex", "work entry must be an object")
    raw_id = _text(value.get("id"))
    openalex_id = raw_id.rstrip("/").rsplit("/", 1)[-1] if raw_id else ""
    title = _text(value.get("title")) or _text(value.get("display_name"))
    if not openalex_id or not title:
        raise ProviderResponseError("openalex", "work entry is missing id or title")

    authors = []
    for authorship in value.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict):
            name = _text(author.get("display_name"))
            if name:
                authors.append(name)

    primary_location = value.get("primary_location")
    if not isinstance(primary_location, dict):
        primary_location = {}
    source = primary_location.get("source")
    if not isinstance(source, dict):
        source = {}
    host_venue = value.get("host_venue")
    if not isinstance(host_venue, dict):
        host_venue = {}

    ids = value.get("ids")
    if not isinstance(ids, dict):
        ids = {}
    doi_value = value.get("doi") or ids.get("doi")
    doi = _normalize_doi(_text(doi_value))
    published_at = _text(value.get("publication_date")) or None
    year = _integer(value.get("publication_year"))
    landing_page = _text(primary_location.get("landing_page_url"))
    openalex_url = raw_id if raw_id.startswith("http") else "https://openalex.org/{}".format(openalex_id)

    open_access = value.get("open_access")
    if not isinstance(open_access, dict):
        open_access = {}
    metadata = {
        "type": value.get("type"),
        "cited_by_count": _integer(value.get("cited_by_count")),
        "is_retracted": value.get("is_retracted"),
        "open_access": {
            "is_oa": open_access.get("is_oa"),
            "oa_status": open_access.get("oa_status"),
        },
    }
    try:
        return ProviderWork(
            provider="openalex",
            provider_record_id=openalex_id,
            title=title,
            abstract=_abstract_from_inverted_index(value.get("abstract_inverted_index")),
            authors=tuple(authors),
            year=year,
            published_at=published_at,
            venue=_text(source.get("display_name"))
            or _text(host_venue.get("display_name"))
            or None,
            doi=doi,
            openalex_id=openalex_id,
            url=landing_page or openalex_url,
            metadata=metadata,
        )
    except (ValidationError, ValueError) as error:
        raise ProviderResponseError("openalex", "work metadata is invalid") from error


def _abstract_from_inverted_index(value: Any) -> Optional[str]:
    if not isinstance(value, dict) or not value:
        return None
    words: dict[int, str] = {}
    for token, positions in value.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                words[position] = token
    if not words:
        return None
    return " ".join(words.get(position, "") for position in range(max(words) + 1)).strip() or None


def _normalize_doi(value: str) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized.lower() or None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _integer(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
