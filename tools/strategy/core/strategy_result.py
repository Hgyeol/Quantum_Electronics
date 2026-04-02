"""
StrategyResult 클래스 정의

전략이 지표 계산 결과를 반환하는 중간 데이터 구조.
strength 결정은 AI Agent가 담당하므로 여기서는 포함하지 않는다.
"""

from dataclasses import dataclass, field
from datetime import datetime

from core.signal import Action


@dataclass(frozen=True)
class StrategyResult:
    """
    전략 실행 결과 데이터 클래스

    Attributes:
        stock_code: 종목코드 (6자리)
        stock_name: 종목명
        strategy_name: 전략명
        raw_signal: 전략 룰이 계산한 원시 방향 (BUY/SELL/HOLD)
                    — 참고값일 뿐, AI Agent가 반드시 따를 필요 없음
                    — AI는 metrics를 직접 보고 최종 action을 독립적으로 결정해야 함
        metrics: 전략이 계산한 원시 지표값 (AI가 action·strength 판단에 사용)
        reason: 조건 충족/미충족 설명
        timestamp: 결과 생성 시각
    """
    stock_code: str
    stock_name: str
    strategy_name: str
    raw_signal: Action
    metrics: dict
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)

    def is_actionable(self) -> bool:
        """룰 기준 HOLD가 아닌 방향 여부 — AI 최종 판단과 다를 수 있음"""
        return self.raw_signal != Action.HOLD

    def __str__(self) -> str:
        return (
            f"StrategyResult({self.strategy_name} | "
            f"{self.stock_name}[{self.stock_code}] "
            f"raw={self.raw_signal.value.upper()} | "
            f"reason='{self.reason}')"
        )
