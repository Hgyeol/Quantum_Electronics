"""Pydantic models shared by the outlook analysis pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from ml.prediction import MLPrediction
from quant.models import QuantSignal

Direction = Literal["positive", "negative", "neutral"]
EvidenceKind = Literal["news", "disclosure", "financial", "market", "quant"]


class DirectionalScoreModel(BaseModel):
    direction: Direction
    score: int = Field(ge=-100, le=100)

    @model_validator(mode="after")
    def _score_matches_direction(self) -> "DirectionalScoreModel":
        if self.direction == "positive" and self.score <= 0:
            raise ValueError("positive direction requires score > 0")
        if self.direction == "negative" and self.score >= 0:
            raise ValueError("negative direction requires score < 0")
        if self.direction == "neutral" and self.score != 0:
            raise ValueError("neutral direction requires score == 0")
        return self


class Evidence(BaseModel):
    evidence_id: str = Field(min_length=1)
    kind: EvidenceKind
    source: str = Field(min_length=1)
    title: str = Field(min_length=1)
    published_at: datetime | None = None
    url: HttpUrl | None = None
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AISignal(DirectionalScoreModel):
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class FinancialSignal(DirectionalScoreModel):
    label: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    value: float | None = None
    period: str | None = None
    reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class FinancialInterpretation(BaseModel):
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    positives: list[str] = Field(default_factory=list)


class AnalysisError(BaseModel):
    source: str = Field(min_length=1)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    recoverable: bool = True


class ScoreBreakdown(BaseModel):
    quant_score: int
    ai_score: int
    financial_score: int
    total_score: int
    direction: Direction

    @model_validator(mode="after")
    def _total_matches_parts(self) -> "ScoreBreakdown":
        expected = self.quant_score + self.ai_score + self.financial_score
        if self.total_score != expected:
            raise ValueError("total_score must equal quant_score + ai_score + financial_score")
        if self.total_score > 0 and self.direction != "positive":
            raise ValueError("positive total_score requires positive direction")
        if self.total_score < 0 and self.direction != "negative":
            raise ValueError("negative total_score requires negative direction")
        if self.total_score == 0 and self.direction != "neutral":
            raise ValueError("zero total_score requires neutral direction")
        return self


class MarketQuote(BaseModel):
    """Live (or latest available) market quote for the stock.

    All values come from a single KIS `inquire-price` call. Optional so the
    field can be omitted when the upstream API fails — the rest of the
    report stays usable.
    """

    price: float = Field(gt=0, description="현재가")
    change: float = Field(description="전일 대비 (절대값)")
    change_rate: float = Field(description="전일 대비 등락률 (%)")
    high: float | None = Field(default=None, description="당일 고가")
    low: float | None = Field(default=None, description="당일 저가")
    volume: int | None = Field(default=None, ge=0, description="누적 거래량")
    w52_high: float | None = Field(default=None, description="52주 최고가")
    w52_low: float | None = Field(default=None, description="52주 최저가")


POSITION_DISCLAIMER = "정보 제공용 계산일 뿐 매수·매도 권유가 아님."


class PositionContext(BaseModel):
    """Deterministic decision-support facts about a user's stock position.

    All fields are facts derived from inputs and live market data. The
    service never advises (buy/sell/hold); see PRD_의사결정보조.md §5.4.
    """

    avg_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    held_since: datetime | None = None
    current_price: float = Field(gt=0)
    holding_days: int | None = Field(default=None, ge=0)
    unrealized_pnl_amount: float
    unrealized_pnl_pct: float
    breakeven_required_pct: float = Field(ge=0)
    distance_to_52w_low_pct: float | None = None
    distance_to_52w_high_pct: float | None = None
    disclaimer: str = POSITION_DISCLAIMER


class OutlookReport(BaseModel):
    stock_code: str = Field(min_length=1)
    stock_name: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str | None = None
    score: ScoreBreakdown
    quant_signals: list[QuantSignal] = Field(default_factory=list)
    ai_signals: list[AISignal] = Field(default_factory=list)
    financial_signals: list[FinancialSignal] = Field(default_factory=list)
    financial_interpretation: FinancialInterpretation | None = None
    ml_prediction: MLPrediction | None = None
    position_context: PositionContext | None = None
    market_quote: MarketQuote | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    errors: list[AnalysisError] = Field(default_factory=list)

    @field_validator("stock_code")
    @classmethod
    def _strip_stock_code(cls, value: str) -> str:
        return value.strip()
