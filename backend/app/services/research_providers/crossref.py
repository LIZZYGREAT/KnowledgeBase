"""Adapter for Crossref Works search."""

from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import quote

from pydantic import ValidationError

from .base import (
    ProviderPage,
    ProviderResponseError,
    ProviderWork,
    ResearchHttpClient,
    build_url,
    parse_nonnegative_cursor,
    validate_search_request,
)


_WORKS_ENDPOINT = "https://api.crossref.org/works"


class CrossrefProvider:
    name = "crossref"

    def __init__(
        self,
        timeout_seconds: float = 20,
        max_retries: int = 3,
        page_size: int = 100,
        client: Optional[ResearchHttpClient] = None,
    ):
        if page_size < 1 or page_size > 1000:
            raise ValueError("Crossref page_size must be from 1 to 1000")
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
        offset = parse_nonnegative_cursor(cursor, self.name)
        url = build_url(
            _WORKS_ENDPOINT,
            [
                ("query.bibliographic", query.strip()),
                (
                    "filter",
                    "from-pub-date:{},until-pub-date:{}".format(
                        start_utc.date().isoformat(), end_utc.date().isoformat()
                    ),
                ),
                ("rows", str(self.page_size)),
                ("offset", str(offset)),
            ],
        )
        payload = self.client.get_json(url)
        message = payload.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("items"), list):
            raise ProviderResponseError(self.name, "response is missing message.items")
        items = message["items"]
        works = tuple(_parse_work(item) for item in items)
        total_count = _integer(message.get("total-results"))
        next_offset = offset + len(works)
        next_cursor = (
            str(next_offset)
            if len(works) == self.page_size
            and (total_count is None or next_offset < total_count)
            else None
        )
        return ProviderPage(
            works=works,
            next_cursor=next_cursor,
            total_count=total_count,
        )

    def enrich(self, work) -> Optional[ProviderWork]:
        if not work.doi:
            return None
        payload = self.client.get_json(
            "{}/{}".format(_WORKS_ENDPOINT, quote(work.doi, safe=""))
        )
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ProviderResponseError(self.name, "singleton response is missing message")
        return _parse_work(message)


def _parse_work(value: Any) -> ProviderWork:
    if not isinstance(value, dict):
        raise ProviderResponseError("crossref", "work entry must be an object")
    doi = _normalize_doi(value.get("DOI"))
    url = _text(value.get("URL"))
    record_id = doi or url
    title = _first_text(value.get("title"))
    if not record_id or not title:
        raise ProviderResponseError("crossref", "work entry is missing DOI/URL or title")

    authors = []
    for author in value.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = _text(author.get("literal"))
        if not name:
            name = " ".join(
                part for part in (_text(author.get("given")), _text(author.get("family"))) if part
            )
        if name:
            authors.append(name)

    published_at, year = _published_date(value)
    abstract = _strip_markup(_text(value.get("abstract"))) or None
    venue = _first_text(value.get("container-title")) or None
    metadata = {
        "type": _text(value.get("type")) or None,
        "publisher": _text(value.get("publisher")) or None,
        "score": _number(value.get("score")),
    }
    if not url and doi:
        url = "https://doi.org/{}".format(doi)
    try:
        return ProviderWork(
            provider="crossref",
            provider_record_id=record_id,
            title=title,
            abstract=abstract,
            authors=tuple(authors),
            year=year,
            published_at=published_at,
            venue=venue,
            doi=doi,
            url=url or None,
            metadata=metadata,
        )
    except (ValidationError, ValueError) as error:
        raise ProviderResponseError("crossref", "work metadata is invalid") from error


def _published_date(value: dict) -> tuple[Optional[str], Optional[int]]:
    for key in ("published-online", "published-print", "published", "issued"):
        entry = value.get(key)
        if not isinstance(entry, dict):
            continue
        date_parts = entry.get("date-parts")
        if not isinstance(date_parts, list) or not date_parts or not isinstance(date_parts[0], list):
            continue
        parts = date_parts[0]
        year = _integer(parts[0]) if parts else None
        if year is None:
            continue
        month = _integer(parts[1]) if len(parts) > 1 else None
        day = _integer(parts[2]) if len(parts) > 2 else None
        published_at = "{:04d}".format(year)
        if month is not None:
            published_at += "-{:02d}".format(month)
            if day is not None:
                published_at += "-{:02d}".format(day)
        return published_at, year
    return None, None


def _normalize_doi(value: Any) -> Optional[str]:
    normalized = _text(value)
    if not normalized:
        return None
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.lower().startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized.lower() or None


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return next((item.strip() for item in value if isinstance(item, str) and item.strip()), "")
    return ""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _integer(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class _PlainTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _strip_markup(value: str) -> str:
    parser = _PlainTextParser()
    parser.feed(value)
    parser.close()
    return " ".join(" ".join(parser.parts).split())
