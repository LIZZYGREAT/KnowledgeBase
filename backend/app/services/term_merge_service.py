"""Preview and coordinate canonical Term merges with Runtime relation updates."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from backend.app.repositories.term_candidate_repository import TermCandidateRepository
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.resolution import normalize_key
from backend.app.services.term_registry import TermRegistry


class TermMergeConflict(RuntimeError):
    """Raised when a Term merge would lose or ambiguously resolve user data."""


@dataclass(frozen=True)
class TermMergePreview:
    survivor_term_id: str
    loser_term_ids: tuple[str, ...]
    final_title: str
    aliases: tuple[str, ...]
    loser_bodies_not_merged: tuple[str, ...]


@dataclass(frozen=True)
class TermMergeResult:
    survivor_term_id: str
    loser_term_ids: tuple[str, ...]
    final_title: str
    aliases: tuple[str, ...]
    loser_bodies_not_merged: tuple[str, ...]
    commit_revision: str
    warnings: tuple[str, ...] = ()


class TermMergeService:
    def __init__(
        self,
        repository_root: Path,
        connection: sqlite3.Connection,
        candidate_repository: TermCandidateRepository,
        publisher,
        indexer,
    ):
        self.repository_root = Path(repository_root).resolve()
        self.knowledge_root = self.repository_root / "knowledge"
        self.connection = connection
        self.candidate_repository = candidate_repository
        self.publisher = publisher
        self.indexer = indexer

    def preview(
        self,
        survivor_term_id: str,
        loser_term_ids: list[str],
        final_title: str,
    ) -> TermMergePreview:
        if not isinstance(survivor_term_id, str) or not survivor_term_id.strip():
            raise ValueError("A survivor Term id is required")
        if not isinstance(final_title, str) or not final_title.strip():
            raise ValueError("A final Term title is required")
        if isinstance(loser_term_ids, (str, bytes)) or not loser_term_ids:
            raise ValueError("Select at least one loser Term")
        if any(not isinstance(item, str) or not item.strip() for item in loser_term_ids):
            raise ValueError("Loser Term ids must be non-empty strings")
        if len(loser_term_ids) != len(set(loser_term_ids)):
            raise ValueError("Loser Term ids must be unique")
        if survivor_term_id in loser_term_ids:
            raise ValueError("The survivor cannot also be a loser")

        registry = TermRegistry.load(self.knowledge_root / "terms")
        terms = {term.id: term for term in registry.terms}
        if survivor_term_id not in terms:
            raise LookupError("Survivor Term '{}' does not exist".format(survivor_term_id))
        missing = [term_id for term_id in loser_term_ids if term_id not in terms]
        if missing:
            raise LookupError("Loser Term does not exist: {}".format(", ".join(missing)))

        selected_ids = {survivor_term_id, *loser_term_ids}
        final_title = final_title.strip()
        aliases = merge_aliases(
            terms[survivor_term_id], [terms[term_id] for term_id in loser_term_ids], final_title
        )
        outside_aliases: dict[str, str] = {}
        for term in registry.terms:
            if term.id in selected_ids:
                continue
            for value in (term.id, term.title, *term.aliases):
                key = normalize_key(value)
                if key:
                    outside_aliases.setdefault(key, term.id)
        for value in (final_title, *aliases):
            collision = outside_aliases.get(normalize_key(value))
            if collision:
                raise TermMergeConflict(
                    "Merge title or alias '{}' already resolves to Term '{}'".format(
                        value, collision
                    )
                )

        for term_id in selected_ids:
            drafts = self.publisher.draft_service.list_for_target("term", term_id)
            if drafts:
                raise TermMergeConflict(
                    "Term '{}' has an active Draft; publish or discard it before merging".format(
                        term_id
                    )
                )

        bodyful_losers = tuple(
            term_id
            for term_id in loser_term_ids
            if _term_body(
                (self.knowledge_root / "terms" / "{}.md".format(term_id)).read_text(
                    encoding="utf-8"
                )
            ).strip()
        )
        return TermMergePreview(
            survivor_term_id=survivor_term_id,
            loser_term_ids=tuple(loser_term_ids),
            final_title=final_title,
            aliases=aliases,
            loser_bodies_not_merged=bodyful_losers,
        )

    def merge(
        self,
        survivor_term_id: str,
        loser_term_ids: list[str],
        final_title: str,
        confirm_loser_bodies_not_merged: bool = False,
    ) -> TermMergeResult:
        preview = self.preview(survivor_term_id, loser_term_ids, final_title)
        if preview.loser_bodies_not_merged and not confirm_loser_bodies_not_merged:
            raise TermMergeConflict(
                "Confirm that loser Term bodies will not be copied into the survivor"
            )

        canonical_merge = None
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            merged_at = _utc_now()
            self.candidate_repository.migrate_merged_terms(
                list(preview.loser_term_ids), preview.survivor_term_id, merged_at
            )
            canonical_merge = self.publisher.merge_terms(
                preview.survivor_term_id,
                list(preview.loser_term_ids),
                preview.final_title,
                list(preview.aliases),
            )
            self.connection.commit()
        except Exception as error:
            self.connection.rollback()
            if canonical_merge is not None:
                try:
                    self.publisher.rollback_term_merge(canonical_merge)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "Term merge failed and its canonical rollback also failed: {}".format(
                            rollback_error
                        )
                    ) from error
            raise

        warnings = []
        try:
            self.indexer.full_rebuild()
        except Exception as error:
            warnings.append(
                "Index rebuild failed; run `python tools/kb.py rebuild`: {}".format(error)
            )
        return TermMergeResult(
            survivor_term_id=preview.survivor_term_id,
            loser_term_ids=preview.loser_term_ids,
            final_title=preview.final_title,
            aliases=preview.aliases,
            loser_bodies_not_merged=preview.loser_bodies_not_merged,
            commit_revision=canonical_merge.commit_revision,
            warnings=tuple(warnings),
        )


def merge_aliases(survivor, losers, final_title: str) -> tuple[str, ...]:
    """Return stable, normalized, de-duplicated aliases for a proposed merge."""
    final_key = normalize_key(final_title)
    seen = set()
    aliases = []
    values = list(survivor.aliases)
    values.extend(loser.title for loser in losers)
    values.extend(alias for loser in losers for alias in loser.aliases)
    for value in values:
        clean = value.strip()
        key = normalize_key(clean)
        if not clean or not key or key == final_key or key in seen:
            continue
        seen.add(key)
        aliases.append(clean)
    # Keep each former id verbatim even when its normalized form matches the title.
    # Term resolution can then preserve exact old Wiki Link targets as well as titles.
    for loser in losers:
        if normalize_key(loser.id) != final_key and loser.id not in aliases:
            aliases.append(loser.id)
    return tuple(aliases)


def _term_body(content: str) -> str:
    parsed = parse_markdown(content)
    if parsed.frontmatter is None or parsed.frontmatter_end_line is None:
        raise ValueError("Term file has invalid frontmatter")
    return "".join(content.splitlines(keepends=True)[parsed.frontmatter_end_line :])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
