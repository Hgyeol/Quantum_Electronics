"""Collect the daily inputs needed by the signal-learning PRD workflow."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect_price_history import collect_price_history, read_codes
from scripts.collect_signal_features import collect_signal_features
from scripts.export_stock_universe import export_stock_universe


def _authenticate_kis(force_token: bool, kis_server: str) -> None:
    import kis_auth

    if force_token:
        Path(kis_auth.get_token_path()).unlink(missing_ok=True)
    kis_auth.auth(svr=kis_server)


def run_daily_signal_learning_collection(
    stock_codes_csv: str | Path = "data/stock_codes.csv",
    master_csv: str | Path = "kospi.csv",
    stock_limit: int = 5,
    prices_csv: str | Path = "data/prices.csv",
    reports_jsonl: str | Path = "data/outlook_reports.jsonl",
    features_csv: str | Path = "data/features.csv",
    price_days: int = 120,
    as_of_date: date | None = None,
    kis_auth_enabled: bool = False,
    force_kis_token: bool = False,
    kis_server: str = "prod",
    price_fetcher=None,
    outlook_service=None,
) -> dict:
    if kis_auth_enabled:
        _authenticate_kis(force_kis_token, kis_server)

    stock_count = export_stock_universe(master_csv, stock_codes_csv, limit=stock_limit)
    codes = read_codes([], str(stock_codes_csv))
    price_result = collect_price_history(
        codes,
        prices_csv,
        days=price_days,
        env_dv="real",
        price_fetcher=price_fetcher,
    )
    feature_result = collect_signal_features(
        codes=codes,
        as_of_date=as_of_date or date.today(),
        reports_jsonl=reports_jsonl,
        features_csv=features_csv,
        service=outlook_service,
    )
    return {
        "stock_universe": {
            "path": str(stock_codes_csv),
            "count": stock_count,
        },
        "prices": {
            "path": str(prices_csv),
            **price_result,
        },
        "features": {
            "reports_jsonl": str(reports_jsonl),
            "features_csv": str(features_csv),
            **feature_result,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect daily signal-learning inputs")
    parser.add_argument("--stock-codes-csv", default="data/stock_codes.csv")
    parser.add_argument("--master-csv", default="kospi.csv")
    parser.add_argument("--stock-limit", type=int, default=5)
    parser.add_argument("--prices-csv", default="data/prices.csv")
    parser.add_argument("--reports-jsonl", default="data/outlook_reports.jsonl")
    parser.add_argument("--features-csv", default="data/features.csv")
    parser.add_argument("--price-days", type=int, default=120)
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--kis-auth", action="store_true")
    parser.add_argument("--force-kis-token", action="store_true")
    parser.add_argument("--kis-server", default="prod", choices=["prod", "vps"])
    args = parser.parse_args()

    result = run_daily_signal_learning_collection(
        stock_codes_csv=args.stock_codes_csv,
        master_csv=args.master_csv,
        stock_limit=args.stock_limit,
        prices_csv=args.prices_csv,
        reports_jsonl=args.reports_jsonl,
        features_csv=args.features_csv,
        price_days=args.price_days,
        as_of_date=date.fromisoformat(args.as_of_date),
        kis_auth_enabled=args.kis_auth,
        force_kis_token=args.force_kis_token,
        kis_server=args.kis_server,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
