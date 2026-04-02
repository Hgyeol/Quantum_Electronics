"""
전략 베이스 클래스

- 모든 전략은 BaseStrategy를 상속
- 전략은 지표 계산만 수행하고 StrategyResult를 반환
- strength 결정은 AI Agent가 담당 (전략에서 결정 금지)
- 전략은 core.data_fetcher와 core.indicators만 사용
"""

from abc import ABC, abstractmethod

from core.strategy_result import StrategyResult


class BaseStrategy(ABC):
    """
    모든 전략의 베이스 클래스

    - 전략은 다른 전략을 참조하지 않는다
    - 전략 간 상태 공유 금지
    """

    @abstractmethod
    def generate_result(self, stock_code: str, stock_name: str) -> StrategyResult:
        """
        단일 종목에 대한 전략 실행 결과 반환

        Args:
            stock_code: 종목코드 (6자리)
            stock_name: 종목명

        Returns:
            StrategyResult 객체 (지표값 포함, raw_signal은 참고용 — AI가 최종 action 결정)
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """전략명"""
        pass

    @property
    @abstractmethod
    def required_days(self) -> int:
        """필요한 과거 데이터 일수"""
        pass

    def __str__(self) -> str:
        return f"{self.name} (required_days={self.required_days})"
