"""Screener condition evaluation against the SQLite cache."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from services.screener_db import get_all_stock_codes, get_investor, get_prices
from services.ranking import (
    fetch_volume_power_rank,
    fetch_near_new_highlow_rank,
    fetch_upper_limit_stocks,
    RankItem,
)

logger = logging.getLogger(__name__)


@dataclass
class ScreenerResult:
    stock_code: str
    stock_name: str
    close: int
    volume: int
    matched_conditions: list[str]


def _ma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _ema(values: list[float], period: int) -> list[float]:
    """EMA series. 길이 = len(values) - period + 1."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(values[:period]) / period]  # SMA seed
    for v in values[period:]:
        out.append((v - out[-1]) * k + out[-1])
    return out


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal_p: int = 9) -> tuple[list[float], list[float], list[float]]:
    """(macd_line, signal_line, histogram) 반환. 모두 동일 길이로 끝 정렬."""
    if len(closes) < slow + signal_p:
        return [], [], []
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    pad = len(ema_fast) - len(ema_slow)
    ema_fast = ema_fast[pad:]
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal_p)
    pad2 = len(macd_line) - len(signal_line)
    macd_aligned = macd_line[pad2:]
    histogram = [m - s for m, s in zip(macd_aligned, signal_line)]
    return macd_aligned, signal_line, histogram


def _lrs(values: list[float], period: int) -> list[float]:
    """Rolling linear regression slope."""
    if len(values) < period:
        return []
    out = []
    x_mean = (period - 1) / 2
    x_var = sum((i - x_mean) ** 2 for i in range(period))
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        y_mean = sum(window) / period
        slope = sum((j - x_mean) * (window[j] - y_mean) for j in range(period)) / x_var
        out.append(slope)
    return out


def _tsf(values: list[float], period: int) -> list[float]:
    """Time series forecast (rolling linear regression value at last bar)."""
    if len(values) < period:
        return []
    out = []
    x_mean = (period - 1) / 2
    x_var = sum((i - x_mean) ** 2 for i in range(period))
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        y_mean = sum(window) / period
        slope = sum((j - x_mean) * (window[j] - y_mean) for j in range(period)) / x_var
        intercept = y_mean - slope * x_mean
        out.append(intercept + slope * (period - 1))
    return out


def _obv(closes: list[float], volumes: list[float]) -> list[float]:
    if not closes:
        return []
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def _signal_line(series: list[float], period: int = 9) -> list[float]:
    """SMA 시그널 라인 (series 기반)."""
    if len(series) < period:
        return []
    return [sum(series[i - period + 1 : i + 1]) / period for i in range(period - 1, len(series))]


def check_volume_surge(stock_code: str, threshold: float = 2.0) -> bool:
    """오늘 거래량 > threshold × 20일 평균 거래량."""
    rows = get_prices(stock_code, days=22)
    if len(rows) < 2:
        return False
    avg_vol = sum(r["volume"] for r in rows[:-1]) / len(rows[:-1])
    if avg_vol <= 0:
        return False
    return rows[-1]["volume"] >= avg_vol * threshold


def check_golden_cross(stock_code: str) -> bool:
    """5일 MA가 20일 MA를 아래에서 위로 돌파 (전일 < 당일)."""
    rows = get_prices(stock_code, days=25)
    closes = [r["close"] for r in rows]
    if len(closes) < 22:
        return False
    ma5_today  = _ma(closes, 5)
    ma20_today = _ma(closes, 20)
    ma5_prev   = _ma(closes[:-1], 5)
    ma20_prev  = _ma(closes[:-1], 20)
    if any(v is None for v in [ma5_today, ma20_today, ma5_prev, ma20_prev]):
        return False
    return ma5_prev < ma20_prev and ma5_today >= ma20_today  # type: ignore[operator]


