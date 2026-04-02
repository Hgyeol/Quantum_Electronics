from langchain.tools import tool

from strategy.strategy_07_strong_close import StrongCloseStrategy

_strategy = StrongCloseStrategy()


@tool
def strong_close(stock_code: str, stock_name: str) -> dict:
    """
    강한 종가 전략으로 종목을 분석한다 (장마감 후 실행 권장).
    당일 종가가 고가-저가 범위의 상위 80% 이상에 위치하면 매수 신호를 반환한다.
    종가가 고가에 가까울수록 당일 매수세가 강했음을 의미한다.
    metrics에는 종가 위치 비율, 고가/저가/종가가 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
