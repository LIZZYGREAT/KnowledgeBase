from datetime import datetime, timezone
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from backend.app.domain.research_runtime import ResearchWorkRecord
from backend.app.services.research_providers import (
    ArxivProvider,
    CrossrefProvider,
    OpenAlexProvider,
    ProviderResponseError,
    ResearchHttpClient,
    ResearchProviderError,
)


_FIXTURES = Path(__file__).parent / "fixtures" / "research"
_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
_END = datetime(2024, 2, 1, tzinfo=timezone.utc)


def test_arxiv_adapter_parses_atom_and_removes_version_from_work_identifier():
    client = _FakeClient(_fixture_bytes("arxiv.atom.xml"))
    page = ArxivProvider(client=client).search(
        "continual learning", _START, _END
    )

    assert len(page.works) == 1
    work = page.works[0]
    assert work.provider == "arxiv"
    assert work.provider_record_id == "2401.12345v2"
    assert work.arxiv_id == "2401.12345"
    assert work.doi == "10.1000/xyz123"
    assert work.year == 2024
    assert work.authors == ("Ada Lovelace", "Alan Turing")
    assert work.metadata["categories"] == ["cs.LG"]
    assert page.total_count == 1
    assert page.next_cursor is None

    parameters = _query_parameters(client.urls[0])
    search_query = parameters["search_query"][0]
    assert 'all:"continual learning"' in search_query
    assert "submittedDate:[202401010000 TO 202402010000]" in search_query
    assert parameters["sortBy"] == ["submittedDate"]
    assert parameters["max_results"] == ["100"]


def test_arxiv_adapter_exposes_offset_cursor_for_another_page():
    body = _fixture_bytes("arxiv.atom.xml").replace(
        b"<opensearch:totalResults>1", b"<opensearch:totalResults>3"
    )
    client = _FakeClient(body)
    page = ArxivProvider(page_size=1, client=client).search(
        "continual learning", _START, _END, cursor="1"
    )

    assert page.next_cursor == "2"
    assert _query_parameters(client.urls[0])["start"] == ["1"]


def test_openalex_adapter_parses_abstract_index_and_cursor_envelope():
    client = _FakeClient(_fixture_bytes("openalex.json"))
    page = OpenAlexProvider(client=client).search("continual learning", _START, _END)

    work = page.works[0]
    assert work.provider == "openalex"
    assert work.provider_record_id == "W1234567890"
    assert work.openalex_id == "W1234567890"
    assert work.doi == "10.1000/xyz123"
    assert work.abstract == "Continual learning reduces forgetting."
    assert work.authors == ("Ada Lovelace", "Alan Turing")
    assert work.venue == "Journal of Learning"
    assert page.total_count == 1
    assert page.next_cursor is None

    parameters = _query_parameters(client.urls[0])
    assert parameters["search"] == ["continual learning"]
    assert parameters["filter"] == [
        "from_publication_date:2024-01-01,to_publication_date:2024-02-01"
    ]
    assert parameters["cursor"] == ["*"]
    assert parameters["per_page"] == ["100"]


def test_crossref_adapter_normalizes_record_and_pagination():
    body = _fixture_bytes("crossref.json").replace(
        b'"total-results": 1', b'"total-results": 2'
    )
    client = _FakeClient(body)
    page = CrossrefProvider(page_size=1, client=client).search(
        "continual learning", _START, _END
    )

    work = page.works[0]
    assert work.provider == "crossref"
    assert work.provider_record_id == "10.1000/xyz123"
    assert work.doi == "10.1000/xyz123"
    assert work.abstract == "A continual learning paper."
    assert work.authors == ("Ada Lovelace", "Alan Turing")
    assert work.published_at == "2024-05-08"
    assert work.year == 2024
    assert page.total_count == 2
    assert page.next_cursor == "1"

    parameters = _query_parameters(client.urls[0])
    assert parameters["query.bibliographic"] == ["continual learning"]
    assert parameters["filter"] == [
        "from-pub-date:2024-01-01,until-pub-date:2024-02-01"
    ]
    assert parameters["offset"] == ["0"]


