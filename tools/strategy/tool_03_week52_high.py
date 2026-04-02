from langchain.tools import tool

from strategy.strategy_03_week52_high import Week52HighStrategy

_strategy = Week52HighStrategy()


@tool
def week52_high(stock_code: str, stock_name: str) -> dict:
    """
    52주 신고가 전략으로 종목을 분석한다.
    현재가가 52주 최고가를 돌파하면 매수 신호를 반환한다.
    metrics에는 현재가, 52주 고가/저가, 고가 대비 현재가 비율이 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
