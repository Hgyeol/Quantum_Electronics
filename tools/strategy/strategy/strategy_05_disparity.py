"""
Strategy 05: 이격도 (Disparity)

매수 조건: 이격도 < 90 (과매도)
매도 조건: 이격도 > 110 (과매수)
"""

from core import data_fetcher, indicators
from core.signal import Action
from core.strategy_result import StrategyResult
from strategy.base_strategy import BaseStrategy


class DisparityStrategy(BaseStrategy):
    """이격도 전략"""

    def __init__(
        self,
        period: int = 20,
        oversold_threshold: float = 90.0,
        overbought_threshold: float = 110.0,
    ):
        """
        Args:
            period: 이동평균 기간 (기본: 20)
            oversold_threshold: 과매도 기준 (기본: 90)
            overbought_threshold: 과매수 기준 (기본: 110)
        """
        self.period = period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold

    @property
    def name(self) -> str:
        return "이격도"

    @property
    def required_days(self) -> int:
        return self.period + 10

    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        이격도 기반 결과 반환
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

        disparity = indicators.calc_disparity(df, self.period)
        current_disparity = disparity.iloc[-1]
        ma_value = indicators.calc_ma(df, self.period).iloc[-1]

        metrics = {
            "disparity": round(float(current_disparity), 2),
            "ma": round(float(ma_value), 2),
            "period": self.period,
            "oversold_threshold": self.oversold_threshold,
            "overbought_threshold": self.overbought_threshold,
            "deviation_from_oversold": round(float(self.oversold_threshold - current_disparity), 2),
            "deviation_from_overbought": round(float(current_disparity - self.overbought_threshold), 2),
        }

        if current_disparity < self.oversold_threshold:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.BUY,
                metrics=metrics,
                reason=f"이격도 {current_disparity:.1f} (과매도 기준 {self.oversold_threshold})"
            )

        if current_disparity > self.overbought_threshold:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.SELL,
                metrics=metrics,
                reason=f"이격도 {current_disparity:.1f} (과매수 기준 {self.overbought_threshold})"
            )

        return StrategyResult(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=self.name,
            raw_signal=Action.HOLD,
            metrics=metrics,
            reason=f"이격도 {current_disparity:.1f} (중립)"
        )
