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

_ISSUE_LABELS = {
    "heading.h1_count": "建议保留一个主标题。",
    "heading.h1_numbering": "建议主标题不编号。",
    "heading.h2_numbering": "建议二级标题使用“一、”等中文编号。",
    "heading.h3_numbering": "建议三级标题使用“1. ”等编号。",
    "heading.h3_dot_space": "建议三级标题编号的句点后保留一个空格。",
    "heading.higher_numbering": "建议四、五级标题不编号。",
    "heading.hierarchy": "建议标题层级连续，避免跳级。",
    "heading.max_level": "标题层级超过写作偏好中的上限。",
    "mermaid.empty": "图表块为空，可以补充图表或删除空块。",
    "frontmatter.missing": "缺少 YAML 元数据，请在正文前补充必需字段。",
    "frontmatter.unclosed": "YAML 元数据缺少结束分隔符 ---。",
    "frontmatter.mapping": "YAML 元数据必须使用字段与值的格式。",
    "math.unclosed_inline": "行内公式缺少结束的 $，请补齐公式边界。",
    "math.unclosed_display": "公式块缺少结束的 $$，请补齐公式边界。",
    "code_fence.unclosed": "代码块缺少结束围栏，请补齐代码边界。",
    "wiki_link.syntax": "知识链接格式不完整，请使用 [[术语标识]] 并补齐括号。",
}


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
                        "元数据字段{}无效：{}".format(
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
    if entity_type == "term" or (parsed.frontmatter and _infer_entity_type(parsed.frontmatter) == "term"):
        languages = {}
        for heading in parsed.headings:
            label = re.sub(r"^[一二三四五六七八九十]+、\s*", "", heading.text)
            if heading.level == 2 and label in {"中文解释", "English Explanation"}:
                if label in languages:
                    issues.append(LintIssue("term.language_duplicate", "语言分节重复，请保留唯一的中文解释和英文解释分节。", heading.line))
                languages[label] = heading.line
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
                        "Mermaid block must contain diagram content.",
                        block.start_line,
                    )
                )
    if maintenance_status is None and parsed.frontmatter is not None:
        maintenance = parsed.frontmatter.get("maintenance") or {}
        maintenance_status = maintenance.get("status") if isinstance(maintenance, dict) else None
    # One policy for Import, AI, preflight, single/batch Publish and repository checks.
    # Parsing and metadata failures retain their blocking severity.
    return [
        replace(
            issue,
            severity="WARN" if issue.code.startswith("heading.") or issue.code == "mermaid.empty" else issue.severity,
            message=_ISSUE_LABELS.get(issue.code, issue.message),
        )
        for issue in issues
    ]


def validate_source_metadata(value):
    return SourceMetadata.model_validate(value)


def validate_taxonomy_registry(value):
    return TaxonomyRegistry.model_validate(value)


def _infer_entity_type(metadata: dict) -> Optional[str]:
    if metadata.get("type") in {"paper-note", "learning-note", "course-note"}:
        return "document"
    if metadata.get("type") in {"concept", "entity", "vocabulary"}:
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
