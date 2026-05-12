import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from analysis.models import OutlookReport
from analysis.scoring import combine_signals
from scripts.collect_daily_signal_learning_inputs import run_daily_signal_learning_collection


class FakeOutlookService:
    def build_report(self, code):
        return OutlookReport(
            stock_code=code,
            stock_name=f"stock-{code}",
            score=combine_signals(),
        )


class CollectDailySignalLearningInputsTests(unittest.TestCase):
    def test_daily_collection_exports_universe_prices_and_features(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            master = tmp / "kospi.csv"
            pd.DataFrame(
                [
                    {
                        "표준코드": "KR7005930003",
                        "단축코드": "005930",
                        "한글 종목명": "삼성전자보통주",
                        "한글 종목약명": "삼성전자",
                        "시장구분": "KOSPI",
                    },
                    {
                        "표준코드": "KR7000660001",
                        "단축코드": "000660",
                        "한글 종목명": "SK하이닉스보통주",
                        "한글 종목약명": "SK하이닉스",
                        "시장구분": "KOSPI",
                    },
                ]
            ).to_csv(master, index=False, encoding="cp949")

            def fake_price_fetcher(code, days, env_dv):
                return pd.DataFrame(
                    [
                        {"date": "20260511", "close": 100},
                        {"date": "20260512", "close": 101},
                    ]
                )

            result = run_daily_signal_learning_collection(
                stock_codes_csv=tmp / "stock_codes.csv",
                master_csv=master,
                stock_limit=2,
                prices_csv=tmp / "prices.csv",
                reports_jsonl=tmp / "reports.jsonl",
                features_csv=tmp / "features.csv",
                price_days=2,
                as_of_date=date.today(),
                price_fetcher=fake_price_fetcher,
                outlook_service=FakeOutlookService(),
            )

            self.assertEqual(result["stock_universe"]["count"], 2)
            self.assertEqual(result["prices"]["rows_written"], 4)
            self.assertEqual(result["features"]["features"], 2)
            self.assertIn("readiness", result)
            self.assertFalse(result["readiness"]["ok"])
            self.assertEqual(result["readiness"]["labeling"]["missing_next_price_count"], 2)
            self.assertTrue((tmp / "stock_codes.csv").exists())
            self.assertTrue((tmp / "prices.csv").exists())
            self.assertTrue((tmp / "features.csv").exists())
            self.assertTrue((tmp / "reports.jsonl").exists())

    def test_daily_collection_skips_workflow_when_not_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            master = tmp / "kospi.csv"
            pd.DataFrame(
                [
                    {
                        "표준코드": "KR7005930003",
                        "단축코드": "005930",
                        "한글 종목명": "삼성전자보통주",
                        "한글 종목약명": "삼성전자",
                        "시장구분": "KOSPI",
                    }
                ]
            ).to_csv(master, index=False, encoding="cp949")

            def fake_price_fetcher(code, days, env_dv):
                return pd.DataFrame([{"date": "20260512", "close": 100}])

            result = run_daily_signal_learning_collection(
                stock_codes_csv=tmp / "stock_codes.csv",
                master_csv=master,
                stock_limit=1,
                prices_csv=tmp / "prices.csv",
                reports_jsonl=tmp / "reports.jsonl",
                features_csv=tmp / "features.csv",
                as_of_date=date.today(),
                price_fetcher=fake_price_fetcher,
                outlook_service=FakeOutlookService(),
                run_workflow_if_ready=True,
                workflow_output_dir=tmp / "workflow",
            )

            self.assertEqual(result["workflow"]["stopped_at"], "input_readiness")
            self.assertFalse((tmp / "workflow" / "ml_dataset.csv").exists())


if __name__ == "__main__":
    unittest.main()
