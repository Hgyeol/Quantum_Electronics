"""Train a logistic regression model on a labeled stock outlook dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.evaluation import evaluate_baselines, evaluate_predictions, split_by_time
from ml.training import train_logistic_regression


def main() -> int:
    parser = argparse.ArgumentParser(description="Train an outlook prediction model")
    parser.add_argument("--dataset", required=True, help="CSV produced by scripts/build_ml_dataset.py")
    parser.add_argument("--output", required=True, help="Model artifact JSON path")
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    args = parser.parse_args()

    dataset = pd.read_csv(args.dataset, dtype={"stock_code": str})
    train, validation, test = split_by_time(dataset)
    model = train_logistic_regression(train, epochs=args.epochs, learning_rate=args.learning_rate)
    model.save(args.output)

    validation_scored = validation.copy()
    test_scored = test.copy()
    validation_scored["ml_probability_up"] = model.predict_proba(validation_scored)
    validation_scored["ml_predicted_up"] = model.predict(validation_scored)
    test_scored["ml_probability_up"] = model.predict_proba(test_scored)
    test_scored["ml_predicted_up"] = model.predict(test_scored)
    output = {
        "model": args.output,
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "validation": {
            "baselines": evaluate_baselines(validation),
            "model": evaluate_predictions(validation_scored, "ml_predicted_up", "ml_probability_up"),
        },
        "test": {
            "baselines": evaluate_baselines(test),
            "model": evaluate_predictions(test_scored, "ml_predicted_up", "ml_probability_up"),
        },
        "coefficients": model.weights,
        "bias": model.bias,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
