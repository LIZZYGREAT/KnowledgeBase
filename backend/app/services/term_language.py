"""Deterministic language sections; only real Markdown headings delimit sections."""

import re
from backend.app.services.markdown_parser import parse_markdown


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
