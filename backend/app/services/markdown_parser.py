"""Deterministic extraction of the Markdown constructs used by KnowledgeBase."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import re

import yaml
from yaml.constructor import ConstructorError
from yaml.resolver import BaseResolver


@dataclass(frozen=True)
class ParseIssue:
    code: str
    message: str
    line: int


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int
    body_index: int


@dataclass(frozen=True)
class Section:
    heading: Heading
    start_line: int
    end_line: int
    body: str


@dataclass(frozen=True)
class WikiLink:
    target: str
    label: Optional[str]
    line: int
    start: int
    end: int


@dataclass(frozen=True)
class Citation:
    source_id: str
    locator: Optional[str]
    line: int
    raw: str


@dataclass(frozen=True)
class MathExpression:
    kind: str
    content: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class CodeBlock:
    language: str
    content: str
    start_line: int
    end_line: int


@dataclass
class MarkdownDocument:
    frontmatter: Optional[Dict[str, Any]] = None
    frontmatter_raw: Optional[str] = None
    frontmatter_start_line: Optional[int] = None
    frontmatter_end_line: Optional[int] = None
    headings: List[Heading] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)
    wiki_links: List[WikiLink] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)
    math_expressions: List[MathExpression] = field(default_factory=list)
    code_blocks: List[CodeBlock] = field(default_factory=list)
    mermaid_blocks: List[CodeBlock] = field(default_factory=list)
    issues: List[ParseIssue] = field(default_factory=list)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "mapping keys must be hashable",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found duplicate key {!r}".format(key),
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)

_FRONTMATTER_CLOSING = {"---", "..."}
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})([^`]*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$")
_WIKI_LINK = re.compile(
    r"\[\[(?P<target>[^\[\]|\]\n]+?)(?:\|(?P<label>[^\[\]\n]+?))?\]\]"
)
_CITATION = re.compile(
    r"\[@(?P<source>[a-z0-9][a-z0-9-]*)(?:,\s*(?P<locator>[^\]\n]+?))?\]"
)
_INLINE_CODE = re.compile(r"(?<!`)`+[^`\n]*?`+(?!`)")


def parse_yaml(text: str) -> Any:
    """Load safe YAML while rejecting duplicate mapping keys."""
    return yaml.load(text, Loader=_UniqueKeyLoader)


def parse_markdown(text: str) -> MarkdownDocument:
    """Parse frontmatter, headings, links, citations, math, and fenced blocks."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    document = MarkdownDocument()
    body_start_index = 0

    if lines and lines[0].strip() == "---":
        closing_index = next(
            (
                index
                for index in range(1, len(lines))
                if lines[index].strip() in _FRONTMATTER_CLOSING
            ),
            None,
        )
        document.frontmatter_start_line = 1
        if closing_index is None:
            document.issues.append(
                ParseIssue("frontmatter.unclosed", "Frontmatter is not closed.", 1)
            )
            body_start_index = len(lines)
        else:
            document.frontmatter_end_line = closing_index + 1
            document.frontmatter_raw = "\n".join(lines[1:closing_index])
            body_start_index = closing_index + 1
            try:
                data = parse_yaml(document.frontmatter_raw)
                if not isinstance(data, dict):
                    document.issues.append(
                        ParseIssue(
                            "frontmatter.mapping",
                            "Frontmatter must contain a YAML mapping.",
                            2,
                        )
                    )
                else:
                    document.frontmatter = data
            except yaml.YAMLError as error:
                problem_line = getattr(getattr(error, "problem_mark", None), "line", 0)
                document.issues.append(
                    ParseIssue(
                        "frontmatter.yaml",
                        "Invalid frontmatter YAML: {}".format(error),
                        problem_line + 2,
                    )
                )

    body_lines = lines[body_start_index:]
    first_body_line = body_start_index + 1
    visible_lines = list(body_lines)
    fence_char = None
    fence_length = 0
    fence_start = 0
    fence_language = ""
    fence_content = []

    for index, line in enumerate(body_lines):
        absolute_line = first_body_line + index
        if fence_char is not None:
            visible_lines[index] = " " * len(line)
            closing_pattern = (
                r"^ {0,3}"
                + re.escape(fence_char)
                + r"{"
                + str(fence_length)
                + r",}\s*$"
            )
            closing = re.match(closing_pattern, line)
            if closing:
                block = CodeBlock(
                    fence_language,
                    "\n".join(fence_content),
                    fence_start,
                    absolute_line,
                )
                if fence_language == "mermaid":
                    document.mermaid_blocks.append(block)
                else:
                    document.code_blocks.append(block)
                fence_char = None
                fence_length = 0
                fence_content = []
            else:
                fence_content.append(line)
            continue

        opening = _FENCE_OPEN.match(line)
        if opening:
            marker = opening.group(1)
            fence_char = marker[0]
            fence_length = len(marker)
            info = opening.group(2).strip()
            fence_language = info.split(None, 1)[0].lower() if info else ""
            fence_start = absolute_line
            fence_content = []
            visible_lines[index] = " " * len(line)

    if fence_char is not None:
        document.issues.append(
            ParseIssue(
                "code_fence.unclosed",
                "Fenced code block is not closed.",
                fence_start,
            )
        )
        block = CodeBlock(
            fence_language,
            "\n".join(fence_content),
            fence_start,
            len(lines),
        )
        if fence_language == "mermaid":
            document.mermaid_blocks.append(block)
        else:
            document.code_blocks.append(block)

    for index, line in enumerate(visible_lines):
        match = _HEADING.match(line)
        if match:
            document.headings.append(
                Heading(
                    len(match.group(1)),
                    match.group(2).strip(),
                    first_body_line + index,
                    index,
                )
            )

    math_input = [
        _INLINE_CODE.sub(lambda match: " " * len(match.group(0)), line)
        for line in visible_lines
    ]
    masked_lines = _mask_math(math_input, first_body_line, document)
    document.sections = _build_sections(body_lines, document.headings, first_body_line)

    for index, line in enumerate(masked_lines):
        text_without_code = _INLINE_CODE.sub(lambda match: " " * len(match.group(0)), line)
        absolute_line = first_body_line + index

        valid_link_spans = []
        for match in _WIKI_LINK.finditer(text_without_code):
            target = match.group("target").strip()
            label = match.group("label")
            label = label.strip() if label is not None else None
            if not target or (label is not None and not label):
                continue
            document.wiki_links.append(
                WikiLink(target, label, absolute_line, match.start(), match.end())
            )
            valid_link_spans.append(match.span())

        unparsed_line = list(text_without_code)
        for start, end in valid_link_spans:
            unparsed_line[start:end] = " " * (end - start)
        remaining = "".join(unparsed_line)
        if "[[" in remaining or "]]" in remaining:
            document.issues.append(
                ParseIssue(
                    "wiki_link.syntax",
                    "Malformed wiki link; use [[term-id]] or [[term-id|label]].",
                    absolute_line,
                )
            )

        for match in _CITATION.finditer(text_without_code):
            locator = match.group("locator")
            document.citations.append(
                Citation(
                    match.group("source"),
                    locator.strip() if locator else None,
                    absolute_line,
                    match.group(0),
                )
            )

    return document


