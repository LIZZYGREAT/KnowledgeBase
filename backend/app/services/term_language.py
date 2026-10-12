"""Deterministic language sections; only real Markdown headings delimit sections."""

import re
from backend.app.services.markdown_parser import parse_markdown


def normalize_term_h3_numbering(explanation):
    """Number real H3 headings in one generated language explanation only."""
    parsed = parse_markdown(explanation)
    lines = explanation.splitlines(keepends=True)
    changed = False
    number = 0
    for heading in parsed.headings:
        if heading.level != 3:
            continue
        number += 1
        line_index = heading.line - 1
        line = lines[line_index]
        prefix_match = re.match(r"^( {0,3}###\s+)", line)
        if prefix_match is None:
            continue
        title = re.sub(r"^\d+\.\s*", "", heading.text).strip()
        newline_match = re.search(r"(\r\n|\r|\n)$", line)
        newline = newline_match.group(1) if newline_match else ""
        normalized = "{}{}. {}{}".format(
            prefix_match.group(1), number, title, newline
        )
        if normalized != line:
            lines[line_index] = normalized
            changed = True
    return "".join(lines) if changed else explanation


def replace_term_language(content, language, explanation):
    if language not in {"zh", "en"}:
        raise ValueError("Unsupported Term language")
    if any(heading.level <= 2 for heading in parse_markdown(explanation).headings):
        raise ValueError("A language explanation cannot introduce top-level section boundaries")
    parsed = parse_markdown(content)
    headings = [heading for heading in parsed.headings if heading.level == 2]
    aliases = {"zh": "中文解释", "en": "English Explanation"}
    lines = content.splitlines(keepends=True)
    for index, heading in enumerate(headings):
        label = re.sub(r"^[一二三四五六七八九十]+、\s*", "", heading.text)
        if label == aliases[language]:
            end = headings[index + 1].line - 1 if index + 1 < len(headings) else len(lines)
            return "".join(lines[:heading.line]) + "\n" + explanation.strip() + "\n\n" + "".join(lines[end:])
    numerals = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
    if len(headings) >= len(numerals):
        raise ValueError("Use the Markdown editor to add another section")
    return content.rstrip() + "\n\n## " + numerals[len(headings)] + "、" + aliases[language] + "\n\n" + explanation.strip() + "\n"


def replace_term_languages(content, definition_zh, definition_en):
    """Build one complete bilingual revision before it can be stored as a Proposal."""
    updated = replace_term_language(content, "zh", definition_zh)
    return replace_term_language(updated, "en", definition_en)
