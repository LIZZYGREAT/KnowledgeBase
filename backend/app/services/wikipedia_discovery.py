"""Small, bounded Wikipedia search adapter for Term Discovery."""

from dataclasses import dataclass
from html.parser import HTMLParser
import json
from typing import Callable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
MAX_RESULTS = 2
MAX_QUERY_CHARS = 180
MAX_RESPONSE_BYTES = 128_000
MAX_TITLE_CHARS = 200
MAX_SNIPPET_CHARS = 600


@dataclass(frozen=True)
class ExternalDiscoveryResult:
    url: str
    title: str
    snippet: str


class WikipediaDiscovery:
    def __init__(
        self,
        opener: Callable = urlopen,
        timeout_seconds: float = 8,
    ):
        self.opener = opener
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, limit: int = MAX_RESULTS) -> list[ExternalDiscoveryResult]:
        if not isinstance(query, str) or not query.strip():
            return []
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Wikipedia result limit must be a positive integer")
        bounded_limit = min(limit, MAX_RESULTS)
        params = urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": query.strip()[:MAX_QUERY_CHARS],
                "srnamespace": 0,
                "srlimit": bounded_limit,
                "format": "json",
                "utf8": 1,
            }
        )
        request = Request(
            "{}?{}".format(WIKIPEDIA_API, params),
            headers={
                "Accept": "application/json",
                "User-Agent": "KnowledgeBase-TermDiscovery/1.0 (bounded opt-in lookup)",
            },
            method="GET",
        )
        with self.opener(request, timeout=self.timeout_seconds) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Wikipedia search response exceeded the size limit")
        payload = json.loads(body.decode("utf-8"))
        entries = payload.get("query", {}).get("search", [])
        results = []
        for entry in entries[:bounded_limit]:
            if not isinstance(entry, dict):
                continue
            title = " ".join(str(entry.get("title", "")).split())[:MAX_TITLE_CHARS]
            snippet = _plain_text(str(entry.get("snippet", "")))[:MAX_SNIPPET_CHARS]
            if not title or not snippet:
                continue
            page = quote(title.replace(" ", "_"), safe="()!,")
            results.append(
                ExternalDiscoveryResult(
                    url="https://en.wikipedia.org/wiki/{}".format(page),
                    title=title,
                    snippet=snippet,
                )
            )
        return results


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _plain_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return " ".join(" ".join(parser.parts).split())
