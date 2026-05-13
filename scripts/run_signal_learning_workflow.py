"""Run the PRD signal-learning workflow from feature and price CSV inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.backtest import evaluate_backtest_suite
from ml.dataset import build_labeled_dataset
from ml.evaluation import evaluate_baselines, split_by_time
from ml.training import load_logistic_regression
from ml.verification import verify_labeled_dataset
from scripts.check_signal_learning_inputs import check_signal_learning_inputs
from scripts.train_outlook_model import train_and_evaluate_model


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_stale_outputs(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)


def evaluate_dataset(dataset: pd.DataFrame) -> dict:
    train, validation, test = split_by_time(dataset)
    return {
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        },
        "train": evaluate_baselines(train),
        "validation": evaluate_baselines(validation),
        "test": evaluate_baselines(test),
    }


def run_signal_learning_workflow(
    features_csv: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
    min_calendar_days: int = 90,
    min_stocks: int = 3,
    epochs: int = 500,
    learning_rate: float = 0.1,
    min_trade_count: int = 5,
    min_selected_stock_count: int = 2,
    continue_on_verification_failure: bool = False,
) -> dict:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    dataset_path = output_root / "ml_dataset.csv"
    verification_path = output_root / "verification.json"
    baseline_metrics_path = output_root / "baseline_metrics.json"
    backtest_metrics_path = output_root / "backtest_metrics.json"
    model_path = output_root / "outlook_logistic_v1.json"
    model_metrics_path = output_root / "outlook_logistic_v1.metrics.json"
    summary_path = output_root / "workflow_summary.json"

    input_readiness = check_signal_learning_inputs(
        features_csv,
        prices_csv,
        min_calendar_days=min_calendar_days,
        min_stocks=min_stocks,
    )
    summary = {
        "ok": False,
        "input_readiness": input_readiness,
        "dataset": str(dataset_path),
        "verification": None,
        "baseline_metrics": None,
        "backtest_metrics": None,
        "model": None,
        "model_metrics": None,
    }
    if not input_readiness.get("ok"):
        summary["stopped_at"] = "input_readiness"
        _remove_stale_outputs(
            [
                dataset_path,
                verification_path,
                baseline_metrics_path,
                backtest_metrics_path,
                model_path,
                model_metrics_path,
            ]
        )
        _write_json(summary_path, summary)
        return summary

    dataset = build_labeled_dataset(features_csv, prices_csv, dataset_path)
    verification = verify_labeled_dataset(
        dataset,
        min_calendar_days=min_calendar_days,
        min_stocks=min_stocks,
    )
    verification_payload = verification.to_dict()
    _write_json(verification_path, verification_payload)

    summary["verification"] = str(verification_path)
    if not verification.ok and not continue_on_verification_failure:
        summary["verification_ok"] = False
        summary["stopped_at"] = "verification"
        _write_json(summary_path, summary)
        return summary

    baseline_metrics = evaluate_dataset(dataset)
    _write_json(baseline_metrics_path, baseline_metrics)

    model_metrics = train_and_evaluate_model(
        dataset=dataset,
        output_path=model_path,
        epochs=epochs,
        learning_rate=learning_rate,
        min_trade_count=min_trade_count,
        min_selected_stock_count=min_selected_stock_count,
    )
    _write_json(model_metrics_path, model_metrics)
    backtest_metrics = evaluate_backtest_suite(dataset, load_logistic_regression(model_path))
    _write_json(backtest_metrics_path, backtest_metrics)

    summary.update(
        {
            "ok": verification.ok,
            "verification_ok": verification.ok,
            "baseline_metrics": str(baseline_metrics_path),
            "backtest_metrics": str(backtest_metrics_path),
            "model": str(model_path),
            "model_metrics": str(model_metrics_path),
            "validation_success_gate": model_metrics["validation"]["success_gate"],
            "test_success_gate": model_metrics["test"]["success_gate"],
        }
    )
    _write_json(summary_path, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the signal-learning PRD workflow")
    parser.add_argument("--features", required=True, help="Feature CSV")
    parser.add_argument("--prices", required=True, help="Price CSV")
    parser.add_argument("--output-dir", required=True, help="Directory for all workflow outputs")
    parser.add_argument("--min-calendar-days", type=int, default=90)
    parser.add_argument("--min-stocks", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    parser.add_argument("--min-trade-count", type=int, default=5)
    parser.add_argument("--min-selected-stock-count", type=int, default=2)
    parser.add_argument(
        "--continue-on-verification-failure",
        action="store_true",
        help="Continue to baseline/model outputs even when PRD dataset gates fail",
    )
    args = parser.parse_args()

    summary = run_signal_learning_workflow(
        features_csv=args.features,
        prices_csv=args.prices,
        output_dir=args.output_dir,
        min_calendar_days=args.min_calendar_days,
        min_stocks=args.min_stocks,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        min_trade_count=args.min_trade_count,
        min_selected_stock_count=args.min_selected_stock_count,
        continue_on_verification_failure=args.continue_on_verification_failure,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("verification_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
