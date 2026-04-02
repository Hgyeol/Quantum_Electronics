"""
Strategy 04: 연속 상승/하락 (Consecutive)

매수 조건: N일 연속 상승
매도 조건: N일 연속 하락
"""

from core import data_fetcher, indicators
from core.signal import Action
from core.strategy_result import StrategyResult
from strategy.base_strategy import BaseStrategy


class ConsecutiveStrategy(BaseStrategy):
    """연속 상승/하락 전략"""

    def __init__(self, buy_days: int = 5, sell_days: int = 5):
        """
        Args:
            buy_days: 매수 조건 연속 상승 일수 (기본: 5)
            sell_days: 매도 조건 연속 하락 일수 (기본: 5)
        """
        self.buy_days = buy_days
        self.sell_days = sell_days

    @property
    def name(self) -> str:
        return "연속 상승/하락"

    @property
    def required_days(self) -> int:
        return max(self.buy_days, self.sell_days) + 5

    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        연속 상승/하락 결과 반환
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

        up_days = indicators.calc_consecutive_days(df, "up")
        down_days = indicators.calc_consecutive_days(df, "down")

        metrics = {
            "up_days": up_days,
            "down_days": down_days,
            "buy_days_threshold": self.buy_days,
            "sell_days_threshold": self.sell_days,
        }

        if up_days >= self.buy_days:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.BUY,
                metrics=metrics,
                reason=f"{up_days}일 연속 상승"
            )

        if down_days >= self.sell_days:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.SELL,
                metrics=metrics,
                reason=f"{down_days}일 연속 하락"
            )

        return StrategyResult(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=self.name,
            raw_signal=Action.HOLD,
            metrics=metrics,
            reason=f"연속 조건 미충족 (상승: {up_days}일, 하락: {down_days}일)"
        )
