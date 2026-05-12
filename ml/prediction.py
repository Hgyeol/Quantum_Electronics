"""Runtime ML prediction models for API responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MLPrediction(BaseModel):
    target: str = "next_day_up"
    probability: float = Field(ge=0.0, le=1.0)
    model: str
    features_version: str
