"""
Strategy 08: 변동성 확장 (Volatility Expansion)

매수 조건: N일 변동성 최저 + 당일 M% 이상 상승
매도 조건: 없음
"""

from core import data_fetcher, indicators
from core.signal import Action
from core.strategy_result import StrategyResult
from strategy.base_strategy import BaseStrategy


class VolatilityStrategy(BaseStrategy):
    """변동성 확장 전략"""

    def __init__(
        self,
        lookback_days: int = 10,
        breakout_pct: float = 3.0,
        vol_margin: float = 1.1,
    ):
        """
        Args:
            lookback_days: 변동성 조회 기간 (기본: 10일)
            breakout_pct: 돌파 기준 상승률 (%, 기본: 3%)
            vol_margin: 변동성 최저 판단 마진 (기본: 1.1 = 최저 대비 10% 이내)
        """
        self.lookback_days = lookback_days
        self.breakout_pct = breakout_pct
        self.vol_margin = vol_margin

    @property
    def name(self) -> str:
        return "변동성 확장"

    @property
    def required_days(self) -> int:
        return self.lookback_days + 10

    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        변동성 확장 결과 반환
        """
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)

        if df.empty or len(df) < self.lookback_days + 1:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.HOLD,
                metrics={},
                reason="데이터 부족"
            )

        volatility = indicators.calc_volatility(df, self.lookback_days)

        if volatility.empty:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.HOLD,
                metrics={},
                reason="변동성 계산 실패"
            )

        current_vol = volatility.iloc[-1]
        min_vol = volatility.iloc[-self.lookback_days:].min()
        change_pct = indicators.calc_daily_change(df)

        metrics = {
            "current_vol": round(float(current_vol), 6),
            "min_vol": round(float(min_vol), 6),
            "vol_ratio": round(float(current_vol / min_vol), 4) if min_vol > 0 else None,
            "vol_margin": self.vol_margin,
            "change_pct": round(float(change_pct), 2) if change_pct is not None else None,
            "breakout_pct": self.breakout_pct,
            "at_low_vol": bool(current_vol <= min_vol * self.vol_margin),
        }

        if current_vol <= min_vol * self.vol_margin:
            if change_pct is not None and change_pct >= self.breakout_pct:
                return StrategyResult(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    strategy_name=self.name,
                    raw_signal=Action.BUY,
                    metrics=metrics,
                    reason=f"변동성 확장 돌파 +{change_pct:.1f}%"
                )

        return StrategyResult(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=self.name,
            raw_signal=Action.HOLD,
            metrics=metrics,
            reason="변동성 확장 조건 미충족"
        )
