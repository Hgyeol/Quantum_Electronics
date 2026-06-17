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
from services.screener_db import get_oldest_price_date, has_data_for_date, init_db, log_collection, upsert_investor, upsert_prices, upsert_stocks

logger = logging.getLogger(__name__)

_PRICE_URL = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
_PRICE_TR_ID = "FHKST03010100"

_INVESTOR_URL = "/uapi/domestic-stock/v1/quotations/investor-trade-by-stock-daily"
_INVESTOR_TR_ID = "FHPTJ04160001"

_SLEEP = 0.12  # KIS rate limit 여유 확보


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


def _fetch_prices_chunk(stock_code: str, start: str, end: str) -> list[dict]:
    """단일 구간 가격 데이터 조회."""
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


def _fetch_prices(stock_code: str, days: int = 365, end_date: datetime | None = None) -> list[dict]:
    """페이지네이션으로 최대 days일치 가격 데이터 수집.

    end_date: 이 날짜 이전 데이터만 수집 (백필용). None이면 오늘까지.
    """
    chunk_days = 130  # 달력 기준 130일 ≈ 거래일 ~90개
    cutoff = (datetime.now() - timedelta(days=days + 60)).strftime("%Y%m%d")

    collected: dict[str, dict] = {}
    end_dt = end_date or datetime.now()

    for _ in range(6):  # 최대 6번 = 약 780거래일 커버
        end_str = end_dt.strftime("%Y%m%d")
        start_dt = end_dt - timedelta(days=chunk_days)
        start_str = start_dt.strftime("%Y%m%d")

        chunk = _fetch_prices_chunk(stock_code, start_str, end_str)
        time.sleep(_SLEEP)

        for row in chunk:
            collected[row["date"]] = row

        if chunk and min(r["date"] for r in chunk) <= cutoff:
            break

        end_dt = start_dt - timedelta(days=1)

    return sorted(collected.values(), key=lambda r: r["date"])


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

    stock_list = _load_stock_codes()
    if not stock_list:
        logger.error("No stock codes loaded — aborting")
        return

    # stocks 테이블에 종목 메타데이터 저장
    from services.outlook import load_all_stock_names as _load_names
    name_map = {}
    try:
        name_map = _load_names()
    except Exception as exc:
        logger.warning("Failed to load stock names: %s", exc)
    stock_rows = [
        {"stock_code": code, "name": name_map.get(code, ""), "market": market}
        for code, market in stock_list
    ]
    upsert_stocks(stock_rows)
    logger.info("Upserted %d stocks into stocks table", len(stock_rows))

    start_ts = time.time()
    collected = 0
    skipped = 0
    today = datetime.now().strftime("%Y%m%d")

    cutoff_date = (datetime.now() - timedelta(days=price_days + 60)).strftime("%Y%m%d")

    for i, (code, _market) in enumerate(stock_list):
        did_something = False

        # 오늘 데이터 없으면 최신 수집
        if not has_data_for_date(code, today):
            prices = _fetch_prices(code, price_days)
            investor = _fetch_investor(code, investor_days)
            time.sleep(_SLEEP)
            if prices:
                upsert_prices(prices)
            if investor:
                upsert_investor(investor)
            if prices or investor:
                did_something = True
        else:
            skipped += 1

        # 1년치 부족하면 과거 구간 백필
        oldest = get_oldest_price_date(code)
        if oldest and oldest > cutoff_date:
            end_dt = datetime.strptime(oldest, "%Y%m%d") - timedelta(days=1)
            backfill = _fetch_prices(code, price_days, end_date=end_dt)
            if backfill:
                upsert_prices(backfill)
                did_something = True

        if did_something:
            collected += 1

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_ts
            logger.info(
                "[%d/%d] collected=%d skipped=%d elapsed=%.0fs",
                i + 1, len(stock_list), collected, skipped, elapsed,
            )

    duration = time.time() - start_ts
    log_collection(datetime.now().isoformat(), collected, duration)
    logger.info("Done. collected=%d skipped=%d total=%d in %.0fs", collected, skipped, len(stock_list), duration)
