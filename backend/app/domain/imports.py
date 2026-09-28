"""Runtime-only Import Job and Import Item records."""

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


ImportJobStatus = Literal["staging", "ready", "failed"]
ImportFileType = Literal["markdown", "pdf"]
ImportItemStatus = Literal[
    "ready", "needs_review", "duplicate", "drafted", "confirmed", "failed"
]


@dataclass(frozen=True)
class ImportJob:
    id: str
    status: ImportJobStatus
    profile: str
    created_at: str
    updated_at: str
    error_message: Optional[str]


@dataclass(frozen=True)
class ImportItem:
    id: str
    job_id: str
    path: str
    file_type: ImportFileType
    sha256: str
    status: ImportItemStatus
    detected_entity_type: Optional[str]
    metadata: Dict[str, Any]
