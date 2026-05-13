"""
퀀트 엔진: 5개 신호를 수집해 QuantSignal 리스트로 반환.

PRD §4 — 퀀트 엔진 (사용자 정의 규칙)

신호 구성:
  #1 골든크로스 (MA5/MA20)          +2 / -2 / 0   tools/strategy/strategy/strategy_01
  #2 이격도 (MA20 대비 현재가 %)    +2 / -2 / 0   tools/strategy/strategy/strategy_05
  #3 모멘텀 (60일 수익률)           +1 / -1 / 0   tools/strategy/strategy/strategy_02
  #4 외인 순매수 (3일 누적, 주)     +2 / -2 / 0   tools/domestic_stock/inquire_investor
  #5 거래량 급증 (20일 평균 대비)   +1 / -1 / 0   tools/strategy/core/data_fetcher

  최대 합산 범위: -8 ~ +8
"""

from __future__ import annotations

import logging

from core.signal import Action
from core import data_fetcher
from strategy.strategy_01_golden_cross import GoldenCrossStrategy
from strategy.strategy_02_momentum import MomentumStrategy
from strategy.strategy_05_disparity import DisparityStrategy

from quant.models import QuantSignal
from quant.signals import get_foreign_investor_signal

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# 전략 인스턴스 (모듈 로드 시 1회 생성)
# ──────────────────────────────────────────────────────────────
_golden_cross = GoldenCrossStrategy(short_period=5, long_period=20)
# Disparity thresholds widened so routine swings inside an uptrend are not
# flagged as overbought. Outside [85, 120] still triggers mean-reversion.
_disparity    = DisparityStrategy(period=20, oversold_threshold=85.0, overbought_threshold=120.0)
# Momentum thresholds halved to ±10% so sustained uptrends register a signal
# instead of waiting for a >30% breakout.
_momentum     = MomentumStrategy(lookback_days=60, buy_threshold=0.10, sell_threshold=-0.10)

# StrategyResult.raw_signal → direction 매핑
_DIRECTION = {Action.BUY: "positive", Action.SELL: "negative", Action.HOLD: "neutral"}


# ──────────────────────────────────────────────────────────────
# 내부 신호 생성 함수
# ──────────────────────────────────────────────────────────────

def _signal_from_strategy(
    result,
    label: str,
    buy_score: int,
    value_key: str | None = None,
) -> QuantSignal:
    """StrategyResult → QuantSignal 변환 헬퍼.

    Args:
        result   : StrategyResult
        label    : QuantSignal.label
        buy_score: BUY 시 부여할 점수 (SELL 은 음수, HOLD 는 0)
        value_key: metrics 에서 꺼낼 키 이름
    """
    action = result.raw_signal
    score = (
        buy_score if action == Action.BUY
        else (-buy_score if action == Action.SELL else 0)
    )
    raw_value = result.metrics.get(value_key) if value_key else None
    return QuantSignal(
        label=label,
        direction=_DIRECTION[action],
        score=score,
        value=float(raw_value) if raw_value is not None else None,
        api_used="inquire_daily_itemchartprice",
    )


def _golden_cross_signal(stock_code: str, stock_name: str) -> QuantSignal:
    """Golden/dead cross event = ±2, sustained MA5 vs MA20 state = ±1."""
    label = "골든크로스 (MA5/MA20)"
    api = "inquire_daily_itemchartprice"
    result = _golden_cross.generate_result(stock_code, stock_name)
    metrics = result.metrics or {}
    curr_short = metrics.get("ma_short")
    curr_long = metrics.get("ma_long")
    value = float(curr_short) if curr_short is not None else None

    if result.raw_signal == Action.BUY:
        return QuantSignal(label=label, direction="positive", score=2, value=value, api_used=api)
    if result.raw_signal == Action.SELL:
        return QuantSignal(label=label, direction="negative", score=-2, value=value, api_used=api)

    # HOLD path — reflect the current trend state instead of always 0.
    if curr_short is not None and curr_long is not None:
        if curr_short > curr_long:
            return QuantSignal(label=label, direction="positive", score=1, value=value, api_used=api)
        if curr_short < curr_long:
            return QuantSignal(label=label, direction="negative", score=-1, value=value, api_used=api)
    return QuantSignal(label=label, direction="neutral", score=0, value=value, api_used=api)


