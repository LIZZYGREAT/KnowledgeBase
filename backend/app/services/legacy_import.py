"""Translate legacy Markdown into the current canonical metadata shape."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List

import yaml

from backend.app.domain.imports import ImportItem
from backend.app.services.markdown_parser import MarkdownDocument, parse_markdown


@dataclass(frozen=True)
class MarkdownNormalization:
    content: str
    item_metadata: Dict[str, object]


class LegacyImportError(ValueError):
    """Raised when a legacy candidate cannot be normalized safely."""


class LegacyImportAdapter:
    MAINTENANCE_STATUS = "legacy"

    def __init__(
        self,
        repository_root: Path,
        document_candidates: Callable[[str, str], List[dict]],
        slugify: Callable[[str, str], str],
    ):
        self.knowledge_root = Path(repository_root).resolve() / "knowledge"
        self.document_candidates = document_candidates
        self.slugify = slugify

    def normalize_markdown(self, item: ImportItem, content: str) -> MarkdownNormalization:
        parsed = parse_markdown(content)
        if parsed.frontmatter is None:
            generated_metadata = self.generate_metadata(item, parsed)
            newline = "\r\n" if "\r\n" in content else "\n"
            frontmatter = yaml.safe_dump(
                generated_metadata, allow_unicode=True, sort_keys=False
            ).rstrip()
            frontmatter = frontmatter.replace("\n", newline)
            normalized = "{}{}{}{}{}{}{}".format(
                "---", newline, frontmatter, newline, "---", newline * 2, content
            )
            item_metadata = {
                "legacy_frontmatter_generated": True,
                "generated_title": generated_metadata["title"],
                "generated_entity_id": generated_metadata["id"],
            }
            return MarkdownNormalization(normalized, item_metadata)

        return MarkdownNormalization(
            self.apply_defaults(content), {"legacy_frontmatter_generated": False}
        )

    def generate_metadata(self, item: ImportItem, parsed: MarkdownDocument) -> dict:
        title = next(
            (
                heading.text.strip()
                for heading in parsed.headings
                if heading.level == 1 and heading.text.strip()
            ),
            None,
        )
        if not title:
            display_name = item.metadata.get("display_name") or Path(item.path).name
            title = Path(str(display_name)).stem.strip() or "Imported Note"

        content_hash = item.sha256
        entity_id = self.slugify(title, fallback="")
        if not entity_id:
            entity_id = "document-{}".format(content_hash[:12])

        learning_root = self.knowledge_root / "documents" / "learning"
        existing = self.document_candidates(entity_id, title)
        if existing or (learning_root / "{}.md".format(entity_id)).exists():
            for hash_length in range(8, 65, 4):
                candidate_id = "{}-{}".format(entity_id, content_hash[:hash_length])
                id_matches = self.document_candidates(candidate_id, title)
                target_exists = (learning_root / "{}.md".format(candidate_id)).exists()
                if not any(
                    match.get("entity_id") == candidate_id for match in id_matches
                ) and not target_exists:
                    entity_id = candidate_id
                    break
            else:
                raise LegacyImportError("Could not generate a unique Legacy Document ID")

        return {
            "schema_version": 1,
            "id": entity_id,
            "title": title,
            "type": "learning-note",
            "domains": [],
            "topics": [],
            "tags": [],
            "sources": [],
            "review": {"human": {"status": "unreviewed"}},
            "maintenance": {"status": self.MAINTENANCE_STATUS},
            "provenance": {"origin": "imported", "ai_assisted": False},
        }

    @staticmethod
    def apply_defaults(content: str) -> str:
        parsed = parse_markdown(content)
        if parsed.frontmatter is None:
            return content
        value = dict(parsed.frontmatter)
        review = dict(value.get("review") or {})
        human = dict(review.get("human") or {})
        human["status"] = "unreviewed"
        review["human"] = human
        value["review"] = review
        value["maintenance"] = {"status": LegacyImportAdapter.MAINTENANCE_STATUS}
        frontmatter = yaml.safe_dump(value, allow_unicode=True, sort_keys=False).rstrip()
        lines = content.lstrip("\ufeff").splitlines()
        body = "\n".join(lines[parsed.frontmatter_end_line :]).lstrip("\n")
        return "---\n{}\n---\n{}".format(frontmatter, body)
