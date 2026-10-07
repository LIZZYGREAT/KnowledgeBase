"""Extract normal text PDFs on demand and reuse their Runtime Corpus text."""

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from typing import Callable, Optional

from backend.app.domain.pdf_corpus import PdfCorpusRecord
from backend.app.repositories.pdf_corpus_repository import PdfCorpusRepository
from backend.app.services.markdown_parser import parse_yaml
from backend.app.domain.source import SourceMetadata


EXTRACTOR_VERSION = "pypdf-text-v1"
MIN_EXTRACTED_TEXT_CHARS = 80
_LOCAL_PDF_PATTERN = re.compile(r"^storage://papers/([a-z0-9]+(?:-[a-z0-9]+)*)\.pdf$")


class PdfCorpusService:
    def __init__(
        self,
        repository_root: Path,
        repository: PdfCorpusRepository,
        extractor: Optional[Callable[[bytes], str]] = None,
        extractor_version: str = EXTRACTOR_VERSION,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.repository_root = Path(repository_root).resolve()
        self.repository = repository
        self.extractor = extractor or _extract_pdf_text
        self.extractor_version = extractor_version
        self.clock = clock

    def get(self, source_id: str) -> Optional[PdfCorpusRecord]:
        return self.repository.get(source_id)

    def ensure(self, source_id: str) -> PdfCorpusRecord:
        """Return current corpus text, extracting only when requested and stale."""
        source_path = self._source_path(source_id)
        if source_path is None:
            return self._save_unavailable(source_id, "Source has no local PDF attachment")
        pdf_path = self._pdf_path(source_id, source_path)
        if pdf_path is None or not pdf_path.is_file():
            return self._save_unavailable(source_id, "Local PDF attachment is missing")

        try:
            payload = pdf_path.read_bytes()
        except OSError as error:
            return self._save_failed(source_id, "Could not read local PDF: {}".format(error))

        pdf_hash = sha256(payload).hexdigest()
        current = self.repository.get(source_id)
        if (
            current is not None
            and current.pdf_hash == pdf_hash
            and current.extractor_version == self.extractor_version
            and current.status in {"ready", "unavailable"}
        ):
            return current

        now = self._now()
        pending = PdfCorpusRecord(
            source_id=source_id,
            pdf_hash=pdf_hash,
            extractor_version=self.extractor_version,
            status="pending",
            updated_at=now,
        )
        self.repository.save(pending)
        try:
            text = self.extractor(payload)
        except Exception as error:
            failed = PdfCorpusRecord(
                source_id=source_id,
                pdf_hash=pdf_hash,
                extractor_version=self.extractor_version,
                status="failed",
                error_message="PDF text extraction failed: {}".format(str(error)[:400]),
                updated_at=self._now(),
            )
            self.repository.save(failed)
            return failed

        normalized_text = _normalize_extracted_text(text)
        if len(normalized_text) < MIN_EXTRACTED_TEXT_CHARS:
            unavailable = PdfCorpusRecord(
                source_id=source_id,
                pdf_hash=pdf_hash,
                extractor_version=self.extractor_version,
                status="unavailable",
                error_message="PDF has too little extractable text for Term Discovery",
                extracted_at=self._now(),
                updated_at=self._now(),
            )
            self.repository.save(unavailable)
            return unavailable

        ready = PdfCorpusRecord(
            source_id=source_id,
            pdf_hash=pdf_hash,
            extractor_version=self.extractor_version,
            text_hash=sha256(normalized_text.encode("utf-8")).hexdigest(),
            text=normalized_text,
            status="ready",
            extracted_at=self._now(),
            updated_at=self._now(),
        )
        self.repository.save(ready)
        return ready

    def _source_path(self, source_id: str) -> Optional[Path]:
        path = (self.repository_root / "knowledge" / "sources" / (source_id + ".yaml")).resolve()
        root = (self.repository_root / "knowledge" / "sources").resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise LookupError("Canonical Source '{}' does not exist".format(source_id))
        metadata = SourceMetadata.model_validate(parse_yaml(path.read_text(encoding="utf-8")))
        if metadata.id != source_id:
            raise ValueError("Canonical Source id does not match the requested id")
        return path if metadata.attachments.local_pdf else None

    def _pdf_path(self, source_id: str, source_path: Path) -> Optional[Path]:
        metadata = SourceMetadata.model_validate(parse_yaml(source_path.read_text(encoding="utf-8")))
        attachment = metadata.attachments.local_pdf
        if attachment is None:
            return None
        match = _LOCAL_PDF_PATTERN.fullmatch(attachment)
        if match is None or match.group(1) != source_id:
            raise ValueError("Source PDF attachment must match storage://papers/<source-id>.pdf")
        papers_root = (self.repository_root / "storage" / "papers").resolve()
        path = (papers_root / (source_id + ".pdf")).resolve()
        if not path.is_relative_to(papers_root):
            raise ValueError("Source PDF attachment escapes storage/papers")
        return path

    def _save_unavailable(self, source_id: str, message: str) -> PdfCorpusRecord:
        current = self.repository.get(source_id)
        # Missing files are checked on each request, so a later import can recover
        # without requiring a schema or database reset.
        record = PdfCorpusRecord(
            source_id=source_id,
            pdf_hash=current.pdf_hash if current else "missing",
            extractor_version=self.extractor_version,
            status="unavailable",
            error_message=message,
            updated_at=self._now(),
        )
        self.repository.save(record)
        return record

    def _save_failed(self, source_id: str, message: str) -> PdfCorpusRecord:
        current = self.repository.get(source_id)
        record = PdfCorpusRecord(
            source_id=source_id,
            pdf_hash=current.pdf_hash if current else "unreadable",
            extractor_version=self.extractor_version,
            status="failed",
            error_message=message,
            updated_at=self._now(),
        )
        self.repository.save(record)
        return record

    def _now(self) -> str:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("PDF Corpus clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _extract_pdf_text(payload: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError("pypdf is required for PDF text extraction") from error
    reader = PdfReader(BytesIO(payload), strict=False)
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _normalize_extracted_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("PDF extractor must return text")
    value = value.replace("\x00", " ")
    return "\n".join(" ".join(line.split()) for line in value.splitlines()).strip()
