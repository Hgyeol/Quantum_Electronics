import tempfile
import unittest
from pathlib import Path

from scripts.audit_signal_learning_prd import audit_signal_learning_prd


class SignalLearningPRDAuditTests(unittest.TestCase):
    def test_audit_reports_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            result = audit_signal_learning_prd(
                dataset_path=tmp / "missing_dataset.csv",
                workflow_dir=tmp / "missing_workflow",
                min_calendar_days=1,
                min_stocks=1,
            )

            self.assertFalse(result["ok"])
            failed_names = {item["name"] for item in result["missing_or_failed"]}
            self.assertIn("technical.dataset_ready", failed_names)
            self.assertIn("phase3.model_artifact_output", failed_names)
            self.assertIn("model.success_gate", failed_names)


if __name__ == "__main__":
    unittest.main()
