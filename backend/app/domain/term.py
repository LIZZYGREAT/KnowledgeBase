from typing import Literal

from pydantic import Field, constr

from .common import CanonicalEntity


class TermMetadata(CanonicalEntity):
    type: Literal["concept", "vocabulary"]
    depth: Literal["stub", "standard", "deep"]
    aliases: list[constr(strict=True, strip_whitespace=True, min_length=1)] = Field(
        default_factory=list
    )
