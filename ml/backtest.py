"""Backtest utilities for prediction outputs."""

from __future__ import annotations

import pandas as pd

from ml.evaluation import evaluate_predictions


def evaluate_long_only_backtest(dataset: pd.DataFrame, prediction_column: str = "predicted_up") -> dict[str, float | int]:
    """Evaluate a simple long-only strategy that buys rows predicted up."""
    return evaluate_predictions(dataset, prediction_column)