def check_frgn_consecutive_buy(stock_code: str, days: int = 3) -> bool:
    """외국인 N일 연속 순매수 > 0."""
    rows = get_investor(stock_code, days=days)
    if len(rows) < days:
        return False
    return all(r["frgn_ntby_qty"] > 0 for r in rows[-days:])


def check_orgn_consecutive_buy(stock_code: str, days: int = 3) -> bool:
    """기관 N일 연속 순매수 > 0."""
    rows = get_investor(stock_code, days=days)
    if len(rows) < days:
        return False
    return all(r["orgn_ntby_qty"] > 0 for r in rows[-days:])


def check_price_surge(stock_code: str, threshold: float = 5.0) -> bool:
    """당일 등락률 > threshold%."""
    rows = get_prices(stock_code, days=2)
    if len(rows) < 2:
        return False
    prev_close = rows[-2]["close"]
    today_close = rows[-1]["close"]
    if prev_close <= 0:
        return False
    return (today_close - prev_close) / prev_close * 100 >= threshold


# ── 강한 매수 신호 ───────────────────────────────────────────────────────────


def check_consecutive_bull(stock_code: str, days: int = 3) -> bool:
    """N일 연속 양봉 (close > open)."""
    rows = get_prices(stock_code, days=days)
    if len(rows) < days:
        return False
    return all(r["close"] > r["open"] for r in rows[-days:])


def check_consecutive_up(stock_code: str, days: int = 3) -> bool:
    """N일 연속 종가 상승 (close[t] > close[t-1])."""
    rows = get_prices(stock_code, days=days + 1)
    if len(rows) < days + 1:
        return False
    closes = [r["close"] for r in rows[-(days + 1):]]
    return all(closes[i] > closes[i - 1] for i in range(1, len(closes)))


def check_higher_high_low(stock_code: str, days: int = 3) -> bool:
    """N일 연속 고가와 저가 동시 상승."""
    rows = get_prices(stock_code, days=days + 1)
    if len(rows) < days + 1:
        return False
    recent = rows[-(days + 1):]
    return all(
        recent[i]["high"] > recent[i - 1]["high"] and recent[i]["low"] > recent[i - 1]["low"]
        for i in range(1, len(recent))
    )


# ── 매수 신호 ────────────────────────────────────────────────────────────────


def check_ma_alignment(stock_code: str) -> bool:
    """이동평균 정배열: MA5 > MA20 > MA60."""
    rows = get_prices(stock_code, days=60)
    if len(rows) < 60:
        return False
    closes = [r["close"] for r in rows]
    ma5 = _ma(closes, 5)
    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    if ma5 is None or ma20 is None or ma60 is None:
        return False
    return ma5 > ma20 > ma60


def check_break_prev_high(stock_code: str) -> bool:
    """오늘 종가 > 전일 고가."""
    rows = get_prices(stock_code, days=2)
    if len(rows) < 2:
        return False
    return rows[-1]["close"] > rows[-2]["high"]


def check_new_high_5d(stock_code: str) -> bool:
    """5일 신고가 갱신 (오늘 고가가 직전 5일 최고)."""
    rows = get_prices(stock_code, days=5)
    if len(rows) < 5:
        return False
    highs = [r["high"] for r in rows]
    return highs[-1] >= max(highs)


def check_volume_golden_cross(stock_code: str) -> bool:
    """거래량 MA5가 MA20을 상향 돌파."""
    rows = get_prices(stock_code, days=22)
    if len(rows) < 22:
        return False
    vols = [r["volume"] for r in rows]
    vma5_today = _ma(vols, 5)
    vma20_today = _ma(vols, 20)
    vma5_prev = _ma(vols[:-1], 5)
    vma20_prev = _ma(vols[:-1], 20)
    if None in (vma5_today, vma20_today, vma5_prev, vma20_prev):
        return False
    return vma5_prev < vma20_prev and vma5_today >= vma20_today  # type: ignore[operator]


