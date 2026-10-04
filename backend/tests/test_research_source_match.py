import pytest

from backend.app.domain.research_runtime import ResearchWorkRecord
from backend.app.domain.source import SourceMetadata
from backend.app.services.research_source_match import find_matching_source


@pytest.mark.parametrize(
    ("field", "work_identifier", "source_identifier"),
    [
        ("doi", "https://doi.org/10.1234/ABC", "doi:10.1234/abc"),
        (
            "arxiv_id",
            "https://arxiv.org/abs/2401.12345v2",
            "2401.12345",
        ),
        (
            "openalex_id",
            "W1234567890",
            "https://openalex.org/W1234567890/",
        ),
    ],
)
def test_find_matching_source_uses_normalized_identifiers(
    field, work_identifier, source_identifier
):
    work = _work(**{field: work_identifier})
    source = _source(**{field: source_identifier})

    result = find_matching_source((source,), work)

    assert result.source is source
    assert result.ambiguous is False


def test_find_matching_source_uses_title_author_and_year_with_one_year_tolerance():
    work = _work(title="A Study: on Research", authors=("Ada Lovelace",), year=2026)
    source = _source(
        title="a study on research!", authors=("Ada Lovelace",), year=2025
    )

    result = find_matching_source((source,), work)

    assert result.source is source
    assert result.ambiguous is False


@pytest.mark.parametrize(
    ("title", "authors", "year"),
    [
        ("A Study on Research", ("Ada Lovelace",), 2024),
        ("A Study on Research", ("Grace Hopper",), 2026),
        ("A Different Study", ("Ada Lovelace",), 2026),
    ],
)
def test_find_matching_source_rejects_weak_identity_mismatches(title, authors, year):
    work = _work(title="A Study on Research", authors=("Ada Lovelace",), year=2026)
    source = _source(title=title, authors=authors, year=year)

    result = find_matching_source((source,), work)

    assert result.source is None
    assert result.ambiguous is False


@pytest.mark.parametrize(
    ("field", "work_identifier", "source_identifier"),
    [
        ("doi", "10.1234/work-a", "10.1234/work-b"),
        ("arxiv_id", "2401.12345", "2401.99999"),
    ],
)
def test_weak_identity_does_not_override_conflicting_strong_identifiers(
    field, work_identifier, source_identifier
):
    work = _work(
        title="Same Research Paper",
        authors=("Ada Lovelace",),
        year=2026,
        **{field: work_identifier},
    )
    source = _source(
        title="Same Research Paper",
        authors=("Ada Lovelace",),
        year=2026,
        **{field: source_identifier},
    )

    result = find_matching_source((source,), work)

    assert result.source is None
    assert result.ambiguous is False


def test_strong_identifiers_pointing_to_different_sources_are_ambiguous():
    work = _work(doi="10.1234/work", arxiv_id="2401.12345")
    doi_source = _source(source_id="doi-source", doi="10.1234/work")
    arxiv_source = _source(source_id="arxiv-source", arxiv_id="2401.12345")

    result = find_matching_source((doi_source, arxiv_source), work)

    assert result.source is None
    assert result.ambiguous is True
    assert [(item.id, item.matched_by) for item in result.candidates] == [
        ("arxiv-source", ("arxiv_id",)),
        ("doi-source", ("doi",)),
    ]


def test_multiple_weak_source_candidates_are_ambiguous():
    work = _work(title="Same Research Paper", authors=("Ada Lovelace",), year=2026)
    first = _source(
        source_id="first-source",
        title="Same Research Paper",
        authors=("Ada Lovelace",),
        year=2025,
    )
    second = _source(
        source_id="second-source",
        title="Same Research Paper",
        authors=("Ada Lovelace",),
        year=2026,
    )

    result = find_matching_source((first, second), work)

    assert result.source is None
    assert result.ambiguous is True
    assert [(item.id, item.title, item.matched_by) for item in result.candidates] == [
        ("first-source", "Same Research Paper", ("title_author_year",)),
        ("second-source", "Same Research Paper", ("title_author_year",)),
    ]


def _work(**overrides):
    values = {
        "id": "work-1",
        "canonical_key": "doi:10.1234/work",
        "title": "Research Work",
        "normalized_title": "research work",
        "authors": ("Grace Hopper",),
        "year": 2026,
        "created_at": "2026-10-03T12:00:00+00:00",
        "updated_at": "2026-10-03T12:00:00+00:00",
    }
    values.update(overrides)
    return ResearchWorkRecord.model_validate(values)


def _source(
    source_id="source-1",
    title="Unrelated Source",
    authors=("Another Author",),
    year=2020,
    doi=None,
    arxiv_id=None,
    openalex_id=None,
):
    return SourceMetadata.model_validate(
        {
            "schema_version": 1,
            "id": source_id,
            "type": "paper",
            "title": title,
            "authors": list(authors),
            "year": year,
            "identifiers": {
                "doi": doi,
                "arxiv_id": arxiv_id,
                "openalex_id": openalex_id,
            },
        }
    )
