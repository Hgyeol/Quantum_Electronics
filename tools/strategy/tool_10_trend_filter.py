from langchain.tools import tool

from strategy.strategy_10_trend_filter import TrendFilterStrategy

_strategy = TrendFilterStrategy()


@tool
def trend_filter(stock_code: str, stock_name: str) -> dict:
    """
    추세 필터 전략으로 종목을 분석한다.
    종가가 MA(60) 위에 있고 전일 대비 상승하면 매수 신호,
    MA(60) 아래에 있고 전일 대비 하락하면 매도 신호를 반환한다.
    중장기 추세 방향과 단기 방향이 일치하는 구간을 포착한다.
    metrics에는 MA값, 종가, MA 대비 이격률(%), 추세 방향이 포함된다.
    raw_signal은 룰 기반 참고값이며, 최종 판단은 AI가 metrics를 보고 결정한다.
    """
    result = _strategy.generate_result(stock_code, stock_name)
    return {
        "strategy": result.strategy_name,
        "raw_signal": result.raw_signal.value,
        "metrics": result.metrics,
        "reason": result.reason,
    }
