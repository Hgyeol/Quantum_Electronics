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
    unique_dates = pd.Series(ordered["date"].drop_duplicates().sort_values().tolist())
    train_date_end = int(len(unique_dates) * train_ratio)
    validation_date_end = train_date_end + int(len(unique_dates) * validation_ratio)
    if len(unique_dates) >= 3:
        train_date_end = min(max(train_date_end, 1), len(unique_dates) - 2)
        validation_date_end = min(max(validation_date_end, train_date_end + 1), len(unique_dates) - 1)
    train_dates = set(unique_dates.iloc[:train_date_end])
    validation_dates = set(unique_dates.iloc[train_date_end:validation_date_end])
    test_dates = set(unique_dates.iloc[validation_date_end:])
    return (
        ordered.loc[ordered["date"].isin(train_dates)].reset_index(drop=True),
        ordered.loc[ordered["date"].isin(validation_dates)].reset_index(drop=True),
        ordered.loc[ordered["date"].isin(test_dates)].reset_index(drop=True),
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
            "date_count": 0,
            "stock_count": 0,
            "selected_stock_count": 0,
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
    selected = evaluated.loc[y_pred == 1]
    selected_returns = selected["next_day_return"]
    cumulative_return = float((1 + selected_returns.fillna(0.0)).prod() - 1) if not selected_returns.empty else 0.0

    return {
        "rows": int(len(evaluated)),
        "date_count": int(evaluated["date"].nunique()) if "date" in evaluated.columns else 0,
        "stock_count": int(evaluated["stock_code"].nunique()) if "stock_code" in evaluated.columns else 0,
        "selected_stock_count": int(selected["stock_code"].nunique()) if "stock_code" in selected.columns else 0,
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


def success_gate(
    model_metrics: dict[str, float | int],
    baseline_metrics: dict[str, dict[str, float | int]],
    baseline_name: str = "total_rule_score_gt_0",
    min_trade_count: int = 5,
    min_selected_stock_count: int = 2,
) -> dict[str, bool | float | int | str]:
    """Check PRD model success against a baseline.

    The PRD considers a model useful if validation/test improves either
    precision or mean selected return while still making enough trades across
    more than one stock to reduce single-name overfitting risk.
    """
    baseline = baseline_metrics.get(baseline_name)
    if baseline is None:
        raise ValueError(f"baseline not found: {baseline_name}")

    model_precision = float(model_metrics.get("precision", 0.0))
    baseline_precision = float(baseline.get("precision", 0.0))
    model_return = float(model_metrics.get("mean_return_when_pred_up", 0.0))
    baseline_return = float(baseline.get("mean_return_when_pred_up", 0.0))
    trade_count = int(model_metrics.get("trade_count", 0))
    selected_stock_count = int(model_metrics.get("selected_stock_count", 0))
    improves_precision = model_precision > baseline_precision
    improves_mean_return = model_return > baseline_return
    enough_trades = trade_count >= min_trade_count
    enough_stock_coverage = selected_stock_count >= min_selected_stock_count
    passes = enough_trades and enough_stock_coverage and (improves_precision or improves_mean_return)

    return {
        "passes": passes,
        "baseline": baseline_name,
        "model_precision": model_precision,
        "baseline_precision": baseline_precision,
        "model_mean_return": model_return,
        "baseline_mean_return": baseline_return,
        "trade_count": trade_count,
        "min_trade_count": min_trade_count,
        "selected_stock_count": selected_stock_count,
        "min_selected_stock_count": min_selected_stock_count,
        "improves_precision": improves_precision,
        "improves_mean_return": improves_mean_return,
        "enough_trades": enough_trades,
        "enough_stock_coverage": enough_stock_coverage,
    }
