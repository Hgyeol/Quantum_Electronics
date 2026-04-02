"""
Strategy 10: 추세 필터 (Trend Filter)

매수 조건: 종가 > MA(60) AND 전일 대비 상승
매도 조건: 종가 < MA(60) AND 전일 대비 하락
"""

from core import data_fetcher, indicators
from core.signal import Action
from core.strategy_result import StrategyResult
from strategy.base_strategy import BaseStrategy


class TrendFilterStrategy(BaseStrategy):
    """추세 필터 전략"""

    def __init__(self, ma_period: int = 60):
        """
        Args:
            ma_period: 추세 판단 이동평균 기간 (기본: 60일)
        """
        self.ma_period = ma_period

    @property
    def name(self) -> str:
        return "추세 필터"

    @property
    def required_days(self) -> int:
        return self.ma_period + 10

    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        추세 필터 결과 반환
        """
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)

        if df.empty or len(df) < self.ma_period:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                action=Action.HOLD,
                metrics={},
                reason="데이터 부족"
            )

        ma = indicators.calc_ma(df, self.ma_period)
        current_close = indicators.get_latest_close(df)
        prev_close = indicators.get_prev_close(df)
        ma_value = ma.iloc[-1]

        if current_close is None or prev_close is None:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                action=Action.HOLD,
                metrics={},
                reason="지표 계산 실패"
            )

        above_ma = current_close > ma_value
        daily_up = current_close > prev_close
        gap_from_ma = (current_close - ma_value) / ma_value * 100

        metrics = {
            "ma": round(float(ma_value), 2),
            "close": float(current_close),
            "prev_close": float(prev_close),
            "above_ma": above_ma,
            "daily_up": daily_up,
            "gap_from_ma_pct": round(float(gap_from_ma), 2),  # MA 대비 이격 (%)
            "ma_period": self.ma_period,
        }

        if above_ma and daily_up:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                action=Action.BUY,
                metrics=metrics,
                reason=f"추세 상승: MA{self.ma_period}({ma_value:,.0f}) 위 + 상승"
            )

        if not above_ma and not daily_up:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                action=Action.SELL,
                metrics=metrics,
                reason=f"추세 하락: MA{self.ma_period}({ma_value:,.0f}) 아래 + 하락"
            )

        return StrategyResult(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=self.name,
            action=Action.HOLD,
            metrics=metrics,
            reason="추세 조건 미충족"
        )
