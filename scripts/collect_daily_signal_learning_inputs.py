"""Collect the daily inputs needed by the signal-learning PRD workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.check_signal_learning_inputs import check_signal_learning_inputs
from scripts.collect_price_history import collect_price_history, read_codes
from scripts.collect_signal_features import collect_signal_features
from scripts.export_stock_universe import DEFAULT_MASTER_CSVS, export_stock_universe
from scripts.run_signal_learning_workflow import run_signal_learning_workflow


def load_dotenv_file(path: str | Path = PROJECT_ROOT / ".env") -> None:
    dotenv_path = Path(path)
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _authenticate_kis(force_token: bool, kis_server: str) -> None:
    import kis_auth

    if force_token:
        Path(kis_auth.get_token_path()).unlink(missing_ok=True)
    kis_auth.auth(svr=kis_server)


def run_daily_signal_learning_collection(
    stock_codes_csv: str | Path = "data/stock_codes.csv",
    master_csv: str | Path | Sequence[str | Path] = DEFAULT_MASTER_CSVS,
    stock_limit: int = 3,
    prices_csv: str | Path = "data/prices.csv",
    reports_jsonl: str | Path = "data/outlook_reports.jsonl",
    features_csv: str | Path = "data/features.csv",
    price_days: int = 120,
    min_calendar_days: int = 90,
    min_stocks: int = 3,
    as_of_date: date | None = None,
    kis_auth_enabled: bool = False,
    force_kis_token: bool = False,
    kis_server: str = "prod",
    run_workflow_if_ready: bool = False,
    workflow_output_dir: str | Path = "ml/artifacts/signal_learning_v1",
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
        skip_existing_reports=True,
    )
    readiness = check_signal_learning_inputs(
        features_csv,
        prices_csv,
        min_calendar_days=min_calendar_days,
        min_stocks=min_stocks,
    )
    result = {
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
        "readiness": readiness,
    }
    if run_workflow_if_ready:
        if readiness.get("ok"):
            result["workflow"] = run_signal_learning_workflow(
                features_csv=features_csv,
                prices_csv=prices_csv,
                output_dir=workflow_output_dir,
                min_calendar_days=min_calendar_days,
                min_stocks=min_stocks,
            )
        else:
            result["workflow"] = {
                "ok": False,
                "stopped_at": "input_readiness",
                "reason": "readiness.ok is false",
            }
    return result


def main() -> int:
    load_dotenv_file()

    parser = argparse.ArgumentParser(description="Collect daily signal-learning inputs")
    parser.add_argument("--stock-codes-csv", default="data/stock_codes.csv")
    parser.add_argument(
        "--master-csv",
        action="append",
        default=None,
        help=(
            "Master CSV path. Repeat to merge multiple files. "
            f"Defaults to {list(DEFAULT_MASTER_CSVS)} when omitted."
        ),
    )
    parser.add_argument("--stock-limit", type=int, default=3)
    parser.add_argument("--prices-csv", default="data/prices.csv")
    parser.add_argument("--reports-jsonl", default="data/outlook_reports.jsonl")
    parser.add_argument("--features-csv", default="data/features.csv")
    parser.add_argument("--price-days", type=int, default=120)
    parser.add_argument("--min-calendar-days", type=int, default=90)
    parser.add_argument("--min-stocks", type=int, default=3)
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--kis-auth", action="store_true")
    parser.add_argument("--force-kis-token", action="store_true")
    parser.add_argument("--kis-server", default="prod", choices=["prod", "vps"])
    parser.add_argument("--run-workflow-if-ready", action="store_true")
    parser.add_argument("--workflow-output-dir", default="ml/artifacts/signal_learning_v1")
    args = parser.parse_args()

    master_csv = args.master_csv if args.master_csv else list(DEFAULT_MASTER_CSVS)
    result = run_daily_signal_learning_collection(
        stock_codes_csv=args.stock_codes_csv,
        master_csv=master_csv,
        stock_limit=args.stock_limit,
        prices_csv=args.prices_csv,
        reports_jsonl=args.reports_jsonl,
        features_csv=args.features_csv,
        price_days=args.price_days,
        min_calendar_days=args.min_calendar_days,
        min_stocks=args.min_stocks,
        as_of_date=date.fromisoformat(args.as_of_date),
        kis_auth_enabled=args.kis_auth,
        force_kis_token=args.force_kis_token,
        kis_server=args.kis_server,
        run_workflow_if_ready=args.run_workflow_if_ready,
        workflow_output_dir=args.workflow_output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
