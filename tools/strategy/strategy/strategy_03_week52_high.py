"""
Strategy 03: 52주 신고가 (Week 52 High)

매수 조건: 현재가 > 52주 최고가
매도 조건: 없음 (다른 전략 조합 또는 손절)

Note: 한투 API의 현재가 조회에서 52주 고가/저가를 직접 제공하므로
      일봉 250일 대신 현재가 API를 사용합니다.
"""

from core import data_fetcher
from core.signal import Action, Signal
from strategy.base_strategy import BaseStrategy


class Week52HighStrategy(BaseStrategy):
    """52주 신고가 전략"""

    def __init__(self, breakout_margin: float = 0.0, buy_strength: float = 0.85):
        """
        Args:
            breakout_margin: 돌파 마진 (%, 기본: 0)
            buy_strength: 매수 시그널 강도 (기본: 0.85)
        """
        self.breakout_margin = breakout_margin
        self.buy_strength = buy_strength

    @property
    def name(self) -> str:
        return "52주 신고가"

    @property
    def required_days(self) -> int:
        return 1  # 현재가 API만 사용하므로 1일

    def generate_signal(self, stock_code: str, stock_name: str) -> Signal:
        """
        52주 신고가 돌파 시그널 생성
        
        한투 API의 현재가 조회(FHKST01010100)에서 52주 고가를 직접 제공합니다.
        """
        # 현재가 API 조회 (52주 고가/저가 포함)
        price_info = data_fetcher.get_current_price(stock_code)

        if not price_info:
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.HOLD,
                strength=0.0,
                reason="현재가 조회 실패"
            )

        current_price = price_info.get("price", 0)
        week52_high = price_info.get("w52_high", 0)

        if current_price == 0 or week52_high == 0:
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.HOLD,
                strength=0.0,
                reason="시세 정보 없음"
            )

        # 돌파 마진 적용
        threshold = week52_high * (1 + self.breakout_margin / 100)

        if current_price > threshold:
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.BUY,
                strength=self.buy_strength,
                reason=f"52주 신고가 돌파 ({week52_high:,}원 → {current_price:,}원)"
            )

        # 52주 고가 대비 현재가 비율
        ratio = (current_price / week52_high) * 100

        return Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.HOLD,
            strength=0.0,
            reason=f"52주 신고가 미도달 (현재: {current_price:,}원, 고가: {week52_high:,}원, {ratio:.1f}%)"
        )

