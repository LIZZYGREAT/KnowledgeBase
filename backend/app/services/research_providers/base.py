"""Shared provider result contract and bounded HTTP transport."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import isfinite
import json
import re
import threading
import time
from typing import Any, Callable, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.app.domain.common import NonEmptyText
from backend.app.domain.research import ResearchProvider as ResearchProviderName


class ProviderWork(BaseModel):
    """Provider-neutral subset of metadata needed by Research discovery."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ResearchProviderName
    provider_record_id: NonEmptyText
    title: NonEmptyText
    abstract: Optional[NonEmptyText] = None
    authors: tuple[NonEmptyText, ...] = ()
    year: Optional[StrictInt] = None
    published_at: Optional[NonEmptyText] = None
    venue: Optional[NonEmptyText] = None
    doi: Optional[NonEmptyText] = None
    arxiv_id: Optional[NonEmptyText] = None
    openalex_id: Optional[NonEmptyText] = None
    semantic_scholar_id: Optional[NonEmptyText] = None
    url: Optional[NonEmptyText] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    works: tuple[ProviderWork, ...]
    next_cursor: Optional[str] = None
    total_count: Optional[StrictInt] = None


class ResearchProvider(Protocol):
    """Common search contract; provider-specific response types stay in adapters."""

    name: ResearchProviderName

    def search(
        self,
        query: str,
        start_at: datetime,
        end_at: datetime,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> ProviderPage:
        ...


def effective_page_size(configured_size: int, requested_limit: Optional[int]) -> int:
    if requested_limit is None:
        return configured_size
    if (
        isinstance(requested_limit, bool)
        or not isinstance(requested_limit, int)
        or requested_limit < 1
    ):
        raise ValueError("Research Provider limit must be a positive integer")
    return min(configured_size, requested_limit)


class ResearchProviderError(RuntimeError):
    def __init__(
        self,
        provider: str,
        message: str,
        status_code: Optional[int] = None,
        retryable: bool = False,
    ):
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
        super().__init__("{}: {}".format(provider, message))


class ProviderResponseError(ResearchProviderError):
    """A provider returned a response that does not match its documented shape."""


class ResearchHttpClient:
    """GET-only transport with timeouts, bounded retries, and optional pacing."""

    def __init__(
        self,
        provider: str,
        timeout_seconds: float = 20,
        max_retries: int = 3,
        opener: Callable = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        minimum_interval_seconds: float = 0,
    ):
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("Provider timeout_seconds must be positive")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("Provider max_retries cannot be negative")
        if (
            isinstance(minimum_interval_seconds, bool)
            or not isinstance(minimum_interval_seconds, (int, float))
            or minimum_interval_seconds < 0
        ):
            raise ValueError("Provider minimum interval cannot be negative")
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.opener = opener
        self.sleeper = sleeper
        self.clock = clock
        self.minimum_interval_seconds = minimum_interval_seconds
        self._last_request_at: Optional[float] = None
        self._pace_lock = threading.Lock()

    def get(self, url: str, accept: str) -> bytes:
        request = Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": "KnowledgeBase-ResearchAgent/1.0",
            },
            method="GET",
        )
        for attempt in range(self.max_retries + 1):
            self._pace_request()
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    return response.read()
            except HTTPError as error:
                retryable = error.code in {408, 425, 429} or 500 <= error.code <= 599
                if retryable and attempt < self.max_retries:
                    delay = _retry_after_delay(error.headers)
                    self.sleeper(_retry_delay(attempt) if delay is None else delay)
                    continue
                raise ResearchProviderError(
                    self.provider,
                    "HTTP {}{}".format(
                        error.code, " after retries" if retryable else ""
                    ),
                    status_code=error.code,
                    retryable=retryable,
                ) from error
            except (TimeoutError, URLError, OSError) as error:
                if attempt < self.max_retries:
                    self.sleeper(_retry_delay(attempt))
                    continue
                raise ResearchProviderError(
                    self.provider,
                    "request failed after {} attempt(s)".format(attempt + 1),
                    retryable=True,
                ) from error
        raise ResearchProviderError(self.provider, "request did not complete")

    def get_json(self, url: str) -> dict[str, Any]:
        try:
            value = json.loads(self.get(url, "application/json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderResponseError(self.provider, "response was not valid JSON") from error
        if not isinstance(value, dict):
            raise ProviderResponseError(self.provider, "response must be a JSON object")
        return value

    def _pace_request(self) -> None:
        if self.minimum_interval_seconds == 0:
            return
        with self._pace_lock:
            now = self.clock()
            if self._last_request_at is not None:
                wait = self.minimum_interval_seconds - (now - self._last_request_at)
                if wait > 0:
                    self.sleeper(wait)
                    now = self.clock()
            self._last_request_at = now


def build_url(base_url: str, parameters: list[tuple[str, str]]) -> str:
    return "{}?{}".format(base_url, urlencode(parameters))


def validate_search_request(query: str, start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Research query must be non-empty text")
    if not isinstance(start_at, datetime) or not isinstance(end_at, datetime):
        raise ValueError("Research search range must use datetime values")
    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise ValueError("Research search start_at must be timezone-aware")
    if end_at.tzinfo is None or end_at.utcoffset() is None:
        raise ValueError("Research search end_at must be timezone-aware")
    start_utc = start_at.astimezone(timezone.utc)
    end_utc = end_at.astimezone(timezone.utc)
    if start_utc >= end_utc:
        raise ValueError("Research search end_at must be later than start_at")
    return start_utc, end_utc


def parse_nonnegative_cursor(cursor: Optional[str], provider: str) -> int:
    if cursor is None:
        return 0
    if not isinstance(cursor, str) or not re.fullmatch(r"[0-9]+", cursor):
        raise ValueError("{} cursor must be a non-negative integer".format(provider))
    return int(cursor)


def _retry_delay(attempt: int) -> float:
    return min(0.25 * (2**attempt), 2.0)


def _retry_after_delay(headers) -> Optional[float]:
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if isfinite(seconds) else None
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None or retry_at.utcoffset() is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        # HTTP-date values use wall time; the transport clock is monotonic and is
        # intentionally used only for request pacing.
        now = datetime.now(timezone.utc)
        return max(0.0, (retry_at.astimezone(timezone.utc) - now).total_seconds())
