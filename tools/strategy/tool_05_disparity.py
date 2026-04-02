from langchain.tools import tool

from strategy.strategy_05_disparity import DisparityStrategy

_strategy = DisparityStrategy()


@tool
def disparity(stock_code: str, stock_name: str) -> dict:
    """
    이격도 전략으로 종목을 분석한다.
    20일 이동평균 대비 이격도가 90 미만이면 과매도(매수 신호),
    110 초과이면 과매수(매도 신호)를 반환한다.
    metrics에는 이격도 수치, MA값, 임계값 대비 이탈 폭이 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
