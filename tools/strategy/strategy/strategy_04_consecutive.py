"""
Strategy 04: 연속 상승/하락 (Consecutive)

매수 조건: N일 연속 상승
매도 조건: N일 연속 하락
"""

from core import data_fetcher, indicators
from core.signal import Action, Signal
from strategy.base_strategy import BaseStrategy


class ConsecutiveStrategy(BaseStrategy):
    """연속 상승/하락 전략"""

    def __init__(
        self,
        buy_days: int = 5,
        sell_days: int = 5,
        strength_base: float = 0.5,
        strength_per_day: float = 0.08,
        strength_max: float = 0.9,
    ):
        """
        Args:
            buy_days: 매수 조건 연속 상승 일수 (기본: 5)
            sell_days: 매도 조건 연속 하락 일수 (기본: 5)
            strength_base: 강도 기본값 (기본: 0.5)
            strength_per_day: 연속일수당 강도 증분 (기본: 0.08)
                - strength = min(strength_max, strength_base + days * strength_per_day)
            strength_max: 강도 최대값 (기본: 0.9)
        """
        self.buy_days = buy_days
        self.sell_days = sell_days
        self.strength_base = strength_base
        self.strength_per_day = strength_per_day
        self.strength_max = strength_max

    @property
    def name(self) -> str:
        return "연속 상승/하락"

    @property
    def required_days(self) -> int:
        return max(self.buy_days, self.sell_days) + 5

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        """
        연속 상승/하락 시그널 생성
        """
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)

        if df.empty or len(df) < self.required_days:
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.HOLD,
                strength=0.0,
                reason="데이터 부족"
            )

        up_days = indicators.calc_consecutive_days(df, "up")
        down_days = indicators.calc_consecutive_days(df, "down")

        # 연속 상승
        if up_days >= self.buy_days:
            strength = min(self.strength_max, self.strength_base + up_days * self.strength_per_day)
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.BUY,
                strength=strength,
                reason=f"{up_days}일 연속 상승"
            )

        # 연속 하락
        if down_days >= self.sell_days:
            strength = min(self.strength_max, self.strength_base + down_days * self.strength_per_day)
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.SELL,
                strength=strength,
                reason=f"{down_days}일 연속 하락"
            )

        return Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.HOLD,
            strength=0.0,
            reason=f"연속 조건 미충족 (상승: {up_days}일, 하락: {down_days}일)"
        )

