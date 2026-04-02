"""
Strategy 06: 돌파 실패 (Breakout Fail)

매수 조건: 없음 (매도 전용 전략)
매도 조건: 전고점 돌파 후 N일 내 하락
"""

from core import data_fetcher, indicators
from core.signal import Action
from core.strategy_result import StrategyResult
from strategy.base_strategy import BaseStrategy


class BreakoutFailStrategy(BaseStrategy):
    """돌파 실패 전략 (매도 전용)"""

    def __init__(
        self,
        lookback_days: int = 20,
        fail_within_days: int = 3,
        fail_threshold: float = -0.03,
    ):
        """
        Args:
            lookback_days: 전고점 조회 기간 (기본: 20일)
            fail_within_days: 돌파 후 확인 기간 (기본: 3일)
            fail_threshold: 하락 기준 (기본: -3%)
        """
        self.lookback_days = lookback_days
        self.fail_within_days = fail_within_days
        self.fail_threshold = fail_threshold

    @property
    def name(self) -> str:
        return "돌파 실패"

    @property
    def required_days(self) -> int:
        return self.lookback_days + self.fail_within_days + 5

    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        돌파 실패 결과 반환
        """
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)

        if df.empty or len(df) < self.required_days:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.HOLD,
                metrics={},
                reason="데이터 부족"
            )

        recent_high = df["high"].iloc[-self.fail_within_days:].max()
        prev_data = df.iloc[:-self.fail_within_days]
        prev_high = prev_data["high"].max()

        metrics = {
            "recent_high": float(recent_high),
            "prev_high": float(prev_high),
            "breakout_occurred": bool(recent_high > prev_high),
            "lookback_days": self.lookback_days,
            "fail_within_days": self.fail_within_days,
            "fail_threshold": self.fail_threshold,
        }

        if recent_high > prev_high:
            current_close = indicators.get_latest_close(df)

            if current_close is None:
                return StrategyResult(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    strategy_name=self.name,
                    raw_signal=Action.HOLD,
                    metrics=metrics,
                    reason="지표 계산 실패"
                )

            change_from_high = (current_close - recent_high) / recent_high
            metrics["change_from_high"] = round(float(change_from_high), 4)
            metrics["change_from_high_pct"] = round(float(change_from_high) * 100, 2)

            if change_from_high <= self.fail_threshold:
                return StrategyResult(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    strategy_name=self.name,
                    raw_signal=Action.SELL,
                    metrics=metrics,
                    reason=f"돌파 실패: 고점 대비 {change_from_high*100:.1f}%"
                )

        return StrategyResult(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=self.name,
            raw_signal=Action.HOLD,
            metrics=metrics,
            reason="돌파 실패 조건 미충족"
        )
