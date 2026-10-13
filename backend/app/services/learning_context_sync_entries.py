"""Safe parsing and rendering of auto-managed learning context entries."""

import json
import re

from backend.app.services.learning_context_service import LearningContextError


ENTRY_START = re.compile(r"(?m)^<!-- learning-context-entry (\{[^\r\n]*\}) -->\r?\n?")
ENTRY_END = "<!-- /learning-context-entry -->"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def layer_path(layer, topic_id):
    if layer in {"active", "important"}:
        return layer + ".md"
    if layer == "topic" and isinstance(topic_id, str) and SLUG.fullmatch(topic_id):
        return "topics/{}.md".format(topic_id)
    raise LearningContextError("AI returned an invalid learning context destination")


def entry_blocks(markdown):
    blocks = []
    for match in ENTRY_START.finditer(markdown):
        close_start = markdown.find(ENTRY_END, match.end())
        if close_start < 0:
            continue
        end = close_start + len(ENTRY_END)
        if markdown[end:end + 1] == "\n":
            end += 1
        try:
            metadata = json.loads(match.group(1))
        except ValueError:
            continue
        if (
            not isinstance(metadata, dict)
            or metadata.get("owner") != "auto"
            or not isinstance(metadata.get("entry_id"), str)
            or not SLUG.fullmatch(metadata["entry_id"])
            or not isinstance(metadata.get("source_headings"), dict)
        ):
            continue
        blocks.append(
            {
                "start": match.start(),
                "end": end,
                "text": markdown[match.start():end],
                "metadata": metadata,
            }
        )
    return blocks


def render_entry(metadata):
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    user_body = metadata.get("user_body")
    if isinstance(user_body, str):
        return (
            "<!-- learning-context-entry {} -->\n"
            "{}\n"
            "{}\n".format(encoded, user_body.rstrip("\n"), ENTRY_END)
        )
    return (
        "<!-- learning-context-entry {} -->\n"
        "### {}\n\n{}\n"
        "{}\n".format(encoded, metadata["title"], metadata["summary"], ENTRY_END)
    )


def visible_entry_content(block):
    lines = block["text"].splitlines()
    body_lines = lines[1:]
    if body_lines and body_lines[-1].strip() == ENTRY_END:
        body_lines.pop()
    body = "\n".join(body_lines).strip("\n")
    heading = re.match(r"^###\s+(.+?)\s*(?:\n|$)", body)
    if heading:
        title = heading.group(1).strip()
        summary = body[heading.end():].strip()
    else:
        title = block["metadata"].get("title", "")
        summary = body.strip()
    return title, summary, body


def replace_entry(memory_files, relative, entry_id, replacement):
    content = memory_files.get(relative, "")
    for block in entry_blocks(content):
        if block["metadata"]["entry_id"] == entry_id:
            memory_files[relative] = content[:block["start"]] + replacement + content[block["end"]:]
            return
    raise LearningContextError("Learning context entry disappeared during synchronization")


def remove_entry(memory_files, relative, entry_id):
    content = memory_files.get(relative, "")
    for block in entry_blocks(content):
        if block["metadata"]["entry_id"] == entry_id:
            memory_files[relative] = content[:block["start"]] + content[block["end"]:]
            return


def append_entry(memory_files, relative, rendered):
    existing = memory_files.get(relative, "")
    separator = "" if not existing or existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
    memory_files[relative] = existing + separator + rendered
