"""Evaluation and backtest metrics for signal learning datasets."""

from __future__ import annotations

import math

import pandas as pd


def split_by_time(
    dataset: pd.DataFrame,
    train_ratio: float = 0.7,
    validation_ratio: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be between 0 and 1")
    if not 0 <= validation_ratio < 1:
        raise ValueError("validation_ratio must be between 0 and 1")
    if train_ratio + validation_ratio >= 1:
        raise ValueError("train_ratio + validation_ratio must be less than 1")

    ordered = dataset.copy()
    ordered["date"] = pd.to_datetime(ordered["date"])
    ordered = ordered.sort_values(["date", "stock_code"]).reset_index(drop=True)
    train_end = int(len(ordered) * train_ratio)
    validation_end = train_end + int(len(ordered) * validation_ratio)
    return (
        ordered.iloc[:train_end].reset_index(drop=True),
        ordered.iloc[train_end:validation_end].reset_index(drop=True),
        ordered.iloc[validation_end:].reset_index(drop=True),
    )


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity = (1 + returns.fillna(0.0)).cumprod()
    drawdown = equity / equity.cummax() - 1
    return float(drawdown.min())


def _roc_auc(y_true: pd.Series, scores: pd.Series) -> float:
    pairs = pd.DataFrame({"target": y_true.astype(int), "score": scores.astype(float)}).dropna()
    positives = pairs[pairs["target"] == 1]
    negatives = pairs[pairs["target"] == 0]
    if positives.empty or negatives.empty:
        return 0.0

    wins = 0.0
    total = len(positives) * len(negatives)
    for positive_score in positives["score"]:
        wins += (positive_score > negatives["score"]).sum()
        wins += 0.5 * (positive_score == negatives["score"]).sum()
    return float(wins / total)


def evaluate_predictions(
    dataset: pd.DataFrame,
    prediction_column: str,
    score_column: str | None = None,
) -> dict[str, float | int]:
    if "target_up" not in dataset.columns:
        raise ValueError("dataset must include target_up")
    if "next_day_return" not in dataset.columns:
        raise ValueError("dataset must include next_day_return")
    if prediction_column not in dataset.columns:
        raise ValueError(f"dataset must include {prediction_column}")
    if score_column is not None and score_column not in dataset.columns:
        raise ValueError(f"dataset must include {score_column}")

    required_columns = ["target_up", "next_day_return", prediction_column]
    if score_column:
        required_columns.append(score_column)
    evaluated = dataset.dropna(subset=required_columns).copy()
    if evaluated.empty:
        return {
            "rows": 0,
            "accuracy": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "roc_auc": 0.0,
            "win_rate": 0.0,
            "trade_count": 0,
            "turnover": 0.0,
            "mean_return_when_pred_up": 0.0,
            "cumulative_return": 0.0,
            "max_drawdown": 0.0,
        }

    y_true = evaluated["target_up"].astype(int)
    y_pred = evaluated[prediction_column].astype(int)
    y_score = pd.to_numeric(evaluated[score_column or prediction_column], errors="coerce").fillna(0.0)
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    selected_returns = evaluated.loc[y_pred == 1, "next_day_return"]
    cumulative_return = float((1 + selected_returns.fillna(0.0)).prod() - 1) if not selected_returns.empty else 0.0

    return {
        "rows": int(len(evaluated)),
        "accuracy": round(float((y_true == y_pred).mean()), 4),
        "precision": round(_safe_divide(tp, tp + fp), 4),
        "recall": round(_safe_divide(tp, tp + fn), 4),
        "roc_auc": round(_roc_auc(y_true, y_score), 4),
        "win_rate": round(float((selected_returns > 0).mean()), 4) if not selected_returns.empty else 0.0,
        "trade_count": int((y_pred == 1).sum()),
        "turnover": round(float((y_pred == 1).mean()), 4),
        "mean_return_when_pred_up": round(float(selected_returns.mean()), 6) if not selected_returns.empty else 0.0,
        "cumulative_return": round(cumulative_return, 6),
        "max_drawdown": round(_max_drawdown(selected_returns), 6),
    }


def _predict_by_score(dataset: pd.DataFrame, score_column: str, threshold: float = 0.0) -> pd.Series:
    if score_column not in dataset.columns:
        return pd.Series([0] * len(dataset), index=dataset.index)
    score = pd.to_numeric(dataset[score_column], errors="coerce").fillna(-math.inf)
    return (score > threshold).astype(int)


def evaluate_baselines(dataset: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    evaluated = dataset.copy()
    evaluated["baseline_always_up"] = 1
    evaluated["baseline_total_rule_score"] = _predict_by_score(evaluated, "total_rule_score")
    evaluated["baseline_quant_score"] = _predict_by_score(evaluated, "quant_score")
    evaluated["baseline_ai_score"] = _predict_by_score(evaluated, "ai_score")
    return {
        "always_up": evaluate_predictions(evaluated, "baseline_always_up"),
        "total_rule_score_gt_0": evaluate_predictions(evaluated, "baseline_total_rule_score"),
        "quant_score_gt_0": evaluate_predictions(evaluated, "baseline_quant_score"),
        "ai_score_gt_0": evaluate_predictions(evaluated, "baseline_ai_score"),
    }
