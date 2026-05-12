import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ml.dataset import FEATURE_COLUMNS
from scripts.run_signal_learning_workflow import run_signal_learning_workflow


class SignalLearningWorkflowTests(unittest.TestCase):
    def test_workflow_writes_dataset_metrics_and_model_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_path = tmp / "features.csv"
            prices_path = tmp / "prices.csv"
            output_dir = tmp / "workflow"

            feature_rows = []
            price_rows = []
            stock_codes = ["005930", "000660", "005380", "035420", "051910"]
            for stock_index, stock_code in enumerate(stock_codes):
                close = 100.0 + stock_index
                for day_index in range(12):
                    date_value = f"2026-05-{day_index + 1:02d}"
                    price_rows.append(
                        {
                            "date": date_value,
                            "stock_code": stock_code,
                            "close": close,
                        }
                    )
                    direction = 1 if (day_index + stock_index) % 2 == 0 else -1
                    row = {
                        "date": date_value,
                        "stock_code": stock_code,
                        "stock_name": f"종목{stock_index}",
                        "quant_score": direction,
                        "ai_score": 0,
                        "financial_score": 0,
                        "total_rule_score": direction,
                        "golden_cross_score": direction,
                        "disparity_score": 0,
                        "momentum_score": direction,
                        "foreign_investor_score": 0,
                        "volume_score": 0,
                        "llm_direction": "positive" if direction > 0 else "negative",
                        "llm_score": direction,
                        "llm_confidence": 0.6,
                        "financial_revenue_growth_score": 0,
                        "financial_margin_score": 0,
                        "financial_debt_score": 0,
                        "news_count": 2,
                        "disclosure_count": 1,
                        "financial_evidence_count": 1,
                    }
                    feature_rows.append(row)
                    close = close * (1.01 if direction > 0 else 0.99)
                price_rows.append(
                    {
                        "date": "2026-05-13",
                        "stock_code": stock_code,
                        "close": close,
                    }
                )

            pd.DataFrame(feature_rows, columns=FEATURE_COLUMNS).to_csv(features_path, index=False)
            pd.DataFrame(price_rows).to_csv(prices_path, index=False)

            summary = run_signal_learning_workflow(
                features_csv=features_path,
                prices_csv=prices_path,
                output_dir=output_dir,
                min_calendar_days=1,
                min_stocks=5,
                epochs=10,
                min_trade_count=1,
                min_selected_stock_count=1,
            )

            self.assertTrue(summary["verification_ok"])
            self.assertEqual(summary["input_readiness"]["prd_progress"]["min_calendar_days"], 1)
            self.assertEqual(summary["input_readiness"]["prd_progress"]["remaining_calendar_days"], 0)
            self.assertTrue((output_dir / "ml_dataset.csv").exists())
            self.assertTrue((output_dir / "verification.json").exists())
            self.assertTrue((output_dir / "baseline_metrics.json").exists())
            self.assertTrue((output_dir / "backtest_metrics.json").exists())
            self.assertTrue((output_dir / "outlook_logistic_v1.json").exists())
            self.assertTrue((output_dir / "outlook_logistic_v1.metrics.json").exists())
            self.assertTrue((output_dir / "workflow_summary.json").exists())

    def test_workflow_stops_before_empty_dataset_when_inputs_have_no_next_price(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_path = tmp / "features.csv"
            prices_path = tmp / "prices.csv"
            output_dir = tmp / "workflow"
            row = {
                "date": "2026-05-12",
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quant_score": 1,
                "ai_score": 0,
                "financial_score": 0,
                "total_rule_score": 1,
                "golden_cross_score": 1,
                "disparity_score": 0,
                "momentum_score": 1,
                "foreign_investor_score": 0,
                "volume_score": 0,
                "llm_direction": "positive",
                "llm_score": 1,
                "llm_confidence": 0.6,
                "financial_revenue_growth_score": 0,
                "financial_margin_score": 0,
                "financial_debt_score": 0,
                "news_count": 1,
                "disclosure_count": 0,
                "financial_evidence_count": 1,
            }
            pd.DataFrame([row], columns=FEATURE_COLUMNS).to_csv(features_path, index=False)
            pd.DataFrame(
                [{"date": "2026-05-12", "stock_code": "005930", "close": 100}]
            ).to_csv(prices_path, index=False)
            output_dir.mkdir()
            for stale_name in [
                "ml_dataset.csv",
                "verification.json",
                "baseline_metrics.json",
                "backtest_metrics.json",
                "outlook_logistic_v1.json",
                "outlook_logistic_v1.metrics.json",
            ]:
                (output_dir / stale_name).write_text("stale", encoding="utf-8")

            summary = run_signal_learning_workflow(
                features_csv=features_path,
                prices_csv=prices_path,
                output_dir=output_dir,
            )

            self.assertEqual(summary["stopped_at"], "input_readiness")
            self.assertFalse((output_dir / "ml_dataset.csv").exists())
            self.assertFalse((output_dir / "verification.json").exists())
            self.assertFalse((output_dir / "baseline_metrics.json").exists())
            self.assertFalse((output_dir / "backtest_metrics.json").exists())
            self.assertFalse((output_dir / "outlook_logistic_v1.json").exists())
            self.assertFalse((output_dir / "outlook_logistic_v1.metrics.json").exists())
            self.assertTrue((output_dir / "workflow_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
