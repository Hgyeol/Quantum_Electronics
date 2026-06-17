"""Repair missing screener rows by date.

Default scope is the live collection window that started on 2026-06-01.

Examples:
    python scripts/repair_screener_gaps.py --dry-run
    python scripts/repair_screener_gaps.py --apply
    python scripts/repair_screener_gaps.py --apply --date 20260616
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import kis_auth as ka
from services.screener_collector import (
    _INVESTOR_TR_ID,
    _INVESTOR_URL,
    _fetch_prices_chunk,
)
from services.screener_db import get_conn, init_db, upsert_investor, upsert_prices

logger = logging.getLogger(__name__)

DEFAULT_START_DATE = "20260601"


def _normalize_date(value: str) -> str:
    date = value.strip().replace("-", "")
    if len(date) != 8 or not date.isdigit():
        raise argparse.ArgumentTypeError("date must be YYYYMMDD or YYYY-MM-DD")
    return date


def _db_dates(start_date: str, end_date: str | None) -> list[str]:
    params: list[str] = [start_date]
    end_clause = ""
    if end_date:
        end_clause = "AND date <= ?"
        params.append(end_date)

    with closing(get_conn()) as conn:
        rows = conn.execute(
            f"""
            SELECT date
            FROM (
                SELECT DISTINCT date FROM daily_price WHERE date >= ? {end_clause}
                UNION
                SELECT DISTINCT date FROM daily_investor WHERE date >= ? {end_clause}
            )
            ORDER BY date
            """,
            params + params,
        ).fetchall()
    return [r["date"] for r in rows]


def _missing_codes(table: str, date: str) -> list[str]:
    if table not in {"daily_price", "daily_investor"}:
        raise ValueError(f"unsupported table: {table}")

    with closing(get_conn()) as conn:
        rows = conn.execute(
            f"""
            SELECT s.stock_code
            FROM stocks s
            LEFT JOIN {table} d
              ON d.stock_code = s.stock_code
             AND d.date = ?
            WHERE d.stock_code IS NULL
            ORDER BY s.stock_code
            """,
            (date,),
        ).fetchall()
    return [r["stock_code"] for r in rows]


def _missing_by_stock(table: str, dates: list[str]) -> dict[str, set[str]]:
    missing: dict[str, set[str]] = defaultdict(set)
    for date in dates:
        codes = _missing_codes(table, date)
        logger.info("%s %s missing=%d", table, date, len(codes))
        for code in codes:
            missing[code].add(date)
    return missing


def _fetch_investor_until(stock_code: str, end_date: str) -> list[dict]:
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
        "FID_INPUT_DATE_1": end_date,
        "FID_ORG_ADJ_PRC": "",
        "FID_ETC_CLS_CODE": "",
    }
    try:
        res = ka._url_fetch(_INVESTOR_URL, _INVESTOR_TR_ID, "", params)
        if not res.isOK():
            return []
        rows = getattr(res.getBody(), "output2", None) or []
    except Exception as exc:
        logger.debug("Investor fetch error %s: %s", stock_code, exc)
        return []

    result = []
    for row in rows:
        try:
            result.append(
                {
                    "stock_code": stock_code,
                    "date": row.get("stck_bsop_date", ""),
                    "frgn_ntby_qty": int(row.get("frgn_ntby_qty") or 0),
                    "orgn_ntby_qty": int(row.get("orgn_ntby_qty") or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return [row for row in result if row["date"]]


def _repair_price(
    missing: dict[str, set[str]],
    start_date: str,
    end_date: str,
    *,
    sleep_sec: float,
    retries: int,
) -> tuple[int, int]:
    inserted = 0
    unresolved = 0
    total = len(missing)

    for index, (code, wanted_dates) in enumerate(missing.items(), start=1):
        got_dates: set[str] = set()
        for attempt in range(retries + 1):
            rows = [
                row
                for row in _fetch_prices_chunk(code, start_date, end_date)
                if row["date"] in wanted_dates
            ]
            if rows:
                upsert_prices(rows)
                inserted += len(rows)
                got_dates.update(row["date"] for row in rows)
            if wanted_dates <= got_dates:
                break
            if attempt < retries:
                time.sleep(sleep_sec * (attempt + 1))

        missing_dates = wanted_dates - got_dates
        unresolved += len(missing_dates)
        if index % 100 == 0 or index == total:
            logger.info(
                "daily_price repair progress %d/%d inserted=%d unresolved=%d",
                index,
                total,
                inserted,
                unresolved,
            )
        time.sleep(sleep_sec)

    return inserted, unresolved


def _repair_investor(
    missing: dict[str, set[str]],
    end_date: str,
    *,
    sleep_sec: float,
    retries: int,
) -> tuple[int, int]:
    inserted = 0
    unresolved = 0
    total = len(missing)

    for index, (code, wanted_dates) in enumerate(missing.items(), start=1):
        got_dates: set[str] = set()
        for attempt in range(retries + 1):
            rows = [
                row
                for row in _fetch_investor_until(code, end_date)
                if row["date"] in wanted_dates
            ]
            if rows:
                upsert_investor(rows)
                inserted += len(rows)
                got_dates.update(row["date"] for row in rows)
            if wanted_dates <= got_dates:
                break
            if attempt < retries:
                time.sleep(sleep_sec * (attempt + 1))

        missing_dates = wanted_dates - got_dates
        unresolved += len(missing_dates)
        if index % 100 == 0 or index == total:
            logger.info(
                "daily_investor repair progress %d/%d inserted=%d unresolved=%d",
                index,
                total,
                inserted,
                unresolved,
            )
        time.sleep(sleep_sec)

    return inserted, unresolved


def run(args: argparse.Namespace) -> int:
    init_db()

    dates = [args.date] if args.date else _db_dates(args.start_date, args.end_date)
    if not dates:
        logger.info("No DB dates found from %s", args.start_date)
        return 0

    start_date = min(dates)
    end_date = max(dates)
    logger.info("Repair window: %s..%s (%d dates)", start_date, end_date, len(dates))

    price_missing = _missing_by_stock("daily_price", dates) if args.table in {"both", "price"} else {}
    investor_missing = (
        _missing_by_stock("daily_investor", dates) if args.table in {"both", "investor"} else {}
    )

    price_cells = sum(len(v) for v in price_missing.values())
    investor_cells = sum(len(v) for v in investor_missing.values())
    logger.info(
        "Missing summary: daily_price=%d cells across %d stocks, daily_investor=%d cells across %d stocks",
        price_cells,
        len(price_missing),
        investor_cells,
        len(investor_missing),
    )

    if args.dry_run:
        return 0
    if not args.apply:
        logger.info("No changes made. Pass --apply to fetch and save missing rows.")
        return 0

    ka.auth()

    if price_missing:
        inserted, unresolved = _repair_price(
            price_missing,
            start_date,
            end_date,
            sleep_sec=args.sleep,
            retries=args.retries,
        )
        logger.info("daily_price repair done: inserted=%d unresolved=%d", inserted, unresolved)

    if investor_missing:
        inserted, unresolved = _repair_investor(
            investor_missing,
            end_date,
            sleep_sec=args.sleep,
            retries=args.retries,
        )
        logger.info("daily_investor repair done: inserted=%d unresolved=%d", inserted, unresolved)

    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair missing daily screener rows.")
    parser.add_argument("--start-date", type=_normalize_date, default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", type=_normalize_date, default=None)
    parser.add_argument("--date", type=_normalize_date, default=None, help="Repair one YYYYMMDD date only.")
    parser.add_argument("--table", choices=("both", "price", "investor"), default="both")
    parser.add_argument("--sleep", type=float, default=0.25, help="Seconds to sleep between API calls.")
    parser.add_argument("--retries", type=int, default=2, help="Retries per stock when wanted rows are still missing.")
    parser.add_argument("--apply", action="store_true", help="Fetch from KIS and write missing rows.")
    parser.add_argument("--dry-run", action="store_true", help="Only report missing rows.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv if argv is not None else sys.argv[1:])
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
