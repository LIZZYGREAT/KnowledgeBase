from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.domain.document import DocumentMetadata
from backend.app.domain.source import SourceMetadata
from backend.app.domain.taxonomy import TaxonomyRegistry
from backend.app.domain.term import TermMetadata
from backend.app.services.markdown_parser import parse_yaml
from backend.app.services.style_linter import validate_taxonomy_registry


FIXTURES = Path(__file__).parent / "fixtures"


def metadata_from_markdown(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    return parse_yaml(frontmatter)


def test_document_schema_accepts_the_canonical_example():
    document = DocumentMetadata.model_validate(metadata_from_markdown("valid_document.md"))

    assert document.id == "ewc-review"
    assert document.type == "paper-note"

    invalid = metadata_from_markdown("valid_document.md")
    invalid["provenance"]["origin"] = "authored"
    with pytest.raises(ValidationError):
        DocumentMetadata.model_validate(invalid)


def test_term_schema_accepts_canonical_term_and_rejects_unknown_type():
    term = TermMetadata.model_validate(metadata_from_markdown("valid_term.md"))
    assert term.depth == "standard"

    invalid = metadata_from_markdown("valid_term.md")
    invalid["type"] = "algorithm"
    with pytest.raises(ValidationError):
        TermMetadata.model_validate(invalid)


def test_source_schema_accepts_storage_uri_and_rejects_machine_path():
    source = SourceMetadata.model_validate(
        parse_yaml((FIXTURES / "valid_source.yaml").read_text(encoding="utf-8"))
    )
    assert source.attachments.local_pdf == "storage://papers/ewc-2017.pdf"

    invalid = source.model_dump()
    invalid["attachments"]["local_pdf"] = r"C:\Users\someone\paper.pdf"
    with pytest.raises(ValidationError):
        SourceMetadata.model_validate(invalid)


def test_source_arxiv_identifier_rejects_yaml_number():
    data = parse_yaml((FIXTURES / "valid_source.yaml").read_text(encoding="utf-8"))
    data["identifiers"]["arxiv_id"] = 1701.00001

    with pytest.raises(ValidationError):
        SourceMetadata.model_validate(data)


def test_taxonomy_registry_rejects_duplicate_ids():
    registry = {
        "schema_version": 1,
        "entries": [
            {"id": "ai", "title": "AI"},
            {"id": "ai", "title": "Artificial Intelligence"},
        ],
    }

    with pytest.raises(ValidationError, match="unique"):
        validate_taxonomy_registry(registry)


def test_taxonomy_registry_accepts_empty_phase_one_skeleton():
    registry = TaxonomyRegistry.model_validate({"schema_version": 1, "entries": []})
    assert registry.entries == []