def _disparity_signal(stock_code: str, stock_name: str) -> QuantSignal:
    result = _disparity.generate_result(stock_code, stock_name)
    return _signal_from_strategy(result, "이격도 (MA20 대비 현재가 %)", buy_score=2, value_key="disparity")


def _momentum_signal(stock_code: str, stock_name: str) -> QuantSignal:
    result = _momentum.generate_result(stock_code, stock_name)
    return _signal_from_strategy(result, "모멘텀 (60일 수익률)", buy_score=1, value_key="return")


def _volume_spike_signal(
    stock_code: str,
    stock_name: str,
    env_dv: str = "real",
    ma_period: int = 20,
    spike_ratio: float = 2.0,
    dry_ratio: float = 0.5,
) -> QuantSignal:
    """당일 거래량 / 20일 평균 비율로 급증 여부 판단."""
    _label = "거래량 급증 (20일 평균 대비)"
    _api   = "inquire_daily_itemchartprice"

    df = data_fetcher.get_daily_prices(stock_code, ma_period + 1, env_dv)
    if df.empty or len(df) < 2:
        logger.warning(f"거래량 데이터 부족 ({stock_name}[{stock_code}])")
        return QuantSignal(label=_label, direction="neutral", score=0, value=None, api_used=_api)

    avg_vol = df["volume"].iloc[:-1].mean()
    if avg_vol <= 0:
        return QuantSignal(label=_label, direction="neutral", score=0, value=None, api_used=_api)

    ratio = round(df["volume"].iloc[-1] / avg_vol, 2)

    if ratio >= spike_ratio:
        return QuantSignal(label=_label, direction="positive", score=1,  value=ratio, api_used=_api)
    if ratio <= dry_ratio:
        return QuantSignal(label=_label, direction="negative", score=-1, value=ratio, api_used=_api)
    return     QuantSignal(label=_label, direction="neutral",  score=0,  value=ratio, api_used=_api)


# ──────────────────────────────────────────────────────────────
# 퀀트 엔진
# ──────────────────────────────────────────────────────────────

class QuantEngine:
    """
    퀀트 신호를 수집하는 엔진.

    Usage:
        engine = QuantEngine()
        signals = engine.get_signals("005930", "삼성전자")
        total   = engine.get_total_score(signals)
    """

    def get_signals(
        self,
        stock_code: str,
        stock_name: str,
        env_dv: str = "real",
    ) -> list[QuantSignal]:
        """
        5개 퀀트 신호를 수집해 반환.

        개별 신호 생성 중 예외가 발생하면 neutral(score=0) 으로 대체하고
        나머지 신호는 계속 실행됩니다.

        Returns:
            list[QuantSignal] — 항상 5개 반환
        """
        builders = [
            ("골든크로스",   lambda: _golden_cross_signal(stock_code, stock_name)),
            ("이격도",       lambda: _disparity_signal(stock_code, stock_name)),
            ("모멘텀",       lambda: _momentum_signal(stock_code, stock_name)),
            ("외인 순매수",  lambda: get_foreign_investor_signal(stock_code, stock_name, env_dv)),
            ("거래량 급증",  lambda: _volume_spike_signal(stock_code, stock_name, env_dv)),
        ]

        signals: list[QuantSignal] = []
        for label, build in builders:
            try:
                signals.append(build())
            except Exception as exc:
                logger.error(f"[{label}] 신호 생성 실패 ({stock_name}[{stock_code}]): {exc}")
                signals.append(QuantSignal(
                    label=label, direction="neutral", score=0,
                    value=None, api_used="inquire_daily_itemchartprice",
                ))

        return signals

    @staticmethod
    def get_total_score(signals: list[QuantSignal]) -> int:
        """5개 신호의 score 합산 (-8 ~ +8)."""
        return sum(s.score for s in signals)
