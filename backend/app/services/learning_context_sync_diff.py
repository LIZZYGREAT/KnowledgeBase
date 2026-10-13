"""Deterministic Markdown diffing and conservative no-AI filters."""

import difflib
import re

from backend.app.services.learning_context_service import LearningContextError
from backend.app.services.markdown_parser import parse_markdown


_MAX_SECTIONS = 10
_MAX_DIFF_CHARS = 18000
_MAX_SECTION_CHARS = 5000
_CRITICAL_TEXT = re.compile(
    r"(?:\d|\$|\\[A-Za-z]+|[=<>±×÷≠≤≥∑∏→←≈]|`|"
    r"(?i:\b(?:not|no|never|without|cannot|must|only|required|necessary|sufficient|always|"
    r"therefore|however|method|algorithm|gradient|projection|constraint|condition|threshold|"
    r"theorem|lemma|dataset|model|loss|convergence|precondition|conclusion|assumption|"
    r"parameter|baseline)\b)|"
    r"否|不|无|未|没有|并非|除非|不能|不可|不再|不是|而非|必须|仅|只有|必要|充分|"
    r"条件|阈值|结论|前提|假设|证明|算法|机制|方法|梯度|约束|模型|损失|收敛|参数|"
    r"\b(?:[A-Z]{2,}|[A-Z][a-z]+[A-Z][A-Za-z]*)\b)"
)
_MARKDOWN_VISUAL = re.compile(r"\*\*|__|~~|(?<!\w)\*(?!\w)|(?<!\w)_(?!\w)|`+")
_ORDINARY_PUNCTUATION = re.compile(r"[，。！？、；：,.!?;:'\"“”‘’（）()【】《》{}\[\]]")


def markdown_body(markdown):
    parsed = parse_markdown(markdown)
    lines = markdown.splitlines()
    start = parsed.frontmatter_end_line or 0
    return "\n".join(lines[start:])


def normalize_heading(value):
    value = re.sub(r"^\s*\d+(?:\.\d+)*(?:[.)、:：-])\s*", "", value)
    return semantic_text(value)


def semantic_text(value):
    value = _MARKDOWN_VISUAL.sub("", value)
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", value)
    value = re.sub(r"(?m)^\s*\d+[.)、]\s+", "", value)
    value = _ORDINARY_PUNCTUATION.sub("", value)
    return " ".join(value.casefold().split())


def section_units(markdown):
    parsed = parse_markdown(markdown)
    lines = markdown.splitlines()
    body_start = parsed.frontmatter_end_line or 0
    body_lines = lines[body_start:]
    headings = sorted(parsed.headings, key=lambda item: item.body_index)
    units = []
    # Treat H1/H2 as logical sections and keep deeper headings inside their
    # parent section. This gives the model useful chapter-sized context while
    # still keeping every paragraph available for bounded batching below.
    boundaries = [heading for heading in headings if heading.level <= 2]
    first_heading = boundaries[0].body_index if boundaries else len(body_lines)
    preamble = "\n".join(body_lines[:first_heading]).strip()
    if preamble:
        units.append({"key": "__preamble__", "heading": "未分节内容", "text": preamble})
    occurrences = {}
    for index, heading in enumerate(boundaries):
        stop = boundaries[index + 1].body_index if index + 1 < len(boundaries) else len(body_lines)
        section = "\n".join(body_lines[heading.body_index:stop]).strip()
        normalized = normalize_heading(heading.text) or "未命名章节"
        occurrences[normalized] = occurrences.get(normalized, 0) + 1
        key = "{}#{}".format(normalized, occurrences[normalized])
        units.append({"key": key, "heading": heading.text, "text": section})
    if not units and body_lines:
        units.append({"key": "__preamble__", "heading": "未分节内容", "text": "\n".join(body_lines).strip()})
    return units


def changed_sections(old_text, new_text, full=False):
    old_units = section_units(old_text) if old_text else []
    new_units = section_units(new_text)
    old_by_key = {item["key"]: item for item in old_units}
    new_by_key = {item["key"]: item for item in new_units}
    order = [item["key"] for item in new_units]
    order.extend(item["key"] for item in old_units if item["key"] not in new_by_key)
    changed = []
    for position, key in enumerate(order):
        old = old_by_key.get(key, {"heading": "未分节内容", "text": ""})
        new = new_by_key.get(key, {"heading": old["heading"], "text": ""})
        if not full and semantic_text(old["text"]) == semantic_text(new["text"]):
            continue
        neighbor_text = []
        for neighbor_key in order[max(0, position - 1):position] + order[position + 1:position + 2]:
            neighbor = new_by_key.get(neighbor_key) or old_by_key.get(neighbor_key)
            if neighbor:
                neighbor_text.append(neighbor["text"][:200])
        heading = new.get("heading") or old.get("heading") or "未分节内容"
        excerpts = _bounded_section_pairs(old["text"], new["text"])
        for part_index, (before, after) in enumerate(excerpts, 1):
            part_heading = heading
            if len(excerpts) > 1:
                part_heading = "{}（片段 {}/{}）".format(heading, part_index, len(excerpts))
            changed.append(
                {
                    "heading": part_heading,
                    "before": before,
                    "after": after,
                    "nearby_context": "\n\n".join(neighbor_text)[:500],
                }
            )
    return changed


