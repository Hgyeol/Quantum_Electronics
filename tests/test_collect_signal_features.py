import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.models import OutlookReport
from analysis.scoring import combine_signals
from scripts.collect_signal_features import collect_signal_features


class FakeOutlookService:
    def build_report(self, code):
        return OutlookReport(
            stock_code=code,
            stock_name=f"stock-{code}",
            score=combine_signals(),
        )


class CollectSignalFeaturesTests(unittest.TestCase):
    def test_collect_signal_features_appends_reports_and_dedupes_features(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_path = Path(tmpdir) / "reports.jsonl"
            features_path = Path(tmpdir) / "features.csv"

            result = collect_signal_features(
                codes=["005930", "000660"],
                as_of_date=pd.Timestamp("2026-05-12").date(),
                reports_jsonl=reports_path,
                features_csv=features_path,
                service=FakeOutlookService(),
            )
            collect_signal_features(
                codes=["005930"],
                as_of_date=pd.Timestamp("2026-05-12").date(),
                reports_jsonl=reports_path,
                features_csv=features_path,
                service=FakeOutlookService(),
            )

            reports = [json.loads(line) for line in reports_path.read_text(encoding="utf-8").splitlines()]
            features = pd.read_csv(features_path, dtype={"stock_code": str})

            self.assertEqual(result, {"reports": 2, "features": 2})
            self.assertEqual(len(reports), 3)
            self.assertEqual(len(features), 2)
            self.assertEqual(set(features["stock_code"]), {"005930", "000660"})
            self.assertEqual(set(features["date"]), {"2026-05-12"})


if __name__ == "__main__":
    unittest.main()
