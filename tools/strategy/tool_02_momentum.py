from langchain.tools import tool

from strategy.strategy_02_momentum import MomentumStrategy

_strategy = MomentumStrategy()


@tool
def momentum(stock_code: str, stock_name: str) -> dict:
    """
    모멘텀 전략으로 종목을 분석한다.
    60일 수익률이 30% 이상이면 매수 신호, -20% 이하면 매도 신호를 반환한다.
    metrics에는 수익률, 매수/매도 임계값이 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
