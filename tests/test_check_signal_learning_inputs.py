import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.check_signal_learning_inputs import check_signal_learning_inputs


def _sample_features():
    return pd.DataFrame(
        [
            {
                "date": "2026-05-10",
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quant_score": 2,
                "ai_score": 1,
                "financial_score": 0,
                "total_rule_score": 3,
                "golden_cross_score": 2,
                "disparity_score": 0,
                "momentum_score": 1,
                "foreign_investor_score": 0,
                "volume_score": 0,
                "llm_direction": "positive",
                "llm_score": 1,
                "llm_confidence": 0.7,
                "financial_revenue_growth_score": 0,
                "financial_margin_score": 0,
                "financial_debt_score": 0,
                "news_count": 3,
                "disclosure_count": 1,
                "financial_evidence_count": 1,
            }
        ]
    )


class CheckSignalLearningInputsTests(unittest.TestCase):
    def test_check_reports_missing_next_price(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features = tmp / "features.csv"
            prices = tmp / "prices.csv"
            sample = _sample_features()
            sample.iloc[[0]].to_csv(features, index=False)
            pd.DataFrame(
                [
                    {"date": "2026-05-10", "stock_code": "005930", "close": 100},
                ]
            ).to_csv(prices, index=False)

            result = check_signal_learning_inputs(features, prices)

            self.assertFalse(result["ok"])
            self.assertEqual(result["prd_progress"]["feature_calendar_days"], 1)
            self.assertEqual(result["prd_progress"]["remaining_calendar_days"], 89)
            self.assertEqual(result["prd_progress"]["target_calendar_end_date"], "2026-08-07")
            self.assertEqual(result["labeling"]["labelable_feature_rows"], 0)
            self.assertEqual(result["labeling"]["missing_next_price_count"], 1)

    def test_check_accepts_labelable_inputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features = tmp / "features.csv"
            prices = tmp / "prices.csv"
            sample = _sample_features()
            sample.iloc[[0]].to_csv(features, index=False)
            pd.DataFrame(
                [
                    {"date": "2026-05-10", "stock_code": "005930", "close": 100},
                    {"date": "2026-05-11", "stock_code": "005930", "close": 101},
                ]
            ).to_csv(prices, index=False)

            result = check_signal_learning_inputs(features, prices, min_calendar_days=1, min_stocks=1)

            self.assertTrue(result["ok"])
            self.assertEqual(result["prd_progress"]["remaining_calendar_days"], 0)
            self.assertEqual(result["prd_progress"]["remaining_stocks"], 0)
            self.assertEqual(result["labeling"]["labelable_feature_rows"], 1)
            self.assertEqual(result["labeling"]["labeled_dataset_rows"], 1)

    def test_check_parses_compact_yyyymmdd_price_dates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features = tmp / "features.csv"
            prices = tmp / "prices.csv"
            sample = _sample_features()
            sample.iloc[[0]].to_csv(features, index=False)
            pd.DataFrame(
                [
                    {"date": 20260510, "stock_code": "005930", "close": 100},
                    {"date": 20260511, "stock_code": "005930", "close": 101},
                ]
            ).to_csv(prices, index=False)

            result = check_signal_learning_inputs(features, prices)

            self.assertEqual(result["prices"]["start_date"], "2026-05-10")
            self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