def batch_sections(sections):
    """Split complete change sections into bounded, ordered model requests."""
    batches = []
    current = []
    current_chars = 0
    for section in sections:
        size = sum(
            len(section.get(field, ""))
            for field in ("before", "after", "nearby_context")
        )
        if size > _MAX_DIFF_CHARS:
            raise LearningContextError("单个章节变化超过模型输入上限")
        if current and (
            len(current) >= _MAX_SECTIONS
            or current_chars + size > _MAX_DIFF_CHARS
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(section)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _bounded_section_pairs(before, after):
    if max(len(before), len(after)) <= _MAX_SECTION_CHARS:
        return [(before, after)]
    if not before:
        return [("", chunk) for chunk in _split_long_text(after)]
    if not after:
        return [(chunk, "") for chunk in _split_long_text(before)]
    old_excerpt, new_excerpt = _diff_excerpt(before, after)
    if len(old_excerpt) > _MAX_SECTION_CHARS or len(new_excerpt) > _MAX_SECTION_CHARS:
        raise LearningContextError("变化范围过大，暂未发送模型；请按章节拆分修改后重试。")
    return [(old_excerpt, new_excerpt)]


def _split_long_text(value):
    chunks = []
    remaining = value
    while remaining:
        if len(remaining) <= _MAX_SECTION_CHARS:
            chunks.append(remaining)
            break
        cut = remaining.rfind(" ", 0, _MAX_SECTION_CHARS - 400)
        if cut < _MAX_SECTION_CHARS // 2:
            cut = _MAX_SECTION_CHARS - 400
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    return chunks or [""]


def _diff_excerpt(before, after):
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=True)
    radius = 350
    ranges = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        candidate = (
            max(0, old_start - radius),
            min(len(before), old_end + radius),
            max(0, new_start - radius),
            min(len(after), new_end + radius),
        )
        if ranges and candidate[0] <= ranges[-1][1] + radius and candidate[2] <= ranges[-1][3] + radius:
            previous = ranges[-1]
            ranges[-1] = (
                previous[0],
                max(previous[1], candidate[1]),
                previous[2],
                max(previous[3], candidate[3]),
            )
        else:
            ranges.append(candidate)
    if not ranges:
        return before[:_MAX_SECTION_CHARS], after[:_MAX_SECTION_CHARS]
    old_parts = []
    new_parts = []
    for old_start, old_end, new_start, new_end in ranges:
        old_part = before[old_start:old_end]
        new_part = after[new_start:new_end]
        if old_start:
            old_part = "[…]" + old_part
        if old_end < len(before):
            old_part += "[…]"
        if new_start:
            new_part = "[…]" + new_part
        if new_end < len(after):
            new_part += "[…]"
        old_parts.append(old_part)
        new_parts.append(new_part)
    return "\n".join(old_parts), "\n".join(new_parts)


def _changed_fragments(before, after):
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=True)
    old_parts, new_parts = [], []
    for tag, start_old, end_old, start_new, end_new in matcher.get_opcodes():
        if tag != "equal":
            old_parts.append(before[start_old:end_old])
            new_parts.append(after[start_new:end_new])
    return "\n".join(old_parts), "\n".join(new_parts)


def is_minor_wording_change(old_text, new_text, changed_sections):
    old_body, new_body = markdown_body(old_text), markdown_body(new_text)
    if not changed_sections or len(changed_sections) != 1:
        return False
    if len(old_body) + len(new_body) > 80000:
        return False
    old_parsed, new_parsed = parse_markdown(old_text), parse_markdown(new_text)
    if [(normalize_heading(item.text), item.level) for item in old_parsed.headings] != [
        (normalize_heading(item.text), item.level) for item in new_parsed.headings
    ]:
        return False
    old_code = [(item.language, item.content) for item in old_parsed.code_blocks]
    new_code = [(item.language, item.content) for item in new_parsed.code_blocks]
    old_math = [(item.kind, item.content) for item in old_parsed.math_expressions]
    new_math = [(item.kind, item.content) for item in new_parsed.math_expressions]
    if old_code != new_code or old_math != new_math:
        return False
    before, after = _changed_fragments(old_body, new_body)
    if _CRITICAL_TEXT.search(before + "\n" + after):
        return False
    old_normalized = semantic_text(old_body)
    new_normalized = semantic_text(new_body)
    if not old_normalized or not new_normalized:
        return False
    ratio = difflib.SequenceMatcher(a=old_normalized, b=new_normalized, autojunk=True).ratio()
    delta = abs(len(old_normalized) - len(new_normalized))
    changed_size = len(before) + len(after)
    return ratio >= 0.92 and delta <= 40 and changed_size <= 100


def tokens(value):
    return {
        item.casefold()
        for item in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+.#-]{1,}|[\u3400-\u9fff]{2,}", value)
    }
