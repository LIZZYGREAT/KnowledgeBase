"""Versioned Research Agent profiles and global settings."""

from __future__ import annotations

from math import isclose
from typing import Literal, Optional

from pydantic import Field, StrictBool, confloat, conint, model_validator

from backend.app.domain.common import CanonicalModel, NonEmptyText, Slug


ResearchProvider = Literal["arxiv", "openalex", "crossref"]
ResearchBreadth = Literal["strict", "balanced", "explore"]
PositiveInt = conint(strict=True, ge=1)
NonNegativeInt = conint(strict=True, ge=0)
Weight = confloat(strict=True, ge=0.0, le=1.0)


class ResearchLens(CanonicalModel):
    id: Slug
    title: NonEmptyText
    enabled: StrictBool
    priority: Literal["low", "medium", "high"]
    queries: list[NonEmptyText] = Field(min_length=1)
    include_terms: list[NonEmptyText] = Field(default_factory=list)
    exclude_terms: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_terms(self) -> "ResearchLens":
        _require_unique(self.queries, "Lens queries")
        _require_unique(self.include_terms, "Lens include_terms")
        _require_unique(self.exclude_terms, "Lens exclude_terms")
        overlap = _normalized_values(self.include_terms) & _normalized_values(
            self.exclude_terms
        )
        if overlap:
            raise ValueError(
                "Lens include_terms and exclude_terms must not overlap: {}".format(
                    ", ".join(sorted(overlap))
                )
            )
        return self


class ResearchProviders(CanonicalModel):
    discovery: list[Literal["arxiv", "openalex"]] = Field(min_length=1)
    enrichment: list[Literal["openalex", "crossref"]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_providers(self) -> "ResearchProviders":
        if len(self.discovery) != len(set(self.discovery)):
            raise ValueError("Discovery provider names must be unique")
        if len(self.enrichment) != len(set(self.enrichment)):
            raise ValueError("Enrichment provider names must be unique")
        return self


class DynamicRetrieval(CanonicalModel):
    enabled: StrictBool
    scope: Literal["entire-library"]


class ResearchContext(CanonicalModel):
    collections: list[Slug] = Field(default_factory=list)
    documents: list[Slug] = Field(default_factory=list)
    dynamic_retrieval: DynamicRetrieval

    @model_validator(mode="after")
    def validate_unique_references(self) -> "ResearchContext":
        _require_unique(self.collections, "Context collections")
        _require_unique(self.documents, "Context documents")
        return self


class ResearchSchedule(CanonicalModel):
    mode: Literal["daily", "weekly", "manual"]


class ResearchSearch(CanonicalModel):
    breadth: ResearchBreadth
    initial_lookback_days: PositiveInt
    max_catchup_days: PositiveInt
    max_candidates_per_run: PositiveInt


class ResearchInbox(CanonicalModel):
    max_new_candidates: NonNegativeInt


class ResearchAIAnalysis(CanonicalModel):
    enabled: StrictBool
    provider: Literal["deepseek"]


class ResearchProfile(CanonicalModel):
    schema_version: Literal[1]
    id: Slug
    title: NonEmptyText
    description: Optional[NonEmptyText] = None
    enabled: StrictBool
    lenses: list[ResearchLens] = Field(min_length=1)
    exclude_terms: list[NonEmptyText] = Field(default_factory=list)
    providers: ResearchProviders
    context: ResearchContext
    schedule: ResearchSchedule
    search: ResearchSearch
    inbox: ResearchInbox
    ai_analysis: ResearchAIAnalysis

    @model_validator(mode="after")
    def validate_profile(self) -> "ResearchProfile":
        lens_ids = [lens.id for lens in self.lenses]
        if len(lens_ids) != len(set(lens_ids)):
            raise ValueError("Research Profile lens IDs must be unique")
        _require_unique(self.exclude_terms, "Profile exclude_terms")
        return self


class ResearchProviderSettings(CanonicalModel):
    timeout_seconds: PositiveInt
    max_retries: NonNegativeInt


class ResearchRuntimeSettings(CanonicalModel):
    slice_days: PositiveInt
    overlap_hours: NonNegativeInt
    retry_cooldown_minutes: PositiveInt


class ResearchAnalysisSettings(CanonicalModel):
    max_context_entities: PositiveInt
    timeout_seconds: PositiveInt


class ResearchRankingWeights(CanonicalModel):
    profile_relevance_weight: Weight
    knowledge_relevance_weight: Weight
    novelty_weight: Weight

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ResearchRankingWeights":
        total = (
            self.profile_relevance_weight
            + self.knowledge_relevance_weight
            + self.novelty_weight
        )
        if not isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError("Research ranking weights must sum to 1.0")
        return self


class ResearchRankingSettings(CanonicalModel):
    strict: ResearchRankingWeights
    balanced: ResearchRankingWeights
    explore: ResearchRankingWeights


class ResearchGlobalConfig(CanonicalModel):
    schema_version: Literal[1]
    providers: ResearchProviderSettings
    runtime: ResearchRuntimeSettings
    analysis: ResearchAnalysisSettings
    ranking: ResearchRankingSettings


def _normalized_values(values: list[str]) -> set[str]:
    return {" ".join(value.split()).casefold() for value in values}


def _require_unique(values: list[str], label: str) -> None:
    normalized = [" ".join(value.split()).casefold() for value in values]
    if len(normalized) != len(set(normalized)):
        raise ValueError("{} must be unique after normalization".format(label))
