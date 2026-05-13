"""Verify a labeled ML dataset against PRD success criteria."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.verification import verify_labeled_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify stock outlook ML dataset readiness")
    parser.add_argument("--dataset", required=True, help="CSV produced by scripts/build_ml_dataset.py")
    parser.add_argument("--min-calendar-days", type=int, default=90)
    parser.add_argument("--min-stocks", type=int, default=3)
    args = parser.parse_args()

    dataset = pd.read_csv(args.dataset, dtype={"stock_code": str})
    result = verify_labeled_dataset(dataset, args.min_calendar_days, args.min_stocks)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
