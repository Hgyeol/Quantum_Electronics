"""Refresh foreign_investor_score in data/features.csv after KIS allows it.

`investor_trade_by_stock_daily` is blocked by KIS during 00:00–15:40 KST, so
the initial historical backfill leaves `foreign_investor_score = 0`. Run this
script after 15:40 KST to re-fetch the daily investor flow per stock and
update the foreign_investor / quant_score / total_rule_score columns in place
for rows whose date is covered by the API response.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from ml.historical import (
    fetch_investor_daily,
    foreign_investor_signal_from_daily,
)

logger = logging.getLogger(__name__)

QUANT_SIGNAL_COLUMNS = (
    "golden_cross_score",
    "disparity_score",
    "momentum_score",
    "foreign_investor_score",
    "volume_score",
)


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


def _read_codes(stock_codes_csv: Path) -> list[str]:
    codes: list[str] = []
    for raw_line in stock_codes_csv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            code = line.split(",")[0].strip()
            if code.lower() != "stock_code":
                codes.append(code)
    return codes


def refresh_foreign_investor(
    stock_codes_csv: str | Path = "data/stock_codes.csv",
    features_csv: str | Path = "data/features.csv",
    end_date: date | None = None,
    kis_auth_enabled: bool = True,
    force_kis_token: bool = False,
    kis_server: str = "prod",
) -> dict:
    if kis_auth_enabled:
        import kis_auth
        if force_kis_token:
            Path(kis_auth.get_token_path()).unlink(missing_ok=True)
        kis_auth.auth(svr=kis_server)

    features_path = Path(features_csv)
    if not features_path.exists():
        raise FileNotFoundError(features_path)
    features = pd.read_csv(features_path, dtype={"stock_code": str, "date": str})
    codes = _read_codes(Path(stock_codes_csv))

    target_end = end_date or date.today()
    summary = {"stocks": [], "rows_updated": 0}

    for code in codes:
        investor_daily, errors = fetch_investor_daily(code, target_end)
        stock_summary = {
            "stock_code": code,
            "investor_rows": int(len(investor_daily)) if isinstance(investor_daily, pd.DataFrame) else 0,
            "rows_updated": 0,
            "errors": [err.model_dump() for err in errors],
        }
        if investor_daily is None or investor_daily.empty:
            summary["stocks"].append(stock_summary)
            continue

        stock_mask = features["stock_code"] == code
        for idx in features.index[stock_mask]:
            row_date_str = str(features.at[idx, "date"])
            try:
                as_of = datetime.strptime(row_date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            new_signal = foreign_investor_signal_from_daily(investor_daily, as_of)
            new_score = int(new_signal.score)
            old_score = int(features.at[idx, "foreign_investor_score"])
            if new_score == old_score:
                continue
            features.at[idx, "foreign_investor_score"] = new_score
            new_quant = int(sum(features.at[idx, col] for col in QUANT_SIGNAL_COLUMNS))
            features.at[idx, "quant_score"] = new_quant
            features.at[idx, "total_rule_score"] = int(
                new_quant
                + features.at[idx, "ai_score"]
                + features.at[idx, "financial_score"]
            )
            stock_summary["rows_updated"] += 1

        summary["stocks"].append(stock_summary)
        summary["rows_updated"] += stock_summary["rows_updated"]

    features = features.sort_values(["date", "stock_code"]).reset_index(drop=True)
    features.to_csv(features_path, index=False)
    return summary


def main() -> int:
    load_dotenv_file()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Refresh foreign_investor_score in features.csv (post 15:40 KST)")
    parser.add_argument("--stock-codes-csv", default="data/stock_codes.csv")
    parser.add_argument("--features-csv", default="data/features.csv")
    parser.add_argument("--end-date", default=None, help="ISO date YYYY-MM-DD; default=today")
    parser.add_argument("--no-kis-auth", action="store_true")
    parser.add_argument("--force-kis-token", action="store_true")
    parser.add_argument("--kis-server", default="prod", choices=["prod", "vps"])
    args = parser.parse_args()

    summary = refresh_foreign_investor(
        stock_codes_csv=args.stock_codes_csv,
        features_csv=args.features_csv,
        end_date=date.fromisoformat(args.end_date) if args.end_date else None,
        kis_auth_enabled=not args.no_kis_auth,
        force_kis_token=args.force_kis_token,
        kis_server=args.kis_server,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
