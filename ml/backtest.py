"""Backtest utilities for prediction outputs."""

from __future__ import annotations

import pandas as pd

from ml.evaluation import evaluate_predictions, split_by_time


def evaluate_long_only_backtest(dataset: pd.DataFrame, prediction_column: str = "predicted_up") -> dict[str, float | int]:
    """Evaluate a simple long-only strategy that buys rows predicted up."""
    return evaluate_predictions(dataset, prediction_column)


def _with_rule_predictions(dataset: pd.DataFrame) -> pd.DataFrame:
    scored = dataset.copy()
    scored["baseline_always_up"] = 1
    for source_column, prediction_column in {
        "total_rule_score": "baseline_total_rule_score",
        "quant_score": "baseline_quant_score",
        "ai_score": "baseline_ai_score",
    }.items():
        if source_column in scored:
            scored[prediction_column] = (pd.to_numeric(scored[source_column], errors="coerce").fillna(0) > 0).astype(int)
        else:
            scored[prediction_column] = 0
    return scored


def evaluate_backtest_suite(dataset: pd.DataFrame, model=None) -> dict:
    """Evaluate baseline and optional model long-only backtests by time split."""
    train, validation, test = split_by_time(dataset)
    output = {
        "rows": {
            "train": len(train),
            "validation": len(validation),
            "test": len(test),
        }
    }
    for name, split in {"validation": validation, "test": test}.items():
        scored = _with_rule_predictions(split)
        metrics = {
            "always_up": evaluate_long_only_backtest(scored, "baseline_always_up"),
            "total_rule_score_gt_0": evaluate_long_only_backtest(scored, "baseline_total_rule_score"),
            "quant_score_gt_0": evaluate_long_only_backtest(scored, "baseline_quant_score"),
            "ai_score_gt_0": evaluate_long_only_backtest(scored, "baseline_ai_score"),
        }
        if model is not None and not scored.empty:
            scored["ml_probability_up"] = model.predict_proba(scored)
            scored["ml_predicted_up"] = model.predict(scored)
            metrics["model"] = evaluate_predictions(scored, "ml_predicted_up", "ml_probability_up")
        output[name] = metrics
    return output
