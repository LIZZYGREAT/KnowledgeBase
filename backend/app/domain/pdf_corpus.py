"""Runtime PDF Corpus state; extracted text is derived and rebuildable."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, constr


NonEmptyText = constr(strict=True, strip_whitespace=True, min_length=1)


class PdfCorpusRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_id: NonEmptyText
    pdf_hash: NonEmptyText
    extractor_version: NonEmptyText
    text_hash: Optional[NonEmptyText] = None
    text: Optional[str] = None
    status: Literal["pending", "ready", "unavailable", "failed"]
    extracted_at: Optional[NonEmptyText] = None
    error_message: Optional[str] = None
    updated_at: NonEmptyText
