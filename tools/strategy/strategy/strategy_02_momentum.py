"""
Strategy 02: 모멘텀 (Momentum)

매수 조건: 60일 수익률 상위 (30% 이상 상승)
매도 조건: 60일 수익률 하위 (-20% 이하 하락)
"""

from core import data_fetcher, indicators
from core.signal import Action
from core.strategy_result import StrategyResult
from strategy.base_strategy import BaseStrategy


class MomentumStrategy(BaseStrategy):
    """모멘텀 전략"""

    def __init__(
        self,
        lookback_days: int = 60,
        buy_threshold: float = 0.30,
        sell_threshold: float = -0.20,
    ):
        """
        Args:
            lookback_days: 수익률 계산 기간 (기본: 60일)
            buy_threshold: 매수 기준 수익률 (기본: 30%)
            sell_threshold: 매도 기준 수익률 (기본: -20%)
        """
        self.lookback_days = lookback_days
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold

    @property
    def name(self) -> str:
        return "모멘텀"

    @property
    def required_days(self) -> int:
        return self.lookback_days + 5

    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        모멘텀 기반 결과 반환
        """
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)

        if df.empty or len(df) < self.lookback_days:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.HOLD,
                metrics={},
                reason="데이터 부족"
            )

        returns = indicators.calc_returns(df, self.lookback_days)
        latest_return = returns.iloc[-1]

        metrics = {
            "return": round(float(latest_return), 4),
            "return_pct": round(float(latest_return) * 100, 2),
            "lookback_days": self.lookback_days,
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
        }

        if latest_return >= self.buy_threshold:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.BUY,
                metrics=metrics,
                reason=f"{self.lookback_days}일 수익률 +{latest_return*100:.1f}%"
            )

        if latest_return <= self.sell_threshold:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.SELL,
                metrics=metrics,
                reason=f"{self.lookback_days}일 수익률 {latest_return*100:.1f}%"
            )

        return StrategyResult(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=self.name,
            raw_signal=Action.HOLD,
            metrics=metrics,
            reason=f"중립 구간 ({latest_return*100:.1f}%)"
        )
