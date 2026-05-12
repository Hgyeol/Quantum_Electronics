"""Runtime ML prediction integration for OutlookService."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from analysis.models import OutlookReport
from ml.features import feature_row_from_report
from ml.prediction import MLPrediction
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
        probability = float(self.model.predict_proba(pd.DataFrame([row])).iloc[0])
        return MLPrediction(
            probability=round(probability, 6),
            model=self.model_name,
            features_version=self.features_version,
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
