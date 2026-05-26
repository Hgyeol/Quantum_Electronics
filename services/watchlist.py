"""Watchlist multi-stock price service backed by KIS intstock-multprice."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_API_URL = "/uapi/domestic-stock/v1/quotations/intstock-multprice"
_TR_ID = "FHKST11300006"


@dataclass
class WatchlistItem:
    stock_code: str
    stock_name: str | None
    price: int
    change: int
    change_rate: float
    volume: int
    trade_value: int = 0  # 누적 거래대금 (원, acml_tr_pbmn)


def fetch_multi_price(codes: list[str], name_map: dict[str, str]) -> list[WatchlistItem]:
    """Call KIS intstock-multprice for up to 30 codes and return WatchlistItem list.

    name_map: {stock_code: stock_name} from the local master CSV (fallback to code).
    Missing or KIS-failed codes are silently skipped.
    """
    if not codes:
        return []

    try:
        import kis_auth as ka
    except Exception as exc:
        logger.warning("kis_auth not available: %s", exc)
        return []

    params: dict[str, str] = {}
    for i, code in enumerate(codes[:30], start=1):
        params[f"FID_COND_MRKT_DIV_CODE_{i}"] = "J"
        params[f"FID_INPUT_ISCD_{i}"] = code

    try:
        res = ka._url_fetch(_API_URL, _TR_ID, "", params)
    except Exception as exc:
        logger.warning("intstock_multprice call failed: %s", exc)
        return []

    if not res.isOK():
        logger.warning("intstock_multprice API error")
        return []

    rows = res.getBody().output
    if not isinstance(rows, list):
        rows = [rows]

    items: list[WatchlistItem] = []
    for row in rows:
        code = (row.get("inter_shrn_iscd") or "").strip()
        if not code:
            continue
        try:
            price = int(row.get("inter2_prpr") or 0)
            change = int(row.get("inter2_prdy_vrss") or 0)
            change_rate = float(row.get("prdy_ctrt") or 0)
            volume = int(row.get("acml_vol") or 0)
            trade_value = int(row.get("acml_tr_pbmn") or 0)
        except (ValueError, TypeError):
            continue

        kis_name = (row.get("inter_kor_isnm") or "").strip() or None
        items.append(
            WatchlistItem(
                stock_code=code,
                stock_name=name_map.get(code) or kis_name,
                price=price,
                change=change,
                change_rate=change_rate,
                volume=volume,
                trade_value=trade_value,
            )
        )

    return items
