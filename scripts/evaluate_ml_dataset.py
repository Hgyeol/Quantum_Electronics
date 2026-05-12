"""Evaluate baseline rules on a labeled stock outlook dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.evaluation import evaluate_baselines, split_by_time


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate stock outlook signal baselines")
    parser.add_argument("--dataset", required=True, help="CSV produced by scripts/build_ml_dataset.py")
    args = parser.parse_args()

    dataset = pd.read_csv(args.dataset, dtype={"stock_code": str})
    train, validation, test = split_by_time(dataset)
    output = {
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "train": evaluate_baselines(train),
        "validation": evaluate_baselines(validation),
        "test": evaluate_baselines(test),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