def check_macd_signal_cross(stock_code: str) -> bool:
    """MACD 라인이 시그널 라인을 상향 돌파."""
    rows = get_prices(stock_code, days=50)
    if len(rows) < 40:
        return False
    closes = [r["close"] for r in rows]
    macd, signal, _ = _macd(closes)
    if len(macd) < 2 or len(signal) < 2:
        return False
    return macd[-2] <= signal[-2] and macd[-1] > signal[-1]


def check_macd_osc_up(stock_code: str) -> bool:
    """MACD 히스토그램 3일 연속 상승."""
    rows = get_prices(stock_code, days=50)
    if len(rows) < 40:
        return False
    closes = [r["close"] for r in rows]
    _, _, hist = _macd(closes)
    if len(hist) < 4:
        return False
    h = hist[-4:]
    return h[1] > h[0] and h[2] > h[1] and h[3] > h[2]


def check_lrs_signal_up(stock_code: str, period: int = 14, signal_p: int = 9) -> bool:
    """LRS(선형회귀 기울기)가 시그널선을 상향 돌파."""
    rows = get_prices(stock_code, days=period + signal_p + 2)
    if len(rows) < period + signal_p + 2:
        return False
    closes = [r["close"] for r in rows]
    lrs = _lrs(closes, period)
    sig = _signal_line(lrs, signal_p)
    if len(sig) < 2:
        return False
    pad = len(lrs) - len(sig)
    lrs_aligned = lrs[pad:]
    return lrs_aligned[-2] <= sig[-2] and lrs_aligned[-1] > sig[-1]


def check_tsf_signal_up(stock_code: str, period: int = 14, signal_p: int = 9) -> bool:
    """TSF(시계열 예측치)가 시그널선을 상향 돌파."""
    rows = get_prices(stock_code, days=period + signal_p + 2)
    if len(rows) < period + signal_p + 2:
        return False
    closes = [r["close"] for r in rows]
    tsf = _tsf(closes, period)
    sig = _signal_line(tsf, signal_p)
    if len(sig) < 2:
        return False
    pad = len(tsf) - len(sig)
    tsf_aligned = tsf[pad:]
    return tsf_aligned[-2] <= sig[-2] and tsf_aligned[-1] > sig[-1]


def check_volume_osc_up(stock_code: str, short: int = 5, long: int = 20) -> bool:
    """거래량 오실레이터((VMA5 - VMA20) / VMA20 × 100)가 0선을 상향 돌파."""
    rows = get_prices(stock_code, days=long + 2)
    if len(rows) < long + 2:
        return False
    vols = [r["volume"] for r in rows]
    vs_t = _ma(vols, short)
    vl_t = _ma(vols, long)
    vs_p = _ma(vols[:-1], short)
    vl_p = _ma(vols[:-1], long)
    if None in (vs_t, vl_t, vs_p, vl_p) or vl_t == 0 or vl_p == 0:
        return False
    osc_t = (vs_t - vl_t) / vl_t * 100  # type: ignore[operator]
    osc_p = (vs_p - vl_p) / vl_p * 100  # type: ignore[operator]
    return osc_p <= 0 and osc_t > 0


def check_price_osc_up(stock_code: str, short: int = 12, long: int = 26, signal_p: int = 9) -> bool:
    """가격 오실레이터(% 형태)가 시그널선을 상향 돌파."""
    rows = get_prices(stock_code, days=long + signal_p + 2)
    if len(rows) < long + signal_p + 2:
        return False
    closes = [r["close"] for r in rows]
    posc = []
    for i in range(long - 1, len(closes)):
        ms = sum(closes[i - short + 1 : i + 1]) / short
        ml = sum(closes[i - long + 1 : i + 1]) / long
        posc.append(0 if ml == 0 else (ms - ml) / ml * 100)
    sig = _signal_line(posc, signal_p)
    if len(sig) < 2:
        return False
    pad = len(posc) - len(sig)
    posc_a = posc[pad:]
    return posc_a[-2] <= sig[-2] and posc_a[-1] > sig[-1]


