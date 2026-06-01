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


_CONDITION_FN = {
    "volume_surge": check_volume_surge,
    "golden_cross": check_golden_cross,
    "frgn_buy": check_frgn_consecutive_buy,
    "orgn_buy": check_orgn_consecutive_buy,
    "price_surge": check_price_surge,
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
    volume_threshold: float = 2.0,
    consecutive_days: int = 3,
    price_surge_threshold: float = 5.0,
) -> list[ScreenerResult]:
    """
    conditions: 적용할 조건 목록 (AND 조건)
    name_map: stock_code → stock_name
    라이브 조건(volume_power, near_high, upper_limit)은 KIS API에서 실시간 조회 후 교집합.
    DB 조건은 screener_db에서 per-stock 검사.
    """
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
            try:
                if cond == "volume_surge":
                    ok = fn(code, volume_threshold)
                elif cond in ("frgn_buy", "orgn_buy"):
                    ok = fn(code, consecutive_days)
                elif cond == "price_surge":
                    ok = fn(code, price_surge_threshold)
                else:
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
