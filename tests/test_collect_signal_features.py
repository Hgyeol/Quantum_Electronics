import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from analysis.models import OutlookReport
from analysis.scoring import combine_signals
from scripts.collect_signal_features import collect_signal_features
from scripts.collect_signal_features import _read_codes


class FakeOutlookService:
    def build_report(self, code):
        return OutlookReport(
            stock_code=code,
            stock_name=f"stock-{code}",
            score=combine_signals(),
        )


class CollectSignalFeaturesTests(unittest.TestCase):
    def test_read_codes_skips_stock_code_csv_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stock_codes.csv"
            path.write_text(
                "stock_code,stock_name,market\n005930,삼성전자,KOSPI\n000660,SK하이닉스,KOSPI\n",
                encoding="utf-8",
            )

            args = type("Args", (), {"codes": ["005930"], "codes_file": str(path)})

            self.assertEqual(_read_codes(args), ["005930", "000660"])

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
                allow_date_override=True,
            )
            collect_signal_features(
                codes=["005930"],
                as_of_date=pd.Timestamp("2026-05-12").date(),
                reports_jsonl=reports_path,
                features_csv=features_path,
                service=FakeOutlookService(),
                allow_date_override=True,
            )

            reports = [json.loads(line) for line in reports_path.read_text(encoding="utf-8").splitlines()]
            features = pd.read_csv(features_path, dtype={"stock_code": str})

            self.assertEqual(result, {"reports": 2, "features": 2})
            self.assertEqual(len(reports), 3)
            self.assertEqual(len(features), 2)
            self.assertEqual(set(features["stock_code"]), {"005930", "000660"})
            self.assertEqual(set(features["date"]), {"2026-05-12"})

    def test_collect_signal_features_can_skip_existing_report_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_path = Path(tmpdir) / "reports.jsonl"
            features_path = Path(tmpdir) / "features.csv"

            collect_signal_features(
                codes=["005930"],
                as_of_date=pd.Timestamp("2026-05-12").date(),
                reports_jsonl=reports_path,
                features_csv=features_path,
                service=FakeOutlookService(),
                allow_date_override=True,
                skip_existing_reports=True,
            )
            result = collect_signal_features(
                codes=["005930"],
                as_of_date=pd.Timestamp("2026-05-12").date(),
                reports_jsonl=reports_path,
                features_csv=features_path,
                service=FakeOutlookService(),
                allow_date_override=True,
                skip_existing_reports=True,
            )

            reports = [json.loads(line) for line in reports_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(result, {"reports": 0, "features": 1})
            self.assertEqual(len(reports), 1)

    def test_collect_signal_features_rejects_backdated_live_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yesterday = date.today() - timedelta(days=1)

            with self.assertRaises(ValueError):
                collect_signal_features(
                    codes=["005930"],
                    as_of_date=yesterday,
                    reports_jsonl=Path(tmpdir) / "reports.jsonl",
                    features_csv=Path(tmpdir) / "features.csv",
                    service=FakeOutlookService(),
                )


if __name__ == "__main__":
    unittest.main()
