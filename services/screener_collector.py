"""Nightly batch: fetch OHLCV + investor data for all listed stocks → SQLite."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import kis_auth as ka
from services.screener_db import has_data_for_date, init_db, log_collection, upsert_investor, upsert_prices

logger = logging.getLogger(__name__)

_PRICE_URL = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
_PRICE_TR_ID = "FHKST03010100"

_INVESTOR_URL = "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
_INVESTOR_TR_ID = "FHPTJ04160001"

_SLEEP = 0.06  # ~16 calls/sec, 20이 max지만 여유 둠


def _load_stock_codes() -> list[tuple[str, str]]:
    """kospi.csv + kosdaq.csv에서 (code, market) 목록 반환."""
    base = Path(__file__).parent.parent
    result: list[tuple[str, str]] = []
    for fname, market in [("kospi.csv", "KOSPI"), ("kosdaq.csv", "KOSDAQ")]:
        path = base / fname
        if not path.exists():
            logger.warning("%s not found", path)
            continue
        for enc in ("utf-8-sig", "cp949", "euc-kr"):
            try:
                df = pd.read_csv(path, encoding=enc, dtype=str)
                break
            except Exception:
                continue
        else:
            logger.warning("Failed to read %s", fname)
            continue
        col = next((c for c in df.columns if "단축코드" in c), None)
        if col is None:
            logger.warning("단축코드 column not found in %s", fname)
            continue
        codes = df[col].dropna().str.strip().str.zfill(6).tolist()
        result.extend((c, market) for c in codes if c.isdigit())
    logger.info("Loaded %d stocks total", len(result))
    return result


def _fetch_prices(stock_code: str, days: int = 30) -> list[dict]:
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days + 50)).strftime("%Y%m%d")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": start,
        "FID_INPUT_DATE_2": end,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    }
    try:
        res = ka._url_fetch(_PRICE_URL, _PRICE_TR_ID, "", params)
        if not res.isOK():
            return []
        rows = res.getBody().output2
        if not rows:
            return []
        result = []
        for r in rows:
            try:
                result.append({
                    "stock_code": stock_code,
                    "date": r.get("stck_bsop_date", ""),
                    "open": int(r.get("stck_oprc") or 0),
                    "high": int(r.get("stck_hgpr") or 0),
                    "low": int(r.get("stck_lwpr") or 0),
                    "close": int(r.get("stck_clpr") or 0),
                    "volume": int(r.get("acml_vol") or 0),
                })
            except (ValueError, TypeError):
                continue
        return [r for r in result if r["date"]]
    except Exception as exc:
        logger.debug("Price fetch error %s: %s", stock_code, exc)
        return []


def _fetch_investor(stock_code: str, days: int = 10) -> list[dict]:
    # FID_INPUT_DATE_1은 기준(종료)일 — 오늘 날짜를 넘기면 API가 최근 N일치 반환
    today = datetime.now().strftime("%Y%m%d")
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": today,
        "FID_ORG_ADJ_PRC": "",
        "FID_ETC_CLS_CODE": "",
    }
    try:
        res = ka._url_fetch(_INVESTOR_URL, _INVESTOR_TR_ID, "", params)
        if not res.isOK():
            return []
        rows = getattr(res.getBody(), "output2", None) or []
        result = []
        for r in rows:
            try:
                result.append({
                    "stock_code": stock_code,
                    "date": r.get("stck_bsop_date", ""),
                    "frgn_ntby_qty": int(r.get("frgn_ntby_qty") or 0),
                    "orgn_ntby_qty": int(r.get("orgn_ntby_qty") or 0),
                })
            except (ValueError, TypeError):
                continue
        return [r for r in result if r["date"]]
    except Exception as exc:
        logger.debug("Investor fetch error %s: %s", stock_code, exc)
        return []


def run(price_days: int = 365, investor_days: int = 10) -> None:
    """전종목 데이터 수집 및 SQLite 저장."""
    init_db()
    ka.auth()

    stocks = _load_stock_codes()
    if not stocks:
        logger.error("No stock codes loaded — aborting")
        return

    start_ts = time.time()
    collected = 0
    skipped = 0
    today = datetime.now().strftime("%Y%m%d")

    for i, (code, _market) in enumerate(stocks):
        if has_data_for_date(code, today):
            skipped += 1
            continue

        prices = _fetch_prices(code, price_days)
        time.sleep(_SLEEP)

        investor = _fetch_investor(code, investor_days)
        time.sleep(_SLEEP)

        if prices:
            upsert_prices(prices)
        if investor:
            upsert_investor(investor)

        if prices or investor:
            collected += 1

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_ts
            logger.info(
                "[%d/%d] collected=%d skipped=%d elapsed=%.0fs",
                i + 1, len(stocks), collected, skipped, elapsed,
            )

    duration = time.time() - start_ts
    log_collection(datetime.now().isoformat(), collected, duration)
    logger.info("Done. collected=%d skipped=%d total=%d in %.0fs", collected, skipped, len(stocks), duration)
