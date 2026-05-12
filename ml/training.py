"""Small dependency-free logistic regression trainer for signal datasets."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ml.dataset import prepare_model_features


@dataclass
class LogisticRegressionModel:
    feature_columns: list[str]
    means: dict[str, float]
    stds: dict[str, float]
    weights: dict[str, float]
    bias: float
    model_name: str = "logistic_regression_v1"
    features_version: str = "v1"

    def _standardize(self, features: pd.DataFrame) -> pd.DataFrame:
        standardized = features.copy()
        for column in self.feature_columns:
            std = self.stds.get(column) or 1.0
            standardized[column] = (standardized[column] - self.means.get(column, 0.0)) / std
        return standardized

    def predict_proba(self, dataset: pd.DataFrame) -> pd.Series:
        features = prepare_model_features(dataset, self.feature_columns)
        standardized = self._standardize(features)
        logits = []
        for _, row in standardized.iterrows():
            logit = self.bias + sum(self.weights[column] * float(row[column]) for column in self.feature_columns)
            logits.append(1 / (1 + math.exp(-max(min(logit, 35), -35))))
        return pd.Series(logits, index=dataset.index)

    def predict(self, dataset: pd.DataFrame, threshold: float = 0.5) -> pd.Series:
        return (self.predict_proba(dataset) >= threshold).astype(int)

    def to_dict(self) -> dict:
        return {
            "model_type": "logistic_regression",
            "model_name": self.model_name,
            "features_version": self.features_version,
            "feature_columns": self.feature_columns,
            "means": self.means,
            "stds": self.stds,
            "weights": self.weights,
            "bias": self.bias,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "LogisticRegressionModel":
        return cls(
            feature_columns=list(payload["feature_columns"]),
            means={key: float(value) for key, value in payload["means"].items()},
            stds={key: float(value) for key, value in payload["stds"].items()},
            weights={key: float(value) for key, value in payload["weights"].items()},
            bias=float(payload["bias"]),
            model_name=payload.get("model_name", "logistic_regression_v1"),
            features_version=payload.get("features_version", "v1"),
        )

    def save(self, path: str | Path) -> None:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_logistic_regression(path: str | Path) -> LogisticRegressionModel:
    return LogisticRegressionModel.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def train_logistic_regression(
    dataset: pd.DataFrame,
    feature_columns: list[str] | None = None,
    learning_rate: float = 0.1,
    epochs: int = 500,
    l2: float = 0.001,
    model_name: str = "logistic_regression_v1",
    features_version: str = "v1",
) -> LogisticRegressionModel:
    if "target_up" not in dataset.columns:
        raise ValueError("dataset must include target_up")
    if dataset["target_up"].nunique() < 2:
        raise ValueError("target_up must include both classes")

    features = prepare_model_features(dataset, feature_columns)
    columns = list(features.columns)
    means = {column: float(features[column].mean()) for column in columns}
    stds = {column: float(features[column].std() or 1.0) for column in columns}
    standardized = features.copy()
    for column in columns:
        standardized[column] = (standardized[column] - means[column]) / stds[column]

    y = dataset["target_up"].astype(float).reset_index(drop=True)
    x = standardized.reset_index(drop=True)
    weights = {column: 0.0 for column in columns}
    bias = 0.0
    n = len(x)

    for _ in range(epochs):
        gradients = {column: 0.0 for column in columns}
        bias_gradient = 0.0
        for idx, row in x.iterrows():
            logit = bias + sum(weights[column] * float(row[column]) for column in columns)
            prediction = 1 / (1 + math.exp(-max(min(logit, 35), -35)))
            error = prediction - float(y.iloc[idx])
            bias_gradient += error
            for column in columns:
                gradients[column] += error * float(row[column])
        bias -= learning_rate * (bias_gradient / n)
        for column in columns:
            regularization = l2 * weights[column]
            weights[column] -= learning_rate * ((gradients[column] / n) + regularization)

    return LogisticRegressionModel(
        feature_columns=columns,
        means=means,
        stds=stds,
        weights=weights,
        bias=bias,
        model_name=model_name,
        features_version=features_version,
    )
