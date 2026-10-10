"""Bounded historical discovery using approved Note content and linked Source dates."""

from datetime import datetime, timezone

from backend.app.domain.document import DocumentMetadata
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.research_watermark import ResearchSearchPlan, ResearchSearchSlice


def research_anchor_year(root, profile, sources):
    years = []
    phrases = [profile.title, *[q for lens in profile.lenses if lens.enabled for q in lens.queries]]
    for path in (root / "knowledge" / "documents").rglob("*.md"):
        if path.is_symlink():
            continue
        content = path.read_text(encoding="utf-8")
        parsed = parse_markdown(content)
        metadata = DocumentMetadata.model_validate(parsed.frontmatter)
        if not metadata.review or not metadata.review.human or metadata.review.human.status != "approved":
            continue
        body = "\n".join(content.splitlines()[parsed.frontmatter_end_line or 0:])
        if not body.strip() or not (
            metadata.id in profile.context.documents
            or any(phrase.casefold() in body.casefold() for phrase in phrases)
        ):
            continue
        for source_id in metadata.sources:
            source = sources.get(source_id)
            if source is not None and source.year is not None:
                years.append(source.year)
    return max(years) if years else profile.search.history_seed_year


def historical_plan(repository, profile, query, provider, anchor, now):
    """One annual window per stream per Run, with an independent progress key."""
    key = "history:" + query.query_key
    state = repository.get_state(profile.id, query.lens_id, provider, key)
    previous = datetime.fromisoformat(state.completed_through) if state and state.completed_through else None
    checkpoint = repository.history_checkpoint(profile.id, query.lens_id, provider, key)
    start = datetime.fromisoformat(checkpoint["start"]) if checkpoint else previous or datetime(max(1000, anchor - 2), 1, 1, tzinfo=timezone.utc)
    # A new approved Note can extend this ceiling; a Term never invents a date.
    ceiling = min(now, datetime(min(9999, anchor + 3), 1, 1, tzinfo=timezone.utc))
    end = min(ceiling, datetime(start.year + 1, 1, 1, tzinfo=timezone.utc))
    return ResearchSearchPlan(
        profile_id=profile.id, lens_id=query.lens_id, provider=provider,
        query_key=key, query_text=query.text,
        slices=(ResearchSearchSlice(start, end),) if start < end else (),
        manual=False, previous_watermark=previous,
    )
