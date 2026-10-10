"""Generate and manage the human-controlled Research Candidate inbox."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal, Optional
import uuid

from backend.app.domain.research import ResearchLens, ResearchProfile
from backend.app.domain.research_runtime import (
    ResearchCandidateRecord,
    ResearchCandidateStatus,
    ResearchDismissReason,
    ResearchWorkAnalysisRecord,
)
from backend.app.repositories.research_candidate_repository import (
    ResearchCandidateRepository,
)


@dataclass(frozen=True)
class CandidateGenerationResult:
    outcome: Literal["created", "existing", "filtered", "inbox_full", "budget_reached", "stretch_budget_reached"]
    candidate: Optional[ResearchCandidateRecord] = None


class ResearchCandidateService:
    def __init__(
        self,
        repository: ResearchCandidateRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.repository = repository
        self.clock = clock

    def remaining_capacity(self, profile: ResearchProfile) -> int:
        return max(
            0,
            profile.inbox.max_new_candidates
            - self.repository.count_new(profile.id),
        )

    def remaining_daily_recommendations(self, profile: ResearchProfile) -> int:
        counts = self._daily_exposure_counts(profile, self._now())
        return max(0, profile.search.max_recommendations_per_day - counts["total"])

    def generate(
        self,
        analysis: ResearchWorkAnalysisRecord,
        profile: ResearchProfile,
        matched_lens: ResearchLens,
    ) -> CandidateGenerationResult:
        with self.repository.transactions.write_transaction():
            return self._generate(analysis, profile, matched_lens)

    def _generate(self, analysis, profile, matched_lens):
        _validate_profile_analysis(profile, matched_lens, analysis)
        if analysis.outcome == "filtered":
            return CandidateGenerationResult("filtered")

        existing = self.repository.get_for_work(analysis.work_id, profile.id)
        if existing is not None:
            return CandidateGenerationResult("existing", existing)

        now = self._now()
        output = analysis.analysis
        if output.profile_relevance < profile.search.min_profile_relevance or output.novelty_to_library < profile.search.min_information_gain:
            return CandidateGenerationResult("filtered")
        work_row = self.repository.connection.execute("SELECT abstract FROM research_works WHERE id=?", (analysis.work_id,)).fetchone()
        abstract = " ".join((work_row["abstract"] or "").casefold().split()) if work_row else ""
        if len(abstract) >= 200:
            previous = self.repository.connection.execute(
                "SELECT w.abstract FROM research_candidates c JOIN research_works w ON w.id=c.work_id WHERE c.profile_id=? AND c.status!='dismissed'",
                (profile.id,),
            ).fetchall()
            if any(" ".join((row["abstract"] or "").casefold().split()) == abstract for row in previous):
                return CandidateGenerationResult("filtered")
        counts = self._daily_exposure_counts(profile, now)
        if counts["total"] >= profile.search.max_recommendations_per_day:
            return CandidateGenerationResult("budget_reached")
        if output.readiness == "low" and counts["stretch"] >= profile.search.max_stretch_per_day:
            return CandidateGenerationResult("stretch_budget_reached")
        candidate = ResearchCandidateRecord(
            id=uuid.uuid4().hex,
            work_id=analysis.work_id,
            profile_id=profile.id,
            status="new",
            primary_lens_id=matched_lens.id,
            analysis_id=analysis.id,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
        persisted, created, full = self.repository.create_if_capacity(
            candidate,
            max_new_candidates=profile.inbox.max_new_candidates,
        )
        if full:
            return CandidateGenerationResult("inbox_full")
        if persisted is None:
            raise RuntimeError("Candidate creation returned no record without reaching capacity")
        return CandidateGenerationResult(
            "created" if created else "existing", persisted
        )

    def _daily_exposure_counts(self, profile: ResearchProfile, now: datetime):
        # Count exposures across all decisions so rejecting cards cannot refill today's budget.
        counts = self.repository.connection.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN json_extract(a.analysis_json, '$.readiness')='low' THEN 1 ELSE 0 END) AS stretch
               FROM research_candidates c JOIN research_work_analyses a ON a.id=c.analysis_id
               WHERE c.profile_id=? AND c.created_at >= ?""",
            (profile.id, now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()),
        ).fetchone()
        return {"total": counts["total"], "stretch": counts["stretch"] or 0}

    def shortlist(
        self, candidate_id: str, user_note: Optional[str] = None
    ) -> ResearchCandidateRecord:
        note = _normalize_note(user_note)
        now = self._now()
        return self.repository.transition(
            candidate_id=candidate_id,
            allowed_statuses=("new", "shortlisted"),
            status="shortlisted",
            now=now,
            user_note=note,
            update_user_note=user_note is not None,
        )

    def dismiss(
        self,
        candidate_id: str,
        reason: Optional[ResearchDismissReason] = None,
        user_note: Optional[str] = None,
    ) -> ResearchCandidateRecord:
        if reason not in {
            None,
            "not_relevant",
            "already_known",
            "too_redundant",
            "not_interested",
            "other",
        }:
            raise ValueError("Unsupported Research Candidate dismiss reason")
        note = _normalize_note(user_note)
        now = self._now()
        return self.repository.transition(
            candidate_id=candidate_id,
            allowed_statuses=("new", "shortlisted", "dismissed"),
            status="dismissed",
            now=now,
            dismiss_reason=reason,
            user_note=note,
            update_user_note=user_note is not None,
            decided_at=now,
        )

    def restore(
        self, candidate_id: str, max_new_candidates: int
    ) -> ResearchCandidateRecord:
        """Return a dismissed Candidate to the Inbox and keep its note."""
        return self.repository.restore_if_capacity(
            candidate_id,
            max_new_candidates=max_new_candidates,
            now=self._now(),
        )

    def update_user_note(
        self, candidate_id: str, user_note: Optional[str]
    ) -> ResearchCandidateRecord:
        return self.repository.update_user_note(
            candidate_id, _normalize_note(user_note), self._now()
        )

    def mark_viewed(self, candidate_id: str) -> ResearchCandidateRecord:
        return self.repository.mark_viewed(candidate_id, self._now())

    def _now(self) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Research Candidate clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


def _validate_profile_analysis(
    profile: ResearchProfile,
    matched_lens: ResearchLens,
    analysis: ResearchWorkAnalysisRecord,
) -> None:
    canonical_lens = next(
        (lens for lens in profile.lenses if lens.id == matched_lens.id), None
    )
    if canonical_lens is None or canonical_lens != matched_lens:
        raise ValueError("Matched Lens does not belong to the Research Profile")
    if not matched_lens.enabled:
        raise ValueError("Cannot create a Candidate from a disabled Lens")
    if analysis.profile_id != profile.id:
        raise ValueError("Research Analysis belongs to a different Profile")


def _normalize_note(user_note: Optional[str]) -> Optional[str]:
    if user_note is None:
        return None
    if not isinstance(user_note, str):
        raise ValueError("Research Candidate user note must be text")
    note = user_note.strip()
    if len(note) > 4_000:
        raise ValueError("Research Candidate user note cannot exceed 4000 characters")
    return note or None
