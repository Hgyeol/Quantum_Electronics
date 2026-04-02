"""
Strategy 09: 평균회귀 (Mean Reversion)

매수 조건: N일 평균 대비 -M% 이하
매도 조건: N일 평균 대비 +M% 이상
"""

from core import data_fetcher, indicators
from core.signal import Action
from core.strategy_result import StrategyResult
from strategy.base_strategy import BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    """평균회귀 전략"""

    def __init__(
        self,
        period: int = 5,
        buy_threshold: float = -3.0,
        sell_threshold: float = 3.0,
    ):
        """
        Args:
            period: 이동평균 기간 (기본: 5일)
            buy_threshold: 매수 이탈 기준 (%, 기본: -3%)
            sell_threshold: 매도 이탈 기준 (%, 기본: +3%)
        """
        self.period = period
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    @property
    def name(self) -> str:
        return "평균회귀"

    @property
    def required_days(self) -> int:
        return self.period + 5

    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        평균회귀 결과 반환
        """
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)

        if df.empty or len(df) < self.period:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.HOLD,
                metrics={},
                reason="데이터 부족"
            )

        ma = indicators.calc_ma(df, self.period)
        current_close = indicators.get_latest_close(df)
        ma_value = ma.iloc[-1]

        if current_close is None or ma_value == 0:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.HOLD,
                metrics={},
                reason="지표 계산 실패"
            )

        deviation = (current_close - ma_value) / ma_value * 100

        metrics = {
            "deviation_pct": round(float(deviation), 2),
            "ma": round(float(ma_value), 2),
            "close": float(current_close),
            "period": self.period,
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
        }

        if deviation <= self.buy_threshold:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.BUY,
                metrics=metrics,
                reason=f"평균 대비 {deviation:.1f}% 이탈 (매수)"
            )

        if deviation >= self.sell_threshold:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.SELL,
                metrics=metrics,
                reason=f"평균 대비 +{deviation:.1f}% 이탈 (매도)"
            )

        return StrategyResult(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=self.name,
            raw_signal=Action.HOLD,
            metrics=metrics,
            reason=f"평균 대비 {deviation:.1f}% (중립)"
        )
