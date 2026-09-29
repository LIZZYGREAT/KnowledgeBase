from pathlib import Path

import pytest
import yaml

from backend.app.services.markdown_parser import parse_markdown, parse_yaml
from backend.app.services.style_linter import lint_markdown, load_writing_standard


FIXTURES = Path(__file__).parent / "fixtures"
STANDARD = load_writing_standard()


def read_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parser_extracts_frontmatter_headings_sections_links_citations_and_math():
    parsed = parse_markdown(read_fixture("valid_document.md"))

    assert parsed.frontmatter["id"] == "ewc-review"
    assert [heading.level for heading in parsed.headings] == [1, 2, 3]
    assert parsed.sections[0].heading.text == "Elastic Weight Consolidation"
    assert parsed.wiki_links[0].target == "fisher-information"
    assert parsed.wiki_links[0].label == "Fisher Information"
    assert parsed.citations[0].source_id == "ewc-2017"
    assert parsed.citations[0].locator == "Sec. 2"
    assert [math.kind for math in parsed.math_expressions] == ["inline", "display"]
    assert len(parsed.mermaid_blocks) == 1
    assert len(parsed.code_blocks) == 1
    assert not parsed.issues


def test_code_blocks_do_not_create_links_citations_or_math():
    parsed = parse_markdown(
        "# Example\n\n```python\n[[ignored]] [@ignored] $x$\n```\n"
        "Inline `[[also ignored]] $y$` remains code.\n"
    )

    assert not parsed.wiki_links
    assert not parsed.citations
    assert not parsed.math_expressions


def test_linter_accepts_valid_document_and_term_fixtures():
    assert lint_markdown(read_fixture("valid_document.md"), "document", STANDARD) == []
    assert lint_markdown(read_fixture("valid_term.md"), "term", STANDARD) == []


def test_linter_reports_heading_errors_and_safe_format_fix():
    issues = lint_markdown(read_fixture("invalid_heading.md"), "document", STANDARD)

    assert {issue.code for issue in issues} >= {
        "heading.h2_numbering",
        "heading.h3_dot_space",
    }
    safe_fix = next(issue.safe_fix for issue in issues if issue.code == "heading.h3_dot_space")
    assert safe_fix == "### 1. Missing space"


def test_linter_reports_unclosed_math():
    issues = lint_markdown(read_fixture("invalid_math.md"), "document", STANDARD)

    assert any(issue.code == "math.unclosed_inline" for issue in issues)


def test_linter_checks_heading_hierarchy_count_and_maximum_level():
    text = "---\nschema_version: 1\nid: headings\ntitle: Headings\ntype: learning-note\n---\n"
    text += "# First\n### 1. Skipped level\n###### Too deep\n# Second\n"

    issues = lint_markdown(text, "document", STANDARD)
    codes = {issue.code for issue in issues}

    assert "heading.h1_count" in codes
    assert "heading.hierarchy" in codes
    assert "heading.max_level" in codes


def test_linter_rejects_missing_frontmatter_and_invalid_entity_schema():
    missing = lint_markdown("# Missing metadata\n", "document", STANDARD)
    invalid = lint_markdown(
        "---\nschema_version: 1\nid: not-a-document\ntitle: Wrong type\ntype: concept\n---\n# Wrong type\n",
        "document",
        STANDARD,
    )

    assert any(issue.code == "frontmatter.missing" for issue in missing)
    assert any(issue.code == "schema.metadata" for issue in invalid)


def test_linter_reports_malformed_wiki_links_without_mermaid_whitelist():
    text = "# Example\n\n## 一、Section\n\n[[broken]\n\n```mermaid\nnot-a-diagram\n```\n"

    issues = lint_markdown(text, "document", STANDARD)

    assert any(issue.code == "wiki_link.syntax" for issue in issues)
    assert not any(issue.code.startswith("mermaid.") for issue in issues)


def test_linter_rejects_empty_mermaid_blocks():
    issues = lint_markdown(
        "# Example\n\n```mermaid\n%% comment only\n```\n", "document", STANDARD
    )

    assert any(issue.code == "mermaid.empty" for issue in issues)


def test_unclosed_fenced_block_is_reported():
    parsed = parse_markdown("# Example\n\n```text\nunfinished\n")

    assert [issue.code for issue in parsed.issues] == ["code_fence.unclosed"]


def test_duplicate_frontmatter_key_is_rejected():
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        parse_yaml("id: first\nid: second\n")
