from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class OHLCVBar(BaseModel):
    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float


class SupportResistanceLevel(BaseModel):
    price: float
    level_type: Literal["support", "resistance"]
    strength: Literal["weak", "medium", "strong"]
    touch_count: int
    last_tested_date: str | None = None
    source: str = "swing"  # "swing" | "ma20" | "ma60" | "bb_lower" | "bb_upper"


class TechnicalIndicators(BaseModel):
    rsi: float | None = None
    rsi_zone: Literal["oversold", "neutral", "overbought"]
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    macd_crossover: Literal["bullish", "bearish", "none"]
    bb_upper: float | None = None
    bb_middle: float | None = None
    bb_lower: float | None = None
    bb_position: Literal["above_upper", "near_upper", "middle", "near_lower", "below_lower"]
    stoch_k: float | None = None
    stoch_d: float | None = None
    stoch_zone: Literal["oversold", "neutral", "overbought"]


class EntryExitSignal(BaseModel):
    action: Literal["buy", "hold", "sell"]
    confidence: Literal["low", "medium", "high"]
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    primary_target: float | None = None
    secondary_target: float | None = None
    stop_loss: float | None = None
    risk_reward_ratio: float | None = None
    reasoning: list[str]


class ChartAnalysis(BaseModel):
    stock_code: str
    stock_name: str | None = None
    generated_at: datetime
    current_price: float
    analysis_period_days: int
    ohlcv: list[OHLCVBar] = []
    support_levels: list[SupportResistanceLevel]
    resistance_levels: list[SupportResistanceLevel]
    indicators: TechnicalIndicators
    signal: EntryExitSignal
    disclaimer: str = "이 분석은 투자 참고용이며, 매수·매도 권고가 아닙니다."
