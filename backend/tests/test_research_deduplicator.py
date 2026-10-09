from datetime import datetime, timezone

import pytest

from backend.app.db.connection import connect_database
from backend.app.repositories.research_repository import ResearchRepository
from backend.app.services.research_deduplicator import (
    ResearchDeduplicator,
    ResearchIdentityConflict,
    normalize_arxiv_id,
    normalize_doi,
    normalize_openalex_id,
    normalize_semantic_scholar_id,
    normalize_title,
)
from backend.app.services.research_providers.base import ProviderWork


_NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def test_normalizes_identifiers_and_titles_without_dropping_numbers():
    assert normalize_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_arxiv_id("https://arxiv.org/abs/2401.12345v2") == "2401.12345"
    assert normalize_openalex_id("https://openalex.org/W123456") == "w123456"
    assert (
        normalize_semantic_scholar_id(
            "https://www.semanticscholar.org/paper/Example/AbC123"
        )
        == "abc123"
    )
    assert normalize_title("Ａ Study: GPT-4, L₂!") == "a study gpt 4 l2"
    assert normalize_title("A Study: GPT-5, L₂!") != normalize_title(
        "A Study: GPT-4, L₂!"
    )


def test_arxiv_preprint_and_published_version_share_work_and_keep_provenance():
    connection, repository, deduplicator = _setup()
    try:
        preprint = deduplicator.record_discovery(
            "continual-learning",
            "replay",
            "query-a",
            "continual learning replay",
            _provider_work(
                provider="arxiv",
                provider_record_id="2401.12345v2",
                title="A Method for Continual Learning",
                authors=("Ada Lovelace",),
                year=2024,
                abstract="Preprint abstract.",
                arxiv_id="https://arxiv.org/abs/2401.12345v2",
                url="https://arxiv.org/abs/2401.12345v2",
                metadata={"categories": ["cs.LG"]},
            ),
        )

        published = deduplicator.record_discovery(
            "continual-learning",
            "replay",
            "query-b",
            "experience replay",
            _provider_work(
                provider="crossref",
                provider_record_id="10.1000/XYZ123",
                title="A Method for Continual Learning",
                authors=("Ada Lovelace", "Alan Turing"),
                year=2024,
                abstract="Published abstract.",
                doi="https://doi.org/10.1000/XYZ123",
                venue="Journal of Learning",
                url="https://doi.org/10.1000/XYZ123",
                metadata={"type": "journal-article"},
            ),
        )

        assert preprint.created_work is True
        assert published.created_work is False
        assert published.match_method == "title_author_year"
        assert published.work.id == preprint.work.id
        assert published.work.canonical_key == "doi:10.1000/xyz123"
        assert published.work.doi == "10.1000/xyz123"
        assert published.work.arxiv_id == "2401.12345"
        assert published.work.title == "A Method for Continual Learning"
        assert published.work.abstract == "Published abstract."
        assert published.work.venue == "Journal of Learning"
        assert published.work.url == "https://doi.org/10.1000/XYZ123"

        discoveries = repository.list_discoveries_for_work(preprint.work.id)
        assert len(discoveries) == 2
        assert {item.provider for item in discoveries} == {"arxiv", "crossref"}
        arxiv_discovery = next(item for item in discoveries if item.provider == "arxiv")
        assert arxiv_discovery.metadata["url"] == "https://arxiv.org/abs/2401.12345v2"
        assert arxiv_discovery.metadata["provider_metadata"] == {"categories": ["cs.LG"]}
    finally:
        connection.close()


def test_strong_doi_match_precedes_title_and_updates_to_preferred_metadata():
    connection, _, deduplicator = _setup()
    try:
        first = deduplicator.record_discovery(
            "continual-learning",
            "replay",
            "query-a",
            "first query",
            _provider_work(
                provider="arxiv",
                provider_record_id="2401.12345v1",
                title="Old title",
                authors=("Ada Lovelace",),
                year=2024,
                doi="doi:10.1000/XYZ123",
                abstract="Older metadata.",
            ),
        )
        second = deduplicator.record_discovery(
            "continual-learning",
            "replay",
            "query-b",
            "second query",
            _provider_work(
                provider="crossref",
                provider_record_id="10.1000/xyz123",
                title="Corrected published title",
                authors=("Ada Lovelace",),
                year=2024,
                doi="https://doi.org/10.1000/xyz123",
                abstract="Preferred publication metadata.",
            ),
        )

        assert second.created_work is False
        assert second.match_method == "doi"
        assert second.work.id == first.work.id
        assert second.work.title == "Corrected published title"
        assert second.work.abstract == "Preferred publication metadata."
    finally:
        connection.close()


