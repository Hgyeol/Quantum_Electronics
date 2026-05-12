"""Runtime ML prediction models for API responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MLFeatureContribution(BaseModel):
    feature: str
    value: float
    contribution: float
    direction: str


class MLPrediction(BaseModel):
    target: str = "next_day_up"
    probability: float = Field(ge=0.0, le=1.0)
    model: str
    features_version: str
    rule_score: int | None = None
    rule_direction: str | None = None
    explanation: str | None = None
    top_contributions: list[MLFeatureContribution] = Field(default_factory=list)
