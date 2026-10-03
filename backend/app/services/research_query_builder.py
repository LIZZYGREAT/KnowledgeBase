"""Build stable, independent searches from enabled Research Profile lenses."""

from dataclasses import dataclass
import hashlib
import unicodedata
from typing import Mapping, Optional, Sequence

from backend.app.domain.research import ResearchProfile


@dataclass(frozen=True)
class ResearchQuery:
    profile_id: str
    lens_id: str
    lens_title: str
    text: str
    normalized_text: str
    query_key: str
    priority: str
    include_terms: tuple[str, ...]
    exclude_terms: tuple[str, ...]
    profile_exclude_terms: tuple[str, ...]


class ResearchQueryBuilder:
    def build(
        self,
        profile: ResearchProfile,
        lens_overrides: Optional[Mapping[str, bool]] = None,
        additional_queries: Sequence[str] = (),
        additional_query_lens: Optional[str] = None,
    ) -> tuple[ResearchQuery, ...]:
        overrides = dict(lens_overrides or {})
        if any(
            not isinstance(lens_id, str) or not isinstance(enabled, bool)
            for lens_id, enabled in overrides.items()
        ):
            raise ValueError("Lens overrides must map known IDs to boolean values")
        known_lens_ids = {lens.id for lens in profile.lenses}
        unknown_ids = sorted(set(overrides) - known_lens_ids)
        if unknown_ids:
            raise ValueError(
                "Unknown Research Lens override(s): {}".format(", ".join(unknown_ids))
            )
        queries = []
        emitted_keys = set()
        for lens in profile.lenses:
            enabled = overrides.get(lens.id, lens.enabled)
            if not enabled:
                continue
            for text in lens.queries:
                normalized_text = normalize_query(text)
                if not normalized_text:
                    raise ValueError(
                        "Research Lens '{}' contains a query with no searchable text".format(
                            lens.id
                        )
                    )
                query_key = hashlib.sha256(
                    "\0".join((profile.id, lens.id, normalized_text)).encode("utf-8")
                ).hexdigest()
                if query_key in emitted_keys:
                    raise ValueError(
                        "Research Lens '{}' repeats a query after normalization".format(
                            lens.id
                        )
                    )
                emitted_keys.add(query_key)
                queries.append(
                    ResearchQuery(
                        profile_id=profile.id,
                        lens_id=lens.id,
                        lens_title=lens.title,
                        text=text.strip(),
                        normalized_text=normalized_text,
                        query_key=query_key,
                        priority=lens.priority,
                        include_terms=tuple(lens.include_terms),
                        exclude_terms=tuple(lens.exclude_terms),
                        profile_exclude_terms=tuple(profile.exclude_terms),
                    )
                )
        if additional_queries:
            selected_lenses = [
                lens
                for lens in profile.lenses
                if overrides.get(lens.id, lens.enabled)
            ]
            if not selected_lenses:
                raise ValueError("Additional Research queries require at least one selected Lens")
            if additional_query_lens is None:
                if len(selected_lenses) > 1:
                    raise ValueError(
                        "Additional Research queries require an explicit Lens when multiple Lenses are selected"
                    )
                lens = selected_lenses[0]
            else:
                lens = next(
                    (item for item in selected_lenses if item.id == additional_query_lens),
                    None,
                )
                if lens is None:
                    raise ValueError(
                        "Additional Research query Lens must be one of the selected Lenses"
                    )
            for text in additional_queries:
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("Additional Research queries must be non-empty text")
                normalized_text = normalize_query(text)
                query_key = hashlib.sha256(
                    "\0".join((profile.id, lens.id, normalized_text)).encode("utf-8")
                ).hexdigest()
                if query_key in emitted_keys:
                    raise ValueError("Research Run contains a duplicate query")
                emitted_keys.add(query_key)
                queries.append(
                    ResearchQuery(
                        profile_id=profile.id,
                        lens_id=lens.id,
                        lens_title=lens.title,
                        text=text.strip(),
                        normalized_text=normalized_text,
                        query_key=query_key,
                        priority=lens.priority,
                        include_terms=tuple(lens.include_terms),
                        exclude_terms=tuple(lens.exclude_terms),
                        profile_exclude_terms=tuple(profile.exclude_terms),
                    )
                )
        return tuple(queries)


def normalize_query(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())
