"""Build a next-day labeled dataset from signal features and close prices."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.dataset import build_labeled_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a labeled stock outlook ML dataset")
    parser.add_argument("--features", required=True, help="CSV containing date, stock_code, and signal features")
    parser.add_argument("--prices", required=True, help="CSV containing date, stock_code, close")
    parser.add_argument("--output", required=True, help="Output CSV path, e.g. data/ml_dataset.csv")
    args = parser.parse_args()

    dataset = build_labeled_dataset(args.features, args.prices, args.output)
    print(f"wrote {len(dataset)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