def check_mao_up(stock_code: str, short: int = 5, long: int = 20) -> bool:
    """MAO(MA5 - MA20)가 0선을 상향 돌파."""
    rows = get_prices(stock_code, days=long + 2)
    if len(rows) < long + 2:
        return False
    closes = [r["close"] for r in rows]
    ms_t = _ma(closes, short)
    ml_t = _ma(closes, long)
    ms_p = _ma(closes[:-1], short)
    ml_p = _ma(closes[:-1], long)
    if None in (ms_t, ml_t, ms_p, ml_p):
        return False
    return (ms_p - ml_p) <= 0 and (ms_t - ml_t) > 0  # type: ignore[operator]


def check_mao_signal_up(stock_code: str, short: int = 5, long: int = 20, signal_p: int = 9) -> bool:
    """MAO가 시그널선(MAO의 9일 MA)을 상향 돌파."""
    rows = get_prices(stock_code, days=long + signal_p + 2)
    if len(rows) < long + signal_p + 2:
        return False
    closes = [r["close"] for r in rows]
    mao = []
    for i in range(long - 1, len(closes)):
        ms = sum(closes[i - short + 1 : i + 1]) / short
        ml = sum(closes[i - long + 1 : i + 1]) / long
        mao.append(ms - ml)
    sig = _signal_line(mao, signal_p)
    if len(sig) < 2:
        return False
    pad = len(mao) - len(sig)
    mao_a = mao[pad:]
    return mao_a[-2] <= sig[-2] and mao_a[-1] > sig[-1]


def check_momentum_up(stock_code: str, period: int = 10) -> bool:
    """Momentum(close[t] - close[t-N])이 3일 연속 상승."""
    rows = get_prices(stock_code, days=period + 4)
    if len(rows) < period + 4:
        return False
    closes = [r["close"] for r in rows]
    mom = [closes[i] - closes[i - period] for i in range(period, len(closes))]
    if len(mom) < 4:
        return False
    return mom[-3] > mom[-4] and mom[-2] > mom[-3] and mom[-1] > mom[-2]


def check_roc_up(stock_code: str, period: int = 10) -> bool:
    """ROC((close[t] - close[t-N]) / close[t-N] × 100)이 3일 연속 상승."""
    rows = get_prices(stock_code, days=period + 4)
    if len(rows) < period + 4:
        return False
    closes = [r["close"] for r in rows]
    roc = []
    for i in range(period, len(closes)):
        if closes[i - period] == 0:
            roc.append(0)
        else:
            roc.append((closes[i] - closes[i - period]) / closes[i - period] * 100)
    if len(roc) < 4:
        return False
    return roc[-3] > roc[-4] and roc[-2] > roc[-3] and roc[-1] > roc[-2]


def check_sonar_signal_up(stock_code: str, period: int = 9, signal_p: int = 9) -> bool:
    """Sonar(N일 EMA의 변화율)이 시그널선을 상향 돌파."""
    rows = get_prices(stock_code, days=period * 3 + signal_p)
    if len(rows) < period * 2 + signal_p + 2:
        return False
    closes = [r["close"] for r in rows]
    ema = _ema(closes, period)
    if len(ema) < period + 1:
        return False
    sonar = []
    for i in range(period, len(ema)):
        if ema[i - period] == 0:
            sonar.append(0)
        else:
            sonar.append((ema[i] - ema[i - period]) / ema[i - period] * 100)
    sig = _signal_line(sonar, signal_p)
    if len(sig) < 2:
        return False
    pad = len(sonar) - len(sig)
    sonar_a = sonar[pad:]
    return sonar_a[-2] <= sig[-2] and sonar_a[-1] > sig[-1]


def check_obv_up(stock_code: str, days: int = 5) -> bool:
    """OBV가 N일 연속 상승."""
    rows = get_prices(stock_code, days=30)
    if len(rows) < days + 1:
        return False
    closes = [r["close"] for r in rows]
    vols = [float(r["volume"]) for r in rows]
    obv = _obv(closes, vols)
    if len(obv) < days + 1:
        return False
    recent = obv[-(days + 1):]
    return all(recent[i] > recent[i - 1] for i in range(1, len(recent)))


