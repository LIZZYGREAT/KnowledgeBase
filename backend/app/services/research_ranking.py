"""Readiness-aware ranking for the Research Candidate inbox."""


_READINESS_SCORE = {"high": 1.0, "medium": 0.65, "low": 0.15}


def recommended_score(analysis, weights: tuple[float, float, float]) -> float:
    profile_weight, knowledge_weight, novelty_weight = weights
    profile = analysis.profile_relevance
    knowledge = analysis.knowledge_relevance
    novelty = analysis.novelty_to_library
    if analysis.readiness not in _READINESS_SCORE:
        # Keep older analysis records on the ranking they were created with.
        return (
            profile_weight * profile
            + knowledge_weight * knowledge
            + novelty_weight * novelty
        )
    score = (
        profile_weight * profile
        + knowledge_weight * knowledge
        + novelty_weight * 0.25 * novelty
        + 0.15 * _READINESS_SCORE[analysis.readiness]
    )
    return min(1.0, score)