def test_openalex_enrichment_fetches_one_work_by_provider_id():
    payload = json.loads(_fixture_bytes("openalex.json"))
    client = _FakeClient(json.dumps(payload["results"][0]).encode("utf-8"))
    provider = OpenAlexProvider(client=client)
    work = _research_work(openalex_id="W1234567890")

    enriched = provider.enrich(work)

    assert enriched is not None
    assert enriched.provider == "openalex"
    assert enriched.openalex_id == "W1234567890"
    assert client.urls == ["https://api.openalex.org/works/W1234567890"]


def test_crossref_enrichment_fetches_one_work_by_escaped_doi():
    payload = json.loads(_fixture_bytes("crossref.json"))
    client = _FakeClient(
        json.dumps({"message": payload["message"]["items"][0]}).encode("utf-8")
    )
    provider = CrossrefProvider(client=client)
    work = _research_work(doi="10.1000/xyz123")

    enriched = provider.enrich(work)

    assert enriched is not None
    assert enriched.provider == "crossref"
    assert enriched.doi == "10.1000/xyz123"
    assert client.urls == ["https://api.crossref.org/works/10.1000%2Fxyz123"]


def test_enrichment_without_a_lookup_identifier_skips_the_provider_request():
    client = _FakeClient(b"{}")
    assert OpenAlexProvider(client=client).enrich(_research_work()) is None
    assert CrossrefProvider(client=client).enrich(_research_work()) is None
    assert client.urls == []


def test_http_client_retries_transient_status_with_timeout_and_bounded_delay():
    calls = []
    delays = []

    def opener(request, timeout):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise HTTPError(
                request.full_url,
                503,
                "unavailable",
                Message(),
                BytesIO(b"temporary"),
            )
        return _Response(b"ok")

    client = ResearchHttpClient(
        "openalex",
        timeout_seconds=7,
        max_retries=1,
        opener=opener,
        sleeper=delays.append,
    )

    assert client.get("https://example.test/works", "application/json") == b"ok"
    assert len(calls) == 2
    assert all(timeout == 7 for _, timeout in calls)
    assert delays == [0.25]


def test_http_client_respects_retry_after_for_rate_limited_requests():
    calls = []
    delays = []

    def opener(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            headers = Message()
            headers["Retry-After"] = "3"
            raise HTTPError(request.full_url, 429, "rate limited", headers, BytesIO())
        return _Response(b"ok")

    client = ResearchHttpClient(
        "openalex",
        max_retries=1,
        opener=opener,
        sleeper=delays.append,
    )

    assert client.get("https://example.test/works", "application/json") == b"ok"
    assert len(calls) == 2
    assert delays == [3.0]


def test_http_client_does_not_retry_nontransient_status():
    def opener(request, timeout):
        raise HTTPError(request.full_url, 400, "bad request", Message(), BytesIO())

    client = ResearchHttpClient("crossref", opener=opener, sleeper=lambda _: None)

    with pytest.raises(ResearchProviderError) as error:
        client.get("https://example.test/works", "application/json")
    assert error.value.status_code == 400
    assert error.value.retryable is False


def test_provider_adapters_reject_invalid_search_ranges_and_malformed_payloads():
    client = _FakeClient(b"not xml")
    with pytest.raises(ProviderResponseError, match="Atom XML"):
        ArxivProvider(client=client).search("topic", _START, _END)

    with pytest.raises(ValueError, match="timezone-aware"):
        OpenAlexProvider(client=_FakeClient(b"{} ")).search(
            "topic", datetime(2024, 1, 1), _END
        )

    with pytest.raises(ValueError, match="later than"):
        CrossrefProvider(client=_FakeClient(b"{} ")).search(
            "topic", _END, _START
        )


class _FakeClient:
    def __init__(self, body: bytes):
        self.body = body
        self.urls = []

    def get(self, url: str, accept: str) -> bytes:
        self.urls.append(url)
        return self.body

    def get_json(self, url: str) -> dict:
        self.urls.append(url)
        return json.loads(self.body)


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


def _fixture_bytes(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _research_work(doi=None, openalex_id=None):
    return ResearchWorkRecord(
        id="work-id",
        canonical_key="title:work:2024:author",
        title="A Work",
        normalized_title="a work",
        doi=doi,
        openalex_id=openalex_id,
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )


def _query_parameters(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)