def check_obv_uturn(stock_code: str) -> bool:
    """OBV U턴: 직전 5일 하락 후 최근 2일 연속 상승."""
    rows = get_prices(stock_code, days=30)
    if len(rows) < 8:
        return False
    closes = [r["close"] for r in rows]
    vols = [float(r["volume"]) for r in rows]
    obv = _obv(closes, vols)
    if len(obv) < 8:
        return False
    declining = obv[-7] > obv[-3]
    rising = obv[-3] < obv[-2] < obv[-1]
    return declining and rising


_CONDITION_FN = {
    "volume_surge": check_volume_surge,
    "golden_cross": check_golden_cross,
    "frgn_buy": check_frgn_consecutive_buy,
    "orgn_buy": check_orgn_consecutive_buy,
    "price_surge": check_price_surge,
    "consecutive_bull": check_consecutive_bull,
    "consecutive_up": check_consecutive_up,
    "higher_high_low": check_higher_high_low,
    "ma_alignment": check_ma_alignment,
    "break_prev_high": check_break_prev_high,
    "new_high_5d": check_new_high_5d,
    "volume_golden_cross": check_volume_golden_cross,
    "macd_signal_cross": check_macd_signal_cross,
    "macd_osc_up": check_macd_osc_up,
    "lrs_signal_up": check_lrs_signal_up,
    "tsf_signal_up": check_tsf_signal_up,
    "volume_osc_up": check_volume_osc_up,
    "price_osc_up": check_price_osc_up,
    "mao_up": check_mao_up,
    "mao_signal_up": check_mao_signal_up,
    "momentum_up": check_momentum_up,
    "roc_up": check_roc_up,
    "sonar_signal_up": check_sonar_signal_up,
    "obv_up": check_obv_up,
    "obv_uturn": check_obv_uturn,
}

# 실시간 KIS API 기반 조건 (per-stock DB 조회 아님)
_LIVE_CONDITIONS: frozenset[str] = frozenset({"volume_power", "near_high", "upper_limit"})

_CONDITION_LABEL = {
    "volume_surge": "거래량 급등",
    "golden_cross": "골든크로스 (MA5/MA20)",
    "frgn_buy": "외국인 연속 순매수",
    "orgn_buy": "기관 연속 순매수",
    "price_surge": "급등주",
    "volume_power": "체결강도 상위",
    "near_high": "신고가 근접",
    "upper_limit": "상한가 포착",
    "consecutive_bull": "연속 양봉 (3일+)",
    "consecutive_up": "연속 상승 (3일+)",
    "higher_high_low": "고가/저가 동시 상승",
    "ma_alignment": "이동평균 정배열 (5/20/60)",
    "break_prev_high": "전일 고가 돌파",
    "new_high_5d": "5일 신고가 갱신",
    "volume_golden_cross": "거래량 골든크로스",
    "macd_signal_cross": "MACD 시그널 크로스",
    "macd_osc_up": "MACD Osc 상승기류",
    "lrs_signal_up": "LRS 시그널 돌파",
    "tsf_signal_up": "TSF 시그널 돌파",
    "volume_osc_up": "Volume Osc 상승돌파",
    "price_osc_up": "Price Osc 상승돌파",
    "mao_up": "MAO 상승돌파",
    "mao_signal_up": "MAO Signal 돌파",
    "momentum_up": "Momentum 상승추세",
    "roc_up": "ROC 상승추세",
    "sonar_signal_up": "Sonar 시그널 돌파",
    "obv_up": "OBV 상승추세",
    "obv_uturn": "OBV U턴",
}


