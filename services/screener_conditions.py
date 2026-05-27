"""Screener condition evaluation against the SQLite cache."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from services.screener_db import get_all_stock_codes, get_investor, get_prices

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


_CONDITION_FN = {
    "volume_surge": check_volume_surge,
    "golden_cross": check_golden_cross,
    "frgn_buy": check_frgn_consecutive_buy,
    "orgn_buy": check_orgn_consecutive_buy,
}

_CONDITION_LABEL = {
    "volume_surge": "거래량 급등",
    "golden_cross": "골든크로스 (MA5/MA20)",
    "frgn_buy": "외국인 연속 순매수",
    "orgn_buy": "기관 연속 순매수",
}


def run_screener(
    conditions: list[str],
    name_map: dict[str, str],
    volume_threshold: float = 2.0,
    consecutive_days: int = 3,
) -> list[ScreenerResult]:
    """
    conditions: 적용할 조건 목록 (AND 조건)
    name_map: stock_code → stock_name
    """
    invalid = [c for c in conditions if c not in _CONDITION_FN]
    if invalid:
        raise ValueError(f"Unknown conditions: {invalid}. Available: {list(_CONDITION_FN)}")

    all_codes = get_all_stock_codes()
    if not all_codes:
        logger.warning("screener DB가 비어있음 — collect_screener_data.py 먼저 실행하세요")
        return []

    results: list[ScreenerResult] = []

    for code in all_codes:
        matched: list[str] = []
        for cond in conditions:
            fn = _CONDITION_FN[cond]
            try:
                if cond == "volume_surge":
                    ok = fn(code, volume_threshold)
                elif cond in ("frgn_buy", "orgn_buy"):
                    ok = fn(code, consecutive_days)
                else:
                    ok = fn(code)
            except Exception as exc:
                logger.debug("Condition %s error for %s: %s", cond, code, exc)
                ok = False
            if ok:
                matched.append(_CONDITION_LABEL[cond])

        if len(matched) == len(conditions):
            rows = get_prices(code, days=1)
            close = rows[-1]["close"] if rows else 0
            volume = rows[-1]["volume"] if rows else 0
            results.append(ScreenerResult(
                stock_code=code,
                stock_name=name_map.get(code, code),
                close=close,
                volume=volume,
                matched_conditions=matched,
            ))

    return results
