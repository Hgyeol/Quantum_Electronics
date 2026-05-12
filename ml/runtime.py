"""Runtime ML prediction integration for OutlookService."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from analysis.models import OutlookReport
from ml.dataset import prepare_model_features
from ml.features import feature_row_from_report
from ml.prediction import MLFeatureContribution, MLPrediction
from ml.training import LogisticRegressionModel, load_logistic_regression


class OutlookMLPredictor:
    def __init__(
        self,
        model: LogisticRegressionModel,
        model_name: str = "logistic_regression_v1",
        features_version: str = "v1",
    ):
        self.model = model
        self.model_name = model_name
        self.features_version = features_version

    def predict_report(self, report: OutlookReport) -> MLPrediction:
        row = feature_row_from_report(report)
        row_frame = pd.DataFrame([row])
        probability = float(self.model.predict_proba(row_frame).iloc[0])
        contributions = self._top_contributions(row_frame)
        return MLPrediction(
            probability=round(probability, 6),
            model=self.model_name,
            features_version=self.features_version,
            rule_score=report.score.total_score,
            rule_direction=report.score.direction,
            explanation=self._explain(probability, report.score.total_score, contributions),
            top_contributions=contributions,
        )

    def _top_contributions(self, row_frame: pd.DataFrame, limit: int = 5) -> list[MLFeatureContribution]:
        features = prepare_model_features(row_frame, self.model.feature_columns)
        standardized = self.model._standardize(features)
        contributions: list[MLFeatureContribution] = []
        for column in self.model.feature_columns:
            value = float(features.iloc[0][column])
            contribution = float(self.model.weights.get(column, 0.0) * standardized.iloc[0][column])
            if contribution == 0:
                continue
            contributions.append(
                MLFeatureContribution(
                    feature=column,
                    value=round(value, 6),
                    contribution=round(contribution, 6),
                    direction="increase" if contribution > 0 else "decrease",
                )
            )
        return sorted(contributions, key=lambda item: abs(item.contribution), reverse=True)[:limit]

    def _explain(
        self,
        probability: float,
        rule_score: int,
        contributions: list[MLFeatureContribution],
    ) -> str:
        ml_direction = "positive" if probability >= 0.5 else "negative"
        rule_direction = "positive" if rule_score > 0 else "negative" if rule_score < 0 else "neutral"
        leading_features = ", ".join(item.feature for item in contributions[:3]) or "no dominant feature"
        return (
            f"ML direction is {ml_direction} from probability {probability:.3f}; "
            f"rule direction is {rule_direction} from total_rule_score {rule_score}. "
            f"Top model drivers: {leading_features}."
        )


def load_predictor_from_env() -> OutlookMLPredictor | None:
    model_path = os.getenv("OUTLOOK_ML_MODEL_PATH")
    if not model_path:
        return None
    path = Path(model_path)
    if not path.exists():
        return None
    return OutlookMLPredictor(
        load_logistic_regression(path),
        model_name=os.getenv("OUTLOOK_ML_MODEL_NAME", "logistic_regression_v1"),
        features_version=os.getenv("OUTLOOK_ML_FEATURES_VERSION", "v1"),
    )
