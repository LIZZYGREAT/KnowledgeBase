"""Adapter for the arXiv Atom query API."""

from datetime import datetime
import re
from typing import Optional
import xml.etree.ElementTree as ET

from pydantic import ValidationError

from .base import (
    ProviderPage,
    ProviderResponseError,
    ProviderWork,
    ResearchHttpClient,
    build_url,
    effective_page_size,
    parse_nonnegative_cursor,
    validate_search_request,
)


_ATOM_NS = "http://www.w3.org/2005/Atom"
_OPEN_SEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_NAMESPACES = {"atom": _ATOM_NS, "opensearch": _OPEN_SEARCH_NS, "arxiv": _ARXIV_NS}
_QUERY_ENDPOINT = "https://export.arxiv.org/api/query"


class ArxivProvider:
    name = "arxiv"

    def __init__(
        self,
        timeout_seconds: float = 20,
        max_retries: int = 3,
        page_size: int = 100,
        client: Optional[ResearchHttpClient] = None,
    ):
        if page_size < 1 or page_size > 2000:
            raise ValueError("arXiv page_size must be from 1 to 2000")
        self.page_size = page_size
        self.client = client or ResearchHttpClient(
            self.name,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            minimum_interval_seconds=3,
        )

    def search(
        self,
        query: str,
        start_at: datetime,
        end_at: datetime,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> ProviderPage:
        start_utc, end_utc = validate_search_request(query, start_at, end_at)
        page_size = effective_page_size(self.page_size, limit)
        offset = parse_nonnegative_cursor(cursor, self.name)
        date_range = "submittedDate:[{} TO {}]".format(
            start_utc.strftime("%Y%m%d%H%M"), end_utc.strftime("%Y%m%d%H%M")
        )
        escaped_query = query.strip().replace("\\", "\\\\").replace('"', '\\"')
        search_query = 'all:"{}" AND {}'.format(escaped_query, date_range)
        url = build_url(
            _QUERY_ENDPOINT,
            [
                ("search_query", search_query),
                ("start", str(offset)),
                ("max_results", str(page_size)),
                ("sortBy", "submittedDate"),
                ("sortOrder", "ascending"),
            ],
        )

        try:
            feed = ET.fromstring(self.client.get(url, "application/atom+xml"))
        except ET.ParseError as error:
            raise ProviderResponseError(self.name, "response was not valid Atom XML") from error
        entries = feed.findall("atom:entry", _NAMESPACES)
        works = tuple(_parse_entry(entry) for entry in entries)
        total_count = _integer_text(feed.findtext("opensearch:totalResults", namespaces=_NAMESPACES))
        next_offset = offset + len(works)
        next_cursor = (
            str(next_offset)
            if len(works) == page_size
            and (total_count is None or next_offset < total_count)
            else None
        )
        return ProviderPage(
            works=works,
            next_cursor=next_cursor,
            total_count=total_count,
        )


def _parse_entry(entry: ET.Element) -> ProviderWork:
    entry_id = _element_text(entry, "atom:id")
    match = re.search(r"/abs/([^?#]+)", entry_id)
    if match is None:
        raise ProviderResponseError("arxiv", "entry is missing a valid arXiv identifier")
    versioned_id = match.group(1)
    arxiv_id = re.sub(r"v\d+$", "", versioned_id)
    published_at = _element_text(entry, "atom:published") or None
    authors = tuple(
        text
        for author in entry.findall("atom:author", _NAMESPACES)
        if (text := _element_text(author, "atom:name"))
    )
    categories = [
        item.attrib["term"]
        for item in entry.findall("atom:category", _NAMESPACES)
        if item.attrib.get("term")
    ]
    doi = _element_text(entry, "arxiv:doi") or None
    journal_ref = _element_text(entry, "arxiv:journal_ref") or None
    updated = _element_text(entry, "atom:updated") or None
    try:
        return ProviderWork(
            provider="arxiv",
            provider_record_id=versioned_id,
            title=_element_text(entry, "atom:title"),
            abstract=_element_text(entry, "atom:summary") or None,
            authors=authors,
            year=int(published_at[:4]) if published_at else None,
            published_at=published_at,
            venue=journal_ref,
            doi=doi,
            arxiv_id=arxiv_id,
            url="https://arxiv.org/abs/{}".format(arxiv_id),
            metadata={
                "categories": categories,
                "updated": updated,
                "journal_ref": journal_ref,
            },
        )
    except (ValidationError, ValueError) as error:
        raise ProviderResponseError("arxiv", "entry metadata is invalid") from error


def _element_text(parent: ET.Element, path: str) -> str:
    value = parent.findtext(path, namespaces=_NAMESPACES)
    return " ".join(value.split()) if value else ""


def _integer_text(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
