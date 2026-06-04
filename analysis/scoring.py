"""Deterministic score aggregation for quant, AI, and financial signals."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from analysis.models import AISignal, Direction, FinancialSignal, ScoreBreakdown
from quant.models import QuantSignal


class ScoredSignal(Protocol):
    score: int


AI_SCORE_MIN = -8
AI_SCORE_MAX = 8


def direction_from_score(score: int) -> Direction:
    if score > 0:
        return "positive"
    if score < 0:
        return "negative"
    return "neutral"


def sum_scores(signals: Iterable[ScoredSignal]) -> int:
    return sum(signal.score for signal in signals)


def aggregate_ai_score(signals: Iterable[AISignal]) -> int:
    """다중 AI 신호 합산 시에도 ±8 범위 유지를 위해 평균 후 클램프.
    LLM이 prompt 제약으로 이미 -8~+8 범위에서 출력하므로 별도 가중치는 불필요.
    """
    ai_signals = list(signals)
    if not ai_signals:
        return 0
    avg = round(sum_scores(ai_signals) / len(ai_signals))
    return max(AI_SCORE_MIN, min(AI_SCORE_MAX, avg))


def combine_signals(
    quant_signals: Iterable[QuantSignal] = (),
    ai_signals: Iterable[AISignal] = (),
    financial_signals: Iterable[FinancialSignal] = (),
) -> ScoreBreakdown:
    quant_score = sum_scores(quant_signals)
    ai_score = aggregate_ai_score(ai_signals)
    financial_score = sum_scores(financial_signals)
    total_score = quant_score + ai_score + financial_score

    return ScoreBreakdown(
        quant_score=quant_score,
        ai_score=ai_score,
        financial_score=financial_score,
        total_score=total_score,
        direction=direction_from_score(total_score),
    )
