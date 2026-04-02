from langchain.tools import tool

from strategy.strategy_01_golden_cross import GoldenCrossStrategy

_strategy = GoldenCrossStrategy()


@tool
def golden_cross(stock_code: str, stock_name: str) -> dict:
    """
    골든크로스/데드크로스 전략으로 종목을 분석한다.
    단기 이동평균(MA5)이 장기 이동평균(MA20)을 상향 돌파하면 매수 신호,
    하향 돌파하면 매도 신호를 반환한다.
    metrics에는 MA 수치와 크로스 종류(golden/dead/none)가 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
