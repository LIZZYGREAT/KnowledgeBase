from typing import Literal

from pydantic import Field

from .common import CanonicalEntity, ExternalArtifact


class DocumentMetadata(CanonicalEntity):
    type: Literal["paper-note", "learning-note", "course-note"]
    external_artifacts: list[ExternalArtifact] = Field(default_factory=list)