def test_weak_matching_requires_same_first_author_and_year_within_one():
    connection, _, deduplicator = _setup()
    try:
        original = _record(
            deduplicator,
            _provider_work(
                "arxiv", "arxiv-1", "A Method for Continual Learning", ("Ada Lovelace",), 2024
            ),
            "query-a",
        )
        different_author = _record(
            deduplicator,
            _provider_work(
                "crossref", "doi-2", "A Method for Continual Learning", ("Alan Turing",), 2024
            ),
            "query-b",
        )
        different_year = _record(
            deduplicator,
            _provider_work(
                "openalex", "openalex-3", "A Method for Continual Learning", ("Ada Lovelace",), 2027
            ),
            "query-c",
        )

        assert different_author.created_work is True
        assert different_year.created_work is True
        assert len({original.work.id, different_author.work.id, different_year.work.id}) == 3
    finally:
        connection.close()


def test_weak_matching_rejects_conflicting_identifiers_and_ambiguous_candidates():
    connection, _, deduplicator = _setup()
    try:
        first = _record(
            deduplicator,
            _provider_work(
                "crossref",
                "doi-a",
                "A Method for Continual Learning",
                ("Ada Lovelace",),
                2024,
                doi="10.1000/a",
            ),
            "query-a",
        )
        second = _record(
            deduplicator,
            _provider_work(
                "crossref",
                "doi-b",
                "A Method for Continual Learning",
                ("Ada Lovelace",),
                2024,
                doi="10.1000/b",
            ),
            "query-b",
        )
        ambiguous = _record(
            deduplicator,
            _provider_work(
                "arxiv",
                "arxiv-ambiguous",
                "A Method for Continual Learning",
                ("Ada Lovelace",),
                2024,
            ),
            "query-c",
        )

        assert second.created_work is True
        assert first.work.id != second.work.id
        assert ambiguous.created_work is True
        assert ambiguous.match_method == "ambiguous_weak_match"
    finally:
        connection.close()


def test_discovery_provenance_is_idempotent_for_same_query_and_provider_record():
    connection, repository, deduplicator = _setup()
    try:
        work = _provider_work(
            "openalex",
            "W123456",
            "A Method for Continual Learning",
            ("Ada Lovelace",),
            2024,
            openalex_id="https://openalex.org/W123456",
        )
        first = _record(deduplicator, work, "query-a")
        repeated = _record(deduplicator, work, "query-a")
        another_query = _record(deduplicator, work, "query-b")

        assert repeated.created_work is False
        assert repeated.created_discovery is False
        assert repeated.discovery.id == first.discovery.id
        assert another_query.created_discovery is True
        assert another_query.work.id == first.work.id
        assert len(repository.list_discoveries_for_work(first.work.id)) == 2
    finally:
        connection.close()


def test_enrichment_fills_missing_work_metadata_without_creating_a_discovery():
    connection, repository, deduplicator = _setup()
    try:
        discovered = _record(
            deduplicator,
            _provider_work(
                "arxiv",
                "2401.12345v1",
                "A Method for Continual Learning",
                ("Ada Lovelace",),
                2024,
                arxiv_id="2401.12345",
            ),
            "query-a",
        )

        enriched = deduplicator.enrich_existing_work(
            discovered.work.id,
            _provider_work(
                "openalex",
                "W123456",
                "A corrected provider title",
                ("Ada Lovelace", "Alan Turing"),
                2024,
                abstract="Additional metadata from OpenAlex.",
                doi="10.1000/xyz123",
                arxiv_id="2401.12345",
                openalex_id="W123456",
                venue="Journal of Learning",
            ),
        )

        assert enriched.id == discovered.work.id
        assert enriched.canonical_key == "doi:10.1000/xyz123"
        assert enriched.title == "A Method for Continual Learning"
        assert enriched.abstract == "Additional metadata from OpenAlex."
        assert enriched.authors == ("Ada Lovelace",)
        assert enriched.openalex_id == "w123456"
        assert enriched.venue == "Journal of Learning"
        assert len(repository.list_discoveries_for_work(enriched.id)) == 1
    finally:
        connection.close()


def test_enrichment_refuses_a_record_that_cannot_be_linked_to_the_work():
    connection, _, deduplicator = _setup()
    try:
        discovered = _record(
            deduplicator,
            _provider_work(
                "arxiv", "2401.12345v1", "A Method", ("Ada Lovelace",), 2024,
                arxiv_id="2401.12345",
            ),
            "query-a",
        )
        with pytest.raises(ValueError, match="does not identify"):
            deduplicator.enrich_existing_work(
                discovered.work.id,
                _provider_work(
                    "crossref", "10.1000/other", "Other", ("Ada Lovelace",), 2024,
                    doi="10.1000/other",
                ),
            )
    finally:
        connection.close()


