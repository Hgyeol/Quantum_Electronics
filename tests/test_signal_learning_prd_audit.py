import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from ml.dataset import FEATURE_COLUMNS, LABEL_COLUMNS
from scripts.audit_signal_learning_prd import audit_signal_learning_prd, main


def _feature_row(date: str, stock_code: str) -> dict:
    row = {column: 0 for column in FEATURE_COLUMNS}
    row.update(
        {
            "date": date,
            "stock_code": stock_code,
            "stock_name": stock_code,
            "llm_direction": "neutral",
        }
    )
    return row


def _dataset_row(date: str, stock_code: str, target_up: int) -> dict:
    row = {column: 0 for column in FEATURE_COLUMNS + LABEL_COLUMNS}
    row.update(_feature_row(date, stock_code))
    row.update(
        {
            "close": 100.0,
            "next_close": 101.0 if target_up else 99.0,
            "next_day_return": 0.01 if target_up else -0.01,
            "target_up": target_up,
        }
    )
    return row


class SignalLearningPRDAuditTests(unittest.TestCase):
    def test_audit_reports_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            result = audit_signal_learning_prd(
                dataset_path=tmp / "missing_dataset.csv",
                workflow_dir=tmp / "missing_workflow",
                features_path=tmp / "missing_features.csv",
                prices_path=tmp / "missing_prices.csv",
                min_calendar_days=1,
                min_stocks=1,
            )

            self.assertFalse(result["ok"])
            failed_names = {item["name"] for item in result["missing_or_failed"]}
            self.assertIn("technical.input_readiness", failed_names)
            self.assertIn("technical.dataset_ready", failed_names)
            self.assertIn("phase3.model_artifact_output", failed_names)
            self.assertIn("model.success_gate", failed_names)
            cache_check = next(item for item in result["checks"] if item["name"] == "technical.llm_cache_available")
            self.assertTrue(cache_check["ok"])
            api_check = next(item for item in result["checks"] if item["name"] == "service.api_ml_prediction_contract")
            self.assertTrue(api_check["ok"])

    def test_audit_accepts_complete_synthetic_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workflow_dir = tmp / "workflow"
            workflow_dir.mkdir()
            features_path = tmp / "features.csv"
            prices_path = tmp / "prices.csv"
            dataset_path = workflow_dir / "ml_dataset.csv"

            pd.DataFrame(
                [
                    _feature_row("2026-01-01", "005930"),
                    _feature_row("2026-01-01", "000660"),
                ],
                columns=FEATURE_COLUMNS,
            ).to_csv(features_path, index=False)
            pd.DataFrame(
                [
                    {"date": "2026-01-01", "stock_code": "005930", "close": 100.0},
                    {"date": "2026-01-02", "stock_code": "005930", "close": 101.0},
                    {"date": "2026-01-01", "stock_code": "000660", "close": 100.0},
                    {"date": "2026-01-02", "stock_code": "000660", "close": 99.0},
                ]
            ).to_csv(prices_path, index=False)
            pd.DataFrame(
                [
                    _dataset_row("2026-01-01", "005930", 1),
                    _dataset_row("2026-01-01", "000660", 0),
                ],
                columns=FEATURE_COLUMNS + LABEL_COLUMNS,
            ).to_csv(dataset_path, index=False)

            for name in ["verification.json", "baseline_metrics.json", "backtest_metrics.json", "workflow_summary.json"]:
                (workflow_dir / name).write_text("{}", encoding="utf-8")
            (workflow_dir / "outlook_logistic_v1.json").write_text(
                json.dumps(
                    {
                        "model_type": "logistic_regression",
                        "model_name": "logistic_regression_v1",
                        "features_version": "v1",
                        "feature_columns": ["quant_score"],
                    }
                ),
                encoding="utf-8",
            )
            (workflow_dir / "outlook_logistic_v1.metrics.json").write_text(
                json.dumps(
                    {
                        "validation": {"success_gate": {"passes": True}},
                        "test": {"success_gate": {"passes": True}},
                    }
                ),
                encoding="utf-8",
            )

            result = audit_signal_learning_prd(
                dataset_path=dataset_path,
                workflow_dir=workflow_dir,
                features_path=features_path,
                prices_path=prices_path,
                min_calendar_days=1,
                min_stocks=2,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["missing_or_failed"], [])

    def test_cli_defaults_match_workflow_output_dir(self):
        output = StringIO()
        with patch("sys.argv", ["audit_signal_learning_prd.py"]):
            with redirect_stdout(output):
                exit_code = main()

        self.assertIn(exit_code, (0, 1))
        self.assertIn("ml/artifacts/signal_learning_v1/ml_dataset.csv", output.getvalue())


if __name__ == "__main__":
    unittest.main()