def _mask_math(lines: List[str], first_line: int, document: MarkdownDocument) -> List[str]:
    masked = []
    mode = None
    start_line = None
    content = []

    for line_index, line in enumerate(lines):
        output = list(line)
        index = 0
        while index < len(line):
            if mode == "display":
                if line.startswith("$$", index) and not _is_escaped(line, index):
                    output[index : index + 2] = "  "
                    document.math_expressions.append(
                        MathExpression("display", "\n".join(content), start_line, first_line + line_index)
                    )
                    mode = None
                    content = []
                    index += 2
                else:
                    content.append(line[index])
                    output[index] = " "
                    index += 1
                continue

            if mode == "inline":
                if line[index] == "$" and not line.startswith("$$", index) and not _is_escaped(line, index):
                    output[index] = " "
                    document.math_expressions.append(
                        MathExpression("inline", "".join(content), start_line, first_line + line_index)
                    )
                    mode = None
                    content = []
                    index += 1
                else:
                    content.append(line[index])
                    output[index] = " "
                    index += 1
                continue

            if line.startswith("$$", index) and not _is_escaped(line, index):
                output[index : index + 2] = "  "
                mode = "display"
                start_line = first_line + line_index
                content = []
                index += 2
            elif line[index] == "$" and not _is_escaped(line, index):
                output[index] = " "
                mode = "inline"
                start_line = first_line + line_index
                content = []
                index += 1
            else:
                index += 1

        if mode == "inline":
            document.issues.append(
                ParseIssue(
                    "math.unclosed_inline",
                    "Inline math is not closed on this line.",
                    first_line + line_index,
                )
            )
            mode = None
            content = []
        masked.append("".join(output))

    if mode == "display":
        document.issues.append(
            ParseIssue(
                "math.unclosed_display",
                "Display math is not closed.",
                start_line,
            )
        )
    return masked


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _build_sections(
    body_lines: List[str], headings: List[Heading], first_body_line: int
) -> List[Section]:
    sections = []
    for index, heading in enumerate(headings):
        end_index = len(body_lines)
        for following in headings[index + 1 :]:
            if following.level <= heading.level:
                end_index = following.body_index
                break
        content_start = heading.body_index + 1
        section_body = "\n".join(body_lines[content_start:end_index])
        sections.append(
            Section(
                heading,
                heading.line,
                first_body_line + end_index - 1 if end_index > content_start else heading.line,
                section_body,
            )
        )
    return sections
