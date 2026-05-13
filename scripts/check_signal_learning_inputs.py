"""Check whether feature and price CSVs can produce next-day labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.dataset import _normalize_dates, build_labeled_dataset


def check_signal_learning_inputs(
    features_csv: str | Path,
    prices_csv: str | Path,
    min_calendar_days: int = 90,
    min_stocks: int = 3,
) -> dict:
    features_path = Path(features_csv)
    prices_path = Path(prices_csv)
    if not features_path.exists():
        return {"ok": False, "error": f"features file not found: {features_path}"}
    if not prices_path.exists():
        return {"ok": False, "error": f"prices file not found: {prices_path}"}

    features = pd.read_csv(features_path, dtype={"stock_code": str})
    prices = pd.read_csv(prices_path, dtype={"stock_code": str})
    features = _normalize_dates(features)
    prices = _normalize_dates(prices)
    features["date"] = pd.to_datetime(features["date"], errors="coerce")
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce")

    labelable_rows = 0
    missing_next_price = []
    for _, feature in features.iterrows():
        stock_prices = prices[
            (prices["stock_code"] == feature["stock_code"])
            & (prices["date"] > feature["date"])
        ]
        if stock_prices.empty:
            missing_next_price.append(
                {
                    "date": feature["date"].date().isoformat() if pd.notna(feature["date"]) else None,
                    "stock_code": feature["stock_code"],
                }
            )
        else:
            labelable_rows += 1

    preview_dataset = build_labeled_dataset(features_path, prices_path)
    feature_dates = features["date"].dropna()
    feature_calendar_days = (
        int((feature_dates.max() - feature_dates.min()).days) + 1 if not feature_dates.empty else 0
    )
    target_calendar_end_date = (
        (feature_dates.min() + pd.Timedelta(days=min_calendar_days - 1)).date().isoformat()
        if not feature_dates.empty and min_calendar_days > 0
        else None
    )
    feature_stock_count = int(features["stock_code"].nunique()) if "stock_code" in features else 0
    has_min_calendar_days = feature_calendar_days >= min_calendar_days
    has_min_stocks = feature_stock_count >= min_stocks
    has_labelable_rows = labelable_rows > 0
    return {
        "ok": has_labelable_rows and has_min_calendar_days and has_min_stocks,
        "prd_progress": {
            "min_calendar_days": min_calendar_days,
            "feature_calendar_days": feature_calendar_days,
            "remaining_calendar_days": max(min_calendar_days - feature_calendar_days, 0),
            "target_calendar_end_date": target_calendar_end_date,
            "min_stocks": min_stocks,
            "feature_stock_count": feature_stock_count,
            "remaining_stocks": max(min_stocks - feature_stock_count, 0),
        },
        "readiness": {
            "has_labelable_rows": has_labelable_rows,
            "has_min_calendar_days": has_min_calendar_days,
            "has_min_stocks": has_min_stocks,
        },
        "features": {
            "rows": int(len(features)),
            "stock_count": feature_stock_count,
            "date_count": int(features["date"].nunique()) if "date" in features else 0,
            "start_date": features["date"].min().date().isoformat() if len(features) else None,
            "end_date": features["date"].max().date().isoformat() if len(features) else None,
        },
        "prices": {
            "rows": int(len(prices)),
            "stock_count": int(prices["stock_code"].nunique()) if "stock_code" in prices else 0,
            "date_count": int(prices["date"].nunique()) if "date" in prices else 0,
            "start_date": prices["date"].min().date().isoformat() if len(prices) else None,
            "end_date": prices["date"].max().date().isoformat() if len(prices) else None,
        },
        "labeling": {
            "labelable_feature_rows": labelable_rows,
            "labeled_dataset_rows": int(len(preview_dataset)),
            "missing_next_price_count": len(missing_next_price),
            "missing_next_price_preview": missing_next_price[:10],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check signal-learning feature/price readiness")
    parser.add_argument("--features", default="data/features.csv")
    parser.add_argument("--prices", default="data/prices.csv")
    parser.add_argument("--min-calendar-days", type=int, default=90)
    parser.add_argument("--min-stocks", type=int, default=3)
    args = parser.parse_args()

    result = check_signal_learning_inputs(
        args.features,
        args.prices,
        min_calendar_days=args.min_calendar_days,
        min_stocks=args.min_stocks,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
