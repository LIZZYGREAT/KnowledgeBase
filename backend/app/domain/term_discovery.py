"""Runtime configuration and history for Term Discovery."""

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, constr, model_validator

from backend.app.domain.term_runtime import TermDiscoveryAssessment


NonEmptyText = constr(strict=True, strip_whitespace=True, min_length=1)
DiscoveryLane = Literal["concept", "entity", "vocabulary"]


class TermDiscoverySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled_lanes: list[DiscoveryLane] = Field(
        default_factory=lambda: ["concept", "entity", "vocabulary"]
    )
    daily_max_new: int = Field(default=5, ge=1, le=12)
    lane_capacities: Dict[str, int] = Field(
        default_factory=lambda: {"concept": 5, "entity": 4, "vocabulary": 6}
    )
    source_preferences: list[NonEmptyText] = Field(default_factory=list, max_length=100)
    focus_override: Optional[constr(strict=True, strip_whitespace=True, max_length=500)] = None

    @model_validator(mode="after")
    def validate_settings(self):
        if len(self.enabled_lanes) != len(set(self.enabled_lanes)):
            raise ValueError("enabled_lanes must not contain duplicates")
        if set(self.lane_capacities) != {"concept", "entity", "vocabulary"}:
            raise ValueError("lane_capacities must define all three Discovery lanes")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12
            for value in self.lane_capacities.values()
        ):
            raise ValueError("lane capacities must be integers from 1 through 12")
        if len(self.source_preferences) != len(set(self.source_preferences)):
            raise ValueError("source_preferences must not contain duplicates")
        return self


class TermDiscoveryRunItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: NonEmptyText
    run_id: NonEmptyText
    lane: DiscoveryLane
    source_id: NonEmptyText
    mention: NonEmptyText
    outcome: Literal["created", "stretch", "duplicate", "filtered", "rejected", "error"]
    candidate_id: Optional[NonEmptyText] = None
    assessment: TermDiscoveryAssessment
    rationale: NonEmptyText
    context_excerpt: NonEmptyText
    created_at: NonEmptyText


class TermDiscoveryRun(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: NonEmptyText
    trigger: Literal["manual", "scheduled"]
    status: Literal["success", "partial", "failed", "skipped_capacity", "skipped_disabled"]
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    lane_budgets: Dict[str, int] = Field(default_factory=dict)
    raw_counts: Dict[str, int] = Field(default_factory=dict)
    filtered_counts: Dict[str, int] = Field(default_factory=dict)
    candidate_count: int = Field(default=0, ge=0)
    started_at: NonEmptyText
    finished_at: Optional[NonEmptyText] = None
    error_summary: Optional[str] = None
    items: list[TermDiscoveryRunItem] = Field(default_factory=list)


class TermDiscoveryState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    settings: TermDiscoverySettings
    open_count: int = Field(ge=0)
    global_capacity: int = Field(ge=0)
    daily_remaining: int = Field(ge=0)
    lane_open: Dict[str, int]
    lane_capacity: Dict[str, int]
    last_run: Optional[TermDiscoveryRun] = None
