"""Shared deterministic matching primitives for canonical registries."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Literal, Mapping, Optional, Sequence, Union
import re
import unicodedata


MatchKind = Literal["exact", "title", "alias", "identifier", "normalized", "fuzzy"]
ResolutionStatus = Literal["resolved", "ambiguous", "unresolved"]

_FUZZY_CANDIDATE_THRESHOLD = 0.78


@dataclass(frozen=True)
class RegistryEntry:
    id: str
    title: str
    aliases: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolutionCandidate:
    id: str
    title: str
    matched_by: MatchKind
    score: float = 1.0


@dataclass(frozen=True)
class Resolution:
    query: str
    status: ResolutionStatus
    matched_by: Optional[MatchKind]
    candidates: tuple[ResolutionCandidate, ...] = ()

    @property
    def entity_id(self) -> Optional[str]:
        if self.status == "resolved" and self.candidates:
            return self.candidates[0].id
        return None


def normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def resolve_entry(
    query: str,
    entries: Sequence[RegistryEntry],
    normalized_aliases: Optional[Mapping[str, tuple[str, ...]]] = None,
) -> Resolution:
    """Resolve exact values first; fuzzy matches are suggestions only."""
    query = query.strip()
    if not query:
        return Resolution(query, "unresolved", None)

    stages: tuple[
        tuple[MatchKind, Callable[[RegistryEntry], Union[str, tuple[str, ...]]]], ...
    ] = (
        ("exact", lambda entry: entry.id),
        ("title", lambda entry: entry.title),
        ("alias", lambda entry: entry.aliases),
        ("identifier", lambda entry: entry.identifiers),
    )
    for match_kind, values_for in stages:
        matches = _matching_entries(query, entries, values_for)
        if matches:
            return _result(query, match_kind, matches)

    normalized_query = normalize_key(query)
    if not normalized_query:
        return Resolution(query, "unresolved", None)

    normalized_matches = []
    alias_ids = set((normalized_aliases or {}).get(normalized_query, ()))
    for entry in entries:
        values = (entry.id, entry.title, *entry.identifiers)
        aliases_match = (
            entry.id in alias_ids
            if normalized_aliases is not None
            else any(normalize_key(alias) == normalized_query for alias in entry.aliases)
        )
        if aliases_match or any(normalize_key(value) == normalized_query for value in values):
            normalized_matches.append(entry)
    if normalized_matches:
        return _result(query, "normalized", normalized_matches)

    scored = []
    for entry in entries:
        values = (entry.id, entry.title, *entry.aliases, *entry.identifiers)
        score = max(
            (SequenceMatcher(None, normalized_query, normalize_key(value)).ratio() for value in values),
            default=0.0,
        )
        if score >= _FUZZY_CANDIDATE_THRESHOLD:
            scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], item[1].id))
    candidates = tuple(
        ResolutionCandidate(entry.id, entry.title, "fuzzy", round(score, 4))
        for score, entry in scored[:5]
    )
    return Resolution(query, "unresolved", "fuzzy" if candidates else None, candidates)


def _matching_entries(query, entries, values_for):
    return [entry for entry in entries if _contains(values_for(entry), query)]


def _contains(values, query):
    if isinstance(values, str):
        return values == query
    return any(value == query for value in values)


def _result(query, matched_by, entries):
    unique = {entry.id: entry for entry in entries}
    ordered = sorted(unique.values(), key=lambda entry: entry.id)
    candidates = tuple(
        ResolutionCandidate(entry.id, entry.title, matched_by)
        for entry in ordered
    )
    status = "resolved" if len(candidates) == 1 else "ambiguous"
    return Resolution(query, status, matched_by, candidates)