def test_conflicting_strong_ids_cannot_join_two_existing_works():
    connection, repository, deduplicator = _setup()
    try:
        first = _record(
            deduplicator,
            _provider_work(
                "crossref",
                "doi-a",
                "First paper",
                ("Ada Lovelace",),
                2024,
                doi="10.1000/a",
                arxiv_id="2401.12345",
            ),
            "query-a",
        )
        second = _record(
            deduplicator,
            _provider_work(
                "crossref",
                "doi-b",
                "Second paper",
                ("Alan Turing",),
                2024,
                doi="10.1000/b",
            ),
            "query-b",
        )

        with pytest.raises(ResearchIdentityConflict) as conflict:
            _record(
                deduplicator,
                _provider_work(
                    "openalex",
                    "W123456",
                    "Combined metadata",
                    ("Grace Hopper",),
                    2024,
                    doi="10.1000/b",
                    arxiv_id="https://arxiv.org/abs/2401.12345v3",
                ),
                "query-c",
            )
        assert first.work.id != second.work.id
        assert conflict.value.reason == "multiple_identifier_matches"
        assert set(conflict.value.matched_work_ids) == {first.work.id, second.work.id}
        assert repository.get_work(first.work.id) == first.work
        assert repository.get_work(second.work.id) == second.work
        assert len(repository.list_discoveries_for_work(first.work.id)) == 1
        assert len(repository.list_discoveries_for_work(second.work.id)) == 1
    finally:
        connection.close()


def test_provider_priority_cannot_replace_a_conflicting_strong_identifier():
    connection, repository, deduplicator = _setup()
    try:
        original = _record(
            deduplicator,
            _provider_work(
                "arxiv",
                "2401.12345",
                "Original title",
                ("Ada Lovelace",),
                2024,
                doi="10.1000/shared",
                openalex_id="W1",
            ),
            "query-a",
        )

        with pytest.raises(ResearchIdentityConflict) as conflict:
            _record(
                deduplicator,
                _provider_work(
                    "crossref",
                    "10.1000/shared",
                    "Provider-preferred title",
                    ("Ada Lovelace",),
                    2024,
                    doi="10.1000/shared",
                    openalex_id="W2",
                ),
                "query-b",
            )

        assert conflict.value.reason == "conflicting_identifier_values:openalex_id"
        assert repository.get_work(original.work.id) == original.work
        assert len(repository.list_discoveries_for_work(original.work.id)) == 1
    finally:
        connection.close()


def test_enrichment_rejects_an_identifier_owned_by_another_work_without_mutation():
    connection, repository, deduplicator = _setup()
    try:
        target = _record(
            deduplicator,
            _provider_work(
                "arxiv",
                "2401.12345",
                "Target work",
                ("Ada Lovelace",),
                2024,
                arxiv_id="2401.12345",
            ),
            "query-a",
        )
        owner = _record(
            deduplicator,
            _provider_work(
                "openalex",
                "W2",
                "Identifier owner",
                ("Alan Turing",),
                2024,
                openalex_id="W2",
            ),
            "query-b",
        )

        with pytest.raises(ResearchIdentityConflict) as conflict:
            deduplicator.enrich_existing_work(
                target.work.id,
                _provider_work(
                    "openalex",
                    "W2",
                    "Target work",
                    ("Ada Lovelace",),
                    2024,
                    arxiv_id="2401.12345",
                    openalex_id="W2",
                ),
            )

        assert conflict.value.reason == "multiple_identifier_matches"
        assert set(conflict.value.matched_work_ids) == {target.work.id, owner.work.id}
        assert repository.get_work(target.work.id) == target.work
        assert repository.get_work(owner.work.id) == owner.work
        assert len(repository.list_discoveries_for_work(target.work.id)) == 1
        assert len(repository.list_discoveries_for_work(owner.work.id)) == 1
    finally:
        connection.close()


def test_rejects_naive_discovery_timestamp():
    connection, _, deduplicator = _setup()
    try:
        with pytest.raises(ValueError, match="timezone-aware"):
            deduplicator.record_discovery(
                "continual-learning",
                "replay",
                "query-a",
                "query",
                _provider_work("arxiv", "arxiv-1", "Title", ("Ada Lovelace",), 2024),
                discovered_at=datetime(2024, 1, 1),
            )
    finally:
        connection.close()


def _setup():
    connection = connect_database(":memory:")
    repository = ResearchRepository(connection)
    deduplicator = ResearchDeduplicator(repository, clock=lambda: _NOW)
    return connection, repository, deduplicator


def _record(deduplicator, work, query_key):
    return deduplicator.record_discovery(
        "continual-learning",
        "replay",
        query_key,
        "continual learning",
        work,
    )


def _provider_work(
    provider,
    provider_record_id,
    title,
    authors,
    year,
    abstract=None,
    published_at=None,
    venue=None,
    doi=None,
    arxiv_id=None,
    openalex_id=None,
    semantic_scholar_id=None,
    url=None,
    metadata=None,
):
    return ProviderWork(
        provider=provider,
        provider_record_id=provider_record_id,
        title=title,
        abstract=abstract,
        authors=authors,
        year=year,
        published_at=published_at,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        openalex_id=openalex_id,
        semantic_scholar_id=semantic_scholar_id,
        url=url,
        metadata=metadata or {},
    )
