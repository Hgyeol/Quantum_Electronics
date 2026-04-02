from langchain.tools import tool

from strategy.strategy_09_mean_reversion import MeanReversionStrategy

_strategy = MeanReversionStrategy()


@tool
def mean_reversion(stock_code: str, stock_name: str) -> dict:
    """
    평균회귀 전략으로 종목을 분석한다.
    5일 이동평균 대비 -3% 이하면 매수 신호, +3% 이상이면 매도 신호를 반환한다.
    단기 평균에서 크게 벗어난 가격이 평균으로 되돌아오는 성질을 이용한다.
    metrics에는 이탈률(%), MA값, 현재 종가, 임계값이 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
