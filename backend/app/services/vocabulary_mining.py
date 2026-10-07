"""Deterministic, per-source vocabulary statistics for research PDFs."""

from collections import Counter
import re


_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)*")
_STOPWORDS = frozenset(
    "a an and are as at be been being but by can could did do does for from had has have "
    "he her here hers him his how i if in into is it its may might more most must my no nor "
    "not of off on once only or other our out over own same she should so some such than that "
    "the their theirs them then there these they this those through to too under until up us "
    "very was we were what when where which while who why will with would you your".split()
)
_LOW_VALUE = frozenset(
    "accuracy algorithm architecture baseline benchmark data dataset experiment experiments "
    "framework hardware model models method methods paper performance result results setup "
    "system systems task tasks training work".split()
)


def mine_vocabulary(text: str) -> dict[str, tuple[str, int]]:
    """Count domain-shaped words and short phrases without consulting an AI model."""
    tokens = _TOKEN.findall(text)
    counts: Counter[str] = Counter()
    displays: dict[str, str] = {}
    normalized = [token.casefold() for token in tokens]
    for index, token in enumerate(tokens):
        key = token.casefold()
        if _useful_word(key):
            counts[key] += 1
            displays.setdefault(key, token)
        for width in (2, 3):
            if index + width > len(tokens):
                continue
            phrase_tokens = normalized[index : index + width]
            if any(item in _STOPWORDS or item in _LOW_VALUE for item in phrase_tokens):
                continue
            phrase = " ".join(phrase_tokens)
            if len(phrase) < 10:
                continue
            counts[phrase] += 1
            displays.setdefault(phrase, " ".join(tokens[index : index + width]))
    return {
        term: (displays[term], count)
        for term, count in sorted(counts.items())
        if term not in _STOPWORDS and term not in _LOW_VALUE
    }


def _useful_word(value: str) -> bool:
    if value in _STOPWORDS or value in _LOW_VALUE:
        return False
    if "-" in value or "'" in value:
        return len(value) >= 7
    return len(value) >= 5
