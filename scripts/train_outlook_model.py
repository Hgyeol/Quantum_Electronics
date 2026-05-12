"""Train a logistic regression model on a labeled stock outlook dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.evaluation import evaluate_baselines, evaluate_predictions, split_by_time, success_gate
from ml.training import train_logistic_regression


def train_and_evaluate_model(
    dataset: pd.DataFrame,
    output_path: str | Path,
    epochs: int = 500,
    learning_rate: float = 0.1,
    min_trade_count: int = 5,
    min_selected_stock_count: int = 2,
) -> dict:
    train, validation, test = split_by_time(dataset)
    model = train_logistic_regression(train, epochs=epochs, learning_rate=learning_rate)
    model.save(output_path)

    validation_scored = validation.copy()
    test_scored = test.copy()
    validation_scored["ml_probability_up"] = model.predict_proba(validation_scored)
    validation_scored["ml_predicted_up"] = model.predict(validation_scored)
    test_scored["ml_probability_up"] = model.predict_proba(test_scored)
    test_scored["ml_predicted_up"] = model.predict(test_scored)
    validation_baselines = evaluate_baselines(validation)
    test_baselines = evaluate_baselines(test)
    validation_model_metrics = evaluate_predictions(validation_scored, "ml_predicted_up", "ml_probability_up")
    test_model_metrics = evaluate_predictions(test_scored, "ml_predicted_up", "ml_probability_up")
    coefficient_importance = [
        {
            "feature": feature,
            "coefficient": coefficient,
            "absolute_coefficient": abs(coefficient),
        }
        for feature, coefficient in model.weights.items()
    ]
    coefficient_importance = sorted(
        coefficient_importance,
        key=lambda item: item["absolute_coefficient"],
        reverse=True,
    )
    return {
        "model": str(output_path),
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "validation": {
            "baselines": validation_baselines,
            "model": validation_model_metrics,
            "success_gate": success_gate(
                validation_model_metrics,
                validation_baselines,
                min_trade_count=min_trade_count,
                min_selected_stock_count=min_selected_stock_count,
            ),
        },
        "test": {
            "baselines": test_baselines,
            "model": test_model_metrics,
            "success_gate": success_gate(
                test_model_metrics,
                test_baselines,
                min_trade_count=min_trade_count,
                min_selected_stock_count=min_selected_stock_count,
            ),
        },
        "coefficients": model.weights,
        "coefficient_importance": coefficient_importance,
        "bias": model.bias,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Train an outlook prediction model")
    parser.add_argument("--dataset", required=True, help="CSV produced by scripts/build_ml_dataset.py")
    parser.add_argument("--output", required=True, help="Model artifact JSON path")
    parser.add_argument("--metrics-output", help="Optional JSON path for training/evaluation metrics")
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    parser.add_argument("--min-trade-count", type=int, default=5)
    parser.add_argument("--min-selected-stock-count", type=int, default=2)
    args = parser.parse_args()

    dataset = pd.read_csv(args.dataset, dtype={"stock_code": str})
    output = train_and_evaluate_model(
        dataset=dataset,
        output_path=args.output,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        min_trade_count=args.min_trade_count,
        min_selected_stock_count=args.min_selected_stock_count,
    )
    rendered = json.dumps(output, ensure_ascii=False, indent=2)
    if args.metrics_output:
        metrics_path = Path(args.metrics_output)
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
