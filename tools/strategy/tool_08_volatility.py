from langchain.tools import tool

from strategy.strategy_08_volatility import VolatilityStrategy

_strategy = VolatilityStrategy()


@tool
def volatility_expansion(stock_code: str, stock_name: str) -> dict:
    """
    변동성 확장 전략으로 종목을 분석한다.
    10일 변동성이 최저 수준일 때 당일 3% 이상 상승하면 변동성 확장 돌파로 판단해 매수 신호를 반환한다.
    변동성이 낮은 횡보 구간에서 급등이 시작되는 패턴을 포착한다.
    metrics에는 현재 변동성, 최저 변동성, 당일 상승률이 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
