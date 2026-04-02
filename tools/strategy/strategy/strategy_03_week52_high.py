"""
Strategy 03: 52주 신고가 (Week 52 High)

매수 조건: 현재가 > 52주 최고가
매도 조건: 없음 (다른 전략 조합 또는 손절)

Note: 한투 API의 현재가 조회에서 52주 고가/저가를 직접 제공하므로
      일봉 250일 대신 현재가 API를 사용합니다.
"""

from core import data_fetcher
from core.signal import Action
from core.strategy_result import StrategyResult
from strategy.base_strategy import BaseStrategy


class Week52HighStrategy(BaseStrategy):
    """52주 신고가 전략"""

    def __init__(self, breakout_margin: float = 0.0):
        """
        Args:
            breakout_margin: 돌파 마진 (%, 기본: 0)
        """
        self.breakout_margin = breakout_margin

    @property
    def name(self) -> str:
        return "52주 신고가"

    @property
    def required_days(self) -> int:
        return 1  # 현재가 API만 사용하므로 1일

    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        52주 신고가 돌파 결과 반환
        """
        price_info = data_fetcher.get_current_price(stock_code)

        if not price_info:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.HOLD,
                metrics={},
                reason="현재가 조회 실패"
            )

        current_price = price_info.get("price", 0)
        week52_high = price_info.get("w52_high", 0)
        week52_low = price_info.get("w52_low", 0)

        if current_price == 0 or week52_high == 0:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.HOLD,
                metrics={},
                reason="시세 정보 없음"
            )

        threshold = week52_high * (1 + self.breakout_margin / 100)
        ratio_to_high = round(current_price / week52_high * 100, 2)

        metrics = {
            "current_price": current_price,
            "week52_high": week52_high,
            "week52_low": week52_low,
            "threshold": threshold,
            "ratio_to_high": ratio_to_high,      # 52주 고가 대비 현재가 비율 (%)
            "breakout_margin": self.breakout_margin,
        }

        if current_price > threshold:
            return StrategyResult(
                stock_code=stock_code,
                stock_name=stock_name,
                strategy_name=self.name,
                raw_signal=Action.BUY,
                metrics=metrics,
                reason=f"52주 신고가 돌파 ({week52_high:,}원 → {current_price:,}원)"
            )

        return StrategyResult(
            stock_code=stock_code,
            stock_name=stock_name,
            strategy_name=self.name,
            raw_signal=Action.HOLD,
            metrics=metrics,
            reason=f"52주 신고가 미도달 ({ratio_to_high:.1f}%)"
        )
