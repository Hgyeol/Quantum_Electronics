from langchain.tools import tool

from strategy.strategy_06_breakout_fail import BreakoutFailStrategy

_strategy = BreakoutFailStrategy()


@tool
def breakout_fail(stock_code: str, stock_name: str) -> dict:
    """
    돌파 실패 전략으로 종목을 분석한다 (매도 전용).
    전고점 돌파 후 3일 내 -3% 이상 하락하면 돌파 실패로 판단해 매도 신호를 반환한다.
    metrics에는 최근 고점, 이전 고점, 돌파 여부, 고점 대비 하락률이 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
