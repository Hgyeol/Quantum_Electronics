"""
Strategy 08: 변동성 확장 (Volatility Expansion)

매수 조건: N일 변동성 최저 + 당일 M% 이상 상승
매도 조건: 없음
"""

from core import data_fetcher, indicators
from core.signal import Action, Signal
from strategy.base_strategy import BaseStrategy


class VolatilityStrategy(BaseStrategy):
    """변동성 확장 전략"""

    def __init__(
        self,
        lookback_days: int = 10,
        breakout_pct: float = 3.0,
        vol_margin: float = 1.1,
        buy_strength: float = 0.75,
    ):
        """
        Args:
            lookback_days: 변동성 조회 기간 (기본: 10일)
            breakout_pct: 돌파 기준 상승률 (%, 기본: 3%)
            vol_margin: 변동성 최저 판단 마진 (기본: 1.1 = 최저 대비 10% 이내)
            buy_strength: 매수 시그널 강도 (기본: 0.75)
        """
        self.lookback_days = lookback_days
        self.breakout_pct = breakout_pct
        self.vol_margin = vol_margin
        self.buy_strength = buy_strength

    @property
    def name(self) -> str:
        return "변동성 확장"

    @property
    def required_days(self) -> int:
        return self.lookback_days + 10

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        """
        변동성 확장 시그널 생성
        """
        df = data_fetcher.get_daily_prices(stock_code, self.required_days)

        if df.empty or len(df) < self.lookback_days + 1:
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.HOLD,
                strength=0.0,
                reason="데이터 부족"
            )

        volatility = indicators.calc_volatility(df, self.lookback_days)

        if volatility.empty:
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.HOLD,
                strength=0.0,
                reason="변동성 계산 실패"
            )

        current_vol = volatility.iloc[-1]
        min_vol = volatility.iloc[-self.lookback_days:].min()

        # 변동성 최저 상태 확인
        if current_vol <= min_vol * self.vol_margin:
            change_pct = indicators.calc_daily_change(df)

            if change_pct is not None and change_pct >= self.breakout_pct:
                return Signal(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    action=Action.BUY,
                    strength=self.buy_strength,
                    reason=f"변동성 확장 돌파 +{change_pct:.1f}%"
                )

        return Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.HOLD,
            strength=0.0,
            reason="변동성 확장 조건 미충족"
        )

