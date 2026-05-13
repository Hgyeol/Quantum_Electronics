"""Backfill historical signal features for the PRD Phase-2 dataset.

For each stock in `data/stock_codes.csv` and each trading date present in
`data/prices.csv`, this script reconstructs an `OutlookReport` (quant + DART
disclosures + DART financials, with LLM scoring on the DART evidence) and
appends a row to `data/features.csv` + `data/outlook_reports.jsonl`.

News evidence is intentionally skipped — see `ml/historical.py` docstring.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ml.features import feature_row_from_report
from ml.historical import (
    HistoricalOutlookProvider,
    StockHistory,
    load_prices_csv,
    make_llm_analyzer,
    prefetch_stock_history,
    slice_prices_for_stock,
    trading_dates_for_stock,
)
from scripts.collect_price_history import read_codes

logger = logging.getLogger(__name__)


def load_dotenv_file(path: str | Path = PROJECT_ROOT / ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _existing_feature_keys(features_csv: Path) -> set[tuple[str, str]]:
    if not features_csv.exists():
        return set()
    df = pd.read_csv(features_csv, dtype={"stock_code": str, "date": str})
    return {(row["date"], row["stock_code"]) for _, row in df.iterrows()}


def _existing_report_keys(reports_jsonl: Path) -> set[tuple[str, str]]:
    if not reports_jsonl.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    for raw_line in reports_jsonl.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        as_of = str(payload.get("as_of_date") or "")
        code = str(payload.get("stock_code") or "").strip()
        if as_of and code:
            keys.add((as_of, code))
    return keys


def _append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _merge_feature_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_rows = pd.DataFrame(rows)
    if path.exists():
        existing = pd.read_csv(path, dtype={"stock_code": str, "date": str})
        merged = pd.concat([existing, new_rows], ignore_index=True)
    else:
        merged = new_rows
    merged = merged.drop_duplicates(subset=["date", "stock_code"], keep="last")
    merged = merged.sort_values(["date", "stock_code"])
    merged.to_csv(path, index=False)


def run_backfill(
    stock_codes_csv: str | Path = "data/stock_codes.csv",
    prices_csv: str | Path = "data/prices.csv",
    features_csv: str | Path = "data/features.csv",
    reports_jsonl: str | Path = "data/outlook_reports.jsonl",
    llm_cache_path: str | Path | None = None,
    backfill_start: date | None = None,
    backfill_end: date | None = None,
    max_dates_per_stock: int | None = None,
    sleep_between_dates: float = 0.0,
    kis_auth_enabled: bool = False,
    force_kis_token: bool = False,
    kis_server: str = "prod",
) -> dict:
    if kis_auth_enabled:
        import kis_auth
        if force_kis_token:
            Path(kis_auth.get_token_path()).unlink(missing_ok=True)
        kis_auth.auth(svr=kis_server)

    prices = load_prices_csv(prices_csv)
    codes = read_codes([], str(stock_codes_csv))
    features_path = Path(features_csv)
    reports_path = Path(reports_jsonl)
    existing_features = _existing_feature_keys(features_path)
    existing_reports = _existing_report_keys(reports_path)

    if llm_cache_path:
        os.environ["OUTLOOK_LLM_CACHE_PATH"] = str(llm_cache_path)
    llm_analyzer = make_llm_analyzer(llm_cache_path)

    histories: dict[str, StockHistory] = {}
    summary = {
        "stocks": [],
        "feature_rows_appended": 0,
        "report_records_appended": 0,
    }

    # Each stock: prefetch DART + investor → then iterate dates
    for code in codes:
        stock_prices = slice_prices_for_stock(prices, code)
        if stock_prices.empty:
            logger.warning("no prices for %s — skipping", code)
            continue

        stock_dates = trading_dates_for_stock(stock_prices, code)
        if backfill_start:
            stock_dates = [d for d in stock_dates if d >= backfill_start]
        if backfill_end:
            stock_dates = [d for d in stock_dates if d <= backfill_end]
        if not stock_dates:
            continue
        if max_dates_per_stock and len(stock_dates) > max_dates_per_stock:
            stock_dates = stock_dates[-max_dates_per_stock:]

        window_start = stock_dates[0]
        window_end = stock_dates[-1]
        logger.info(
            "prefetching %s — %d dates from %s to %s",
            code, len(stock_dates), window_start, window_end,
        )
        history = prefetch_stock_history(
            stock_code=code,
            prices=stock_prices,
            backfill_start=window_start,
            backfill_end=window_end,
        )
        histories[code] = history

        provider = HistoricalOutlookProvider({code: history}, llm_analyzer=llm_analyzer)

        rows_for_stock = []
        records_for_stock = []
        for as_of in stock_dates:
            iso = as_of.isoformat()
            if (iso, code) in existing_features and (iso, code) in existing_reports:
                continue
            report = provider(stock_code=code, as_of_date=as_of)
            if (iso, code) not in existing_features:
                rows_for_stock.append(feature_row_from_report(report, as_of_date=as_of))
            if (iso, code) not in existing_reports:
                payload = report.model_dump(mode="json")
                payload["as_of_date"] = iso
                records_for_stock.append(payload)
            if sleep_between_dates:
                time.sleep(sleep_between_dates)

        if rows_for_stock:
            _merge_feature_csv(features_path, rows_for_stock)
            summary["feature_rows_appended"] += len(rows_for_stock)
        if records_for_stock:
            _append_jsonl(reports_path, records_for_stock)
            summary["report_records_appended"] += len(records_for_stock)

        existing_features.update((row["date"], row["stock_code"]) for row in rows_for_stock)
        existing_reports.update((record["as_of_date"], record["stock_code"]) for record in records_for_stock)
        summary["stocks"].append(
            {
                "stock_code": code,
                "dates_processed": len(stock_dates),
                "feature_rows": len(rows_for_stock),
                "report_records": len(records_for_stock),
                "errors": [err.model_dump() for err in history.errors[:5]],
            }
        )

    return summary


def main() -> int:
    load_dotenv_file()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Backfill historical signal features for PRD Phase 2")
    parser.add_argument("--stock-codes-csv", default="data/stock_codes.csv")
    parser.add_argument("--prices-csv", default="data/prices.csv")
    parser.add_argument("--features-csv", default="data/features.csv")
    parser.add_argument("--reports-jsonl", default="data/outlook_reports.jsonl")
    parser.add_argument("--llm-cache-path", default="data/llm_cache.json")
    parser.add_argument("--backfill-start", default=None, help="ISO date YYYY-MM-DD")
    parser.add_argument("--backfill-end", default=None, help="ISO date YYYY-MM-DD")
    parser.add_argument("--max-dates-per-stock", type=int, default=None)
    parser.add_argument("--sleep-between-dates", type=float, default=0.0)
    parser.add_argument("--kis-auth", action="store_true")
    parser.add_argument("--force-kis-token", action="store_true")
    parser.add_argument("--kis-server", default="prod", choices=["prod", "vps"])
    args = parser.parse_args()

    summary = run_backfill(
        stock_codes_csv=args.stock_codes_csv,
        prices_csv=args.prices_csv,
        features_csv=args.features_csv,
        reports_jsonl=args.reports_jsonl,
        llm_cache_path=args.llm_cache_path,
        backfill_start=date.fromisoformat(args.backfill_start) if args.backfill_start else None,
        backfill_end=date.fromisoformat(args.backfill_end) if args.backfill_end else None,
        max_dates_per_stock=args.max_dates_per_stock,
        sleep_between_dates=args.sleep_between_dates,
        kis_auth_enabled=args.kis_auth,
        force_kis_token=args.force_kis_token,
        kis_server=args.kis_server,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