def _fetch_live_items(condition: str) -> list[RankItem]:
    try:
        if condition == "volume_power":
            return fetch_volume_power_rank(50)
        if condition == "near_high":
            return fetch_near_new_highlow_rank("high", 50)
        if condition == "upper_limit":
            return fetch_upper_limit_stocks()
    except Exception as exc:
        logger.warning("Live condition fetch failed [%s]: %s", condition, exc)
    return []


def run_screener(
    conditions: list[str],
    name_map: dict[str, str],
    params: dict[str, dict] | None = None,
) -> list[ScreenerResult]:
    """
    conditions: 적용할 조건 목록 (AND 조건)
    name_map: stock_code → stock_name
    params: 조건별 파라미터 dict ({"volume_surge": {"threshold": 2.0}, ...})
            지정 안 된 조건은 check 함수의 기본값 사용.
    라이브 조건(volume_power, near_high, upper_limit)은 KIS API에서 실시간 조회 후 교집합.
    DB 조건은 screener_db에서 per-stock 검사.
    """
    user_params: dict[str, dict] = params or {}
    all_valid = set(_CONDITION_FN.keys()) | _LIVE_CONDITIONS
    invalid = [c for c in conditions if c not in all_valid]
    if invalid:
        raise ValueError(f"Unknown conditions: {invalid}. Available: {sorted(all_valid)}")

    live_conds = [c for c in conditions if c in _LIVE_CONDITIONS]
    db_conds = [c for c in conditions if c not in _LIVE_CONDITIONS]

    # ── 라이브 조건 프리패치 ───────────────────────────────────────────────
    live_sets: dict[str, set[str]] = {}
    live_price_lookup: dict[str, tuple[int, int]] = {}  # code → (price, volume)
    for cond in live_conds:
        items = _fetch_live_items(cond)
        live_sets[cond] = {item.stock_code for item in items}
        for item in items:
            if item.stock_code not in live_price_lookup:
                live_price_lookup[item.stock_code] = (item.price, item.volume)

    # ── 후보 종목 결정 ────────────────────────────────────────────────────
    if live_conds:
        # 라이브 조건들의 교집합
        candidate_set: set[str] = set.intersection(*[live_sets[c] for c in live_conds])
        if db_conds:
            # DB 조건도 있으면 screener DB에 있는 종목만 교차
            db_codes = set(get_all_stock_codes())
            candidate_codes = list(candidate_set & db_codes)
        else:
            candidate_codes = list(candidate_set)
    else:
        candidate_codes = get_all_stock_codes()

    if not candidate_codes:
        if live_conds and not any(live_sets.values()):
            logger.warning("라이브 조건 API에서 데이터를 가져오지 못했습니다 (장 마감 또는 API 오류)")
        return []

    # ── 종목별 조건 검사 ──────────────────────────────────────────────────
    results: list[ScreenerResult] = []

    for code in candidate_codes:
        # 라이브 조건: 이미 교집합으로 필터링됨 → 레이블만 추가
        matched: list[str] = [_CONDITION_LABEL[c] for c in live_conds]

        # DB 조건: per-stock 검사
        for cond in db_conds:
            fn = _CONDITION_FN[cond]
            cond_params = user_params.get(cond, {})
            try:
                ok = fn(code, **cond_params)
            except TypeError as exc:
                logger.warning("Invalid params for %s (%s). Using defaults.", cond, exc)
                ok = fn(code)
            except Exception as exc:
                logger.debug("Condition %s error for %s: %s", cond, code, exc)
                ok = False
            if ok:
                matched.append(_CONDITION_LABEL[cond])

        if len(matched) < len(conditions):
            continue

        # 가격/거래량: DB 우선, 없으면 라이브 API 값 사용
        rows = get_prices(code, days=1)
        if rows:
            close = rows[-1]["close"]
            volume = rows[-1]["volume"]
        else:
            close, volume = live_price_lookup.get(code, (0, 0))

        results.append(ScreenerResult(
            stock_code=code,
            stock_name=name_map.get(code, code),
            close=close,
            volume=volume,
            matched_conditions=matched,
        ))

    return results
