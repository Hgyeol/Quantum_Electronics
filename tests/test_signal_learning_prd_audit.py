import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts.audit_signal_learning_prd import audit_signal_learning_prd, main


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

    def test_cli_defaults_match_workflow_output_dir(self):
        output = StringIO()
        with patch("sys.argv", ["audit_signal_learning_prd.py"]):
            with redirect_stdout(output):
                exit_code = main()

        self.assertEqual(exit_code, 1)
        self.assertIn("ml/artifacts/signal_learning_v1/ml_dataset.csv", output.getvalue())


if __name__ == "__main__":
    unittest.main()
