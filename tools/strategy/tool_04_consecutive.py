from langchain.tools import tool

from strategy.strategy_04_consecutive import ConsecutiveStrategy

_strategy = ConsecutiveStrategy()


@tool
def consecutive(stock_code: str, stock_name: str) -> dict:
    """
    연속 상승/하락 전략으로 종목을 분석한다.
    5일 연속 상승이면 매수 신호, 5일 연속 하락이면 매도 신호를 반환한다.
    metrics에는 현재 연속 상승일수, 연속 하락일수, 임계값이 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
