"""Deterministic Markdown style and canonical metadata checks."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Optional
import re

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.domain.document import DocumentMetadata
from backend.app.domain.source import SourceMetadata
from backend.app.domain.taxonomy import TaxonomyRegistry
from backend.app.domain.term import TermMetadata
from .markdown_parser import MarkdownDocument, parse_markdown


class _StandardModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _HeadingRule(_StandardModel):
    numbering: Literal["none", "chinese", "arabic-dot-space"]


class _H1Rule(_HeadingRule):
    count: int = Field(ge=0)


class _HeadingStandard(_StandardModel):
    max_level: int = Field(ge=1, le=6)
    h1: _H1Rule
    h2: _HeadingRule
    h3: _HeadingRule
    h4: _HeadingRule
    h5: _HeadingRule


class _MathStandard(_StandardModel):
    inline_for_short_expression: bool
    display_for_multiline: bool


class _MermaidStandard(_StandardModel):
    enabled: bool


class WritingStandard(_StandardModel):
    schema_version: Literal[1]
    heading: _HeadingStandard
    math: _MathStandard
    mermaid: _MermaidStandard


@dataclass(frozen=True)
class LintIssue:
    code: str
    message: str
    line: int
    severity: Literal["ERROR", "WARN"] = "ERROR"
    safe_fix: Optional[str] = None


_CHINESE_NUMBERED = r"^[一二三四五六七八九十百零〇两]+、\S.*$"
_H1_NUMBERING = r"^\s*(?:\d+[.)、]|[一二三四五六七八九十百零〇两]+[、.])\s*"
_H4_H5_NUMBERING = r"^\s*(?:\d+[.)、]|[一二三四五六七八九十百零〇两]+[、.])\s*\S"
_MERMAID_DECLARATION = (
    r"^(?:flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|"
    r"erDiagram|journey|gantt|pie|gitGraph|mindmap|timeline|quadrantChart|"
    r"requirementDiagram|C4(?:Context|Container|Component|Dynamic|Deployment)|"
    r"sankey-beta|xychart-beta|block-beta|packet-beta|architecture-beta|kanban)\b"
)


def load_writing_standard(path: Optional[Path] = None) -> WritingStandard:
    if path is None:
        repository_root = Path(__file__).resolve().parents[3]
        path = repository_root / "config" / "writing-standard.yaml"
    with path.open("r", encoding="utf-8") as source:
        value = yaml.safe_load(source)
    return WritingStandard.model_validate(value)


def lint_markdown(
    text: str,
    entity_type: Optional[str] = None,
    standard: Optional[WritingStandard] = None,
    maintenance_status: Optional[str] = None,
) -> list[LintIssue]:
    standard = standard or load_writing_standard()
    parsed = parse_markdown(text)
    issues = [LintIssue(item.code, item.message, item.line) for item in parsed.issues]

    if parsed.frontmatter is None:
        if not any(item.code.startswith("frontmatter.") for item in parsed.issues):
            issues.append(
                LintIssue("frontmatter.missing", "Canonical Markdown requires YAML frontmatter.", 1)
            )
    else:
        inferred_type = entity_type or _infer_entity_type(parsed.frontmatter)
        if inferred_type in {"document", "term"}:
            model = DocumentMetadata if inferred_type == "document" else TermMetadata
            try:
                model.model_validate(parsed.frontmatter)
            except ValidationError as error:
                line = (parsed.frontmatter_start_line or 1) + 1
                issues.extend(
                    LintIssue(
                        "schema.metadata",
                        "metadata{}: {}".format(
                            "." + ".".join(str(part) for part in detail["loc"])
                            if detail["loc"]
                            else "",
                            detail["msg"],
                        ),
                        line,
                    )
                    for detail in error.errors()
                )
        else:
            issues.append(
                LintIssue(
                    "schema.entity_type",
                    "Set entity_type to 'document' or 'term' to validate this Markdown file.",
                    (parsed.frontmatter_start_line or 1) + 1,
                )
            )

    issues.extend(_lint_headings(parsed, standard))
    if standard.mermaid.enabled:
        for block in parsed.mermaid_blocks:
            meaningful_lines = [
                line.strip()
                for line in block.content.splitlines()
                if line.strip() and not line.strip().startswith("%%")
            ]
            if not meaningful_lines:
                issues.append(
                    LintIssue(
                        "mermaid.empty",
                        "Mermaid block must contain a diagram declaration.",
                        block.start_line,
                    )
                )
            elif not re.match(_MERMAID_DECLARATION, meaningful_lines[0]):
                issues.append(
                    LintIssue(
                        "mermaid.declaration",
                        "Mermaid block must start with a recognized diagram declaration.",
                        block.start_line,
                    )
                )
    if maintenance_status is None and parsed.frontmatter is not None:
        maintenance = parsed.frontmatter.get("maintenance") or {}
        maintenance_status = maintenance.get("status") if isinstance(maintenance, dict) else None
    if maintenance_status == "legacy":
        issues = [
            replace(issue, severity="WARN")
            if issue.code.startswith("heading.") or issue.code.startswith("mermaid.")
            else issue
            for issue in issues
        ]
    return issues


def validate_source_metadata(value):
    return SourceMetadata.model_validate(value)


def validate_taxonomy_registry(value):
    return TaxonomyRegistry.model_validate(value)


def _infer_entity_type(metadata: dict) -> Optional[str]:
    if metadata.get("type") in {"paper-note", "learning-note", "course-note"}:
        return "document"
    if metadata.get("type") in {"concept", "vocabulary"}:
        return "term"
    return None


def _lint_headings(
    parsed: MarkdownDocument, standard: WritingStandard
) -> list[LintIssue]:
    issues = []
    h1s = [heading for heading in parsed.headings if heading.level == 1]
    if len(h1s) != standard.heading.h1.count:
        issues.append(
            LintIssue(
                "heading.h1_count",
                "Expected exactly {} H1 heading(s), found {}.".format(
                    standard.heading.h1.count, len(h1s)
                ),
                h1s[0].line if h1s else 1,
            )
        )
    for heading in h1s:
        if re.match(_H1_NUMBERING, heading.text):
            issues.append(
                LintIssue(
                    "heading.h1_numbering",
                    "H1 headings must not be numbered.",
                    heading.line,
                )
            )

    previous_level = 0
    for heading in parsed.headings:
        if heading.level > standard.heading.max_level:
            issues.append(
                LintIssue(
                    "heading.max_level",
                    "Heading level H{} exceeds the configured maximum H{}.".format(
                        heading.level, standard.heading.max_level
                    ),
                    heading.line,
                )
            )
        if heading.level > previous_level + 1:
            issues.append(
                LintIssue(
                    "heading.hierarchy",
                    "Heading level must not skip from H{} to H{}.".format(
                        previous_level, heading.level
                    ),
                    heading.line,
                )
            )
        previous_level = heading.level

        if heading.level == 2 and standard.heading.h2.numbering == "chinese":
            if not re.match(_CHINESE_NUMBERED, heading.text):
                issues.append(
                    LintIssue(
                        "heading.h2_numbering",
                        "H2 headings must start with a Chinese numeral and '、'.",
                        heading.line,
                    )
                )
        elif heading.level == 3 and standard.heading.h3.numbering == "arabic-dot-space":
            match = re.match(r"^(\d+)\.(\s*)(\S.*)$", heading.text)
            if not match:
                issues.append(
                    LintIssue(
                        "heading.h3_numbering",
                        "H3 headings must use Arabic numbering followed by '. '.",
                        heading.line,
                    )
                )
            elif match.group(2) != " ":
                fixed_text = "{}. {}".format(match.group(1), match.group(3))
                issues.append(
                    LintIssue(
                        "heading.h3_dot_space",
                        "Add one space after the H3 numbering period.",
                        heading.line,
                        safe_fix="### " + fixed_text,
                    )
                )
        elif heading.level in {4, 5}:
            if re.match(_H4_H5_NUMBERING, heading.text):
                issues.append(
                    LintIssue(
                        "heading.higher_numbering",
                        "H4 and H5 headings must not be numbered.",
                        heading.line,
                    )
                )
    return issues
