from datetime import datetime, timezone
from hashlib import sha256
import re

import pytest

from backend.app.db.connection import connect_database
from backend.app.repositories.pdf_corpus_repository import PdfCorpusRepository
from backend.app.services.pdf_corpus_service import PdfCorpusService


def test_pdf_corpus_extracts_once_and_reuses_matching_hash(tmp_path):
    connection = connect_database(":memory:")
    _write_source_and_pdf(tmp_path, b"first pdf bytes")
    calls = []
    text = "Reusable research text. " * 8
    service = PdfCorpusService(
        tmp_path,
        PdfCorpusRepository(connection),
        extractor=lambda payload: calls.append(payload) or text,
        clock=_clock,
    )

    first = service.ensure("sample-paper")
    second = service.ensure("sample-paper")

    assert first.status == "ready"
    assert first.pdf_hash == sha256(b"first pdf bytes").hexdigest()
    normalized_text = " ".join(text.split())
    assert first.text_hash == sha256(normalized_text.encode("utf-8")).hexdigest()
    assert second == first
    assert calls == [b"first pdf bytes"]
    connection.close()


def test_lightweight_corpus_state_reads_never_select_extracted_text(tmp_path):
    connection = connect_database(":memory:")
    _write_source_and_pdf(tmp_path, b"source bytes")
    repository = PdfCorpusRepository(connection)
    service = PdfCorpusService(
        tmp_path,
        repository,
        extractor=lambda _payload: "Extracted research text. " * 10,
        clock=_clock,
    )
    service.ensure("sample-paper")
    statements = []
    connection.set_trace_callback(statements.append)

    one = service.get_state("sample-paper")
    many = service.list_states(["sample-paper", "missing", "sample-paper"])

    state_queries = [
        statement.lower()
        for statement in statements
        if "from pdf_corpus" in statement.lower()
    ]
    assert len(state_queries) == 2
    assert all(
        not re.search(r"\btext\b", statement.split("from pdf_corpus")[0])
        for statement in state_queries
    )
    assert one is not None and one.status == "ready"
    assert one.text_hash is not None
    assert many["sample-paper"] == one
    assert "missing" not in many
    assert "text" not in one.model_dump()
    assert repository.get("sample-paper").text.startswith("Extracted research text.")
    connection.close()


def test_pdf_hash_and_extractor_version_refresh_lazily(tmp_path):
    connection = connect_database(":memory:")
    pdf_path = _write_source_and_pdf(tmp_path, b"first pdf bytes")
    calls = []

    def extract(payload):
        calls.append(payload)
        return ("Extracted text from " + payload.decode("ascii") + ". ") * 8

    repository = PdfCorpusRepository(connection)
    first_service = PdfCorpusService(tmp_path, repository, extract, "extractor-1", _clock)
    first = first_service.ensure("sample-paper")
    pdf_path.write_bytes(b"second pdf bytes")
    second = first_service.ensure("sample-paper")
    upgraded_service = PdfCorpusService(tmp_path, repository, extract, "extractor-2", _clock)
    refreshed = upgraded_service.ensure("sample-paper")

    assert first.pdf_hash != second.pdf_hash
    assert second.extractor_version == "extractor-1"
    assert refreshed.extractor_version == "extractor-2"
    assert calls == [b"first pdf bytes", b"second pdf bytes", b"second pdf bytes"]
    connection.close()


def test_empty_pdf_is_unavailable_and_cached(tmp_path):
    connection = connect_database(":memory:")
    _write_source_and_pdf(tmp_path, b"scanned PDF")
    calls = []
    service = PdfCorpusService(
        tmp_path,
        PdfCorpusRepository(connection),
        extractor=lambda payload: calls.append(payload) or "  \n",
        clock=_clock,
    )

    first = service.ensure("sample-paper")
    second = service.ensure("sample-paper")

    assert first.status == "unavailable"
    assert "too little extractable text" in first.error_message
    assert second == first
    assert len(calls) == 1
    connection.close()


def test_failed_extraction_can_be_retried(tmp_path):
    connection = connect_database(":memory:")
    _write_source_and_pdf(tmp_path, b"retryable PDF")
    calls = []

    def extract(_payload):
        calls.append("call")
        if len(calls) == 1:
            raise RuntimeError("temporary parser failure")
        return "Recovered text. " * 10

    service = PdfCorpusService(
        tmp_path,
        PdfCorpusRepository(connection),
        extractor=extract,
        clock=_clock,
    )

    failed = service.ensure("sample-paper")
    retried = service.ensure("sample-paper")

    assert failed.status == "failed"
    assert retried.status == "ready"
    assert calls == ["call", "call"]
    connection.close()


def test_pdf_attachment_must_match_source_and_stay_under_papers(tmp_path):
    connection = connect_database(":memory:")
    _write_source_and_pdf(tmp_path, b"source bytes")
    source_path = tmp_path / "knowledge" / "sources" / "sample-paper.yaml"
    source_path.write_text(
        "schema_version: 1\nid: sample-paper\ntype: paper\ntitle: Example\n"
        "attachments:\n  local_pdf: storage://papers/other-paper.pdf\n",
        encoding="utf-8",
    )
    service = PdfCorpusService(
        tmp_path,
        PdfCorpusRepository(connection),
        extractor=lambda _payload: "text " * 100,
        clock=_clock,
    )

    with pytest.raises(ValueError, match="must match"):
        service.ensure("sample-paper")
    connection.close()


def _write_source_and_pdf(root, payload):
    source_dir = root / "knowledge" / "sources"
    papers_dir = root / "storage" / "papers"
    source_dir.mkdir(parents=True, exist_ok=True)
    papers_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "sample-paper.yaml").write_text(
        "schema_version: 1\nid: sample-paper\ntype: paper\ntitle: Example\n"
        "attachments:\n  local_pdf: storage://papers/sample-paper.pdf\n",
        encoding="utf-8",
    )
    pdf_path = papers_dir / "sample-paper.pdf"
    pdf_path.write_bytes(payload)
    return pdf_path


def _clock():
    return datetime(2026, 10, 7, tzinfo=timezone.utc)
