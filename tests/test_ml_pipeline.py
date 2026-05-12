import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis.models import AISignal, Evidence, FinancialSignal, OutlookReport
from analysis.scoring import combine_signals
from ml.backtest import evaluate_backtest_suite
from ml.dataset import attach_next_day_labels, build_labeled_dataset, prepare_model_features
from ml.evaluation import evaluate_baselines, split_by_time, success_gate
from ml.features import feature_row_from_report
from ml.runtime import OutlookMLPredictor
from ml.training import load_logistic_regression, train_logistic_regression
from quant.models import QuantSignal


class MLPipelineTests(unittest.TestCase):
    def _sample_features(self):
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
                },
                {
                    "date": "2026-05-11",
                    "stock_code": "005930",
                    "stock_name": "삼성전자",
                    "quant_score": -1,
                    "ai_score": 0,
                    "financial_score": 0,
                    "total_rule_score": -1,
                    "golden_cross_score": 0,
                    "disparity_score": -2,
                    "momentum_score": 1,
                    "foreign_investor_score": 0,
                    "volume_score": 0,
                    "llm_direction": "neutral",
                    "llm_score": 0,
                    "llm_confidence": 0.4,
                    "financial_revenue_growth_score": 0,
                    "financial_margin_score": 0,
                    "financial_debt_score": 0,
                    "news_count": 1,
                    "disclosure_count": 0,
                    "financial_evidence_count": 1,
                },
            ]
        )

    def test_attach_next_day_labels_uses_next_trading_close_by_stock(self):
        prices = pd.DataFrame(
            [
                {"date": "2026-05-10", "stock_code": "005930", "close": 100},
                {"date": "2026-05-11", "stock_code": "005930", "close": 105},
                {"date": "2026-05-12", "stock_code": "005930", "close": 102},
            ]
        )

        dataset = attach_next_day_labels(self._sample_features(), prices)

        self.assertEqual(len(dataset), 2)
        self.assertEqual(dataset.iloc[0]["target_up"], 1)
        self.assertAlmostEqual(dataset.iloc[0]["next_day_return"], 0.05)
        self.assertEqual(dataset.iloc[1]["target_up"], 0)

    def test_duplicate_feature_rows_are_rejected(self):
        features = pd.concat([self._sample_features().iloc[[0]], self._sample_features().iloc[[0]]])
        prices = pd.DataFrame([{"date": "2026-05-10", "stock_code": "005930", "close": 100}])

        with self.assertRaises(ValueError):
            attach_next_day_labels(features, prices)

    def test_build_labeled_dataset_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            features_path = tmp / "features.csv"
            prices_path = tmp / "prices.csv"
            output_path = tmp / "ml_dataset.csv"
            self._sample_features().to_csv(features_path, index=False)
            pd.DataFrame(
                [
                    {"date": "2026-05-10", "stock_code": "005930", "close": 100},
                    {"date": "2026-05-11", "stock_code": "005930", "close": 105},
                    {"date": "2026-05-12", "stock_code": "005930", "close": 102},
                ]
            ).to_csv(prices_path, index=False)

            dataset = build_labeled_dataset(features_path, prices_path, output_path)

            self.assertTrue(output_path.exists())
            self.assertEqual(len(dataset), 2)

    def test_split_by_time_and_baselines(self):
        dataset = pd.DataFrame(
            [
                {"date": f"2026-05-{day:02d}", "stock_code": "005930", "target_up": day % 2, "next_day_return": 0.01 if day % 2 else -0.01, "total_rule_score": day - 5, "quant_score": 1, "ai_score": 0}
                for day in range(1, 11)
            ]
        )

        train, validation, test = split_by_time(dataset, train_ratio=0.6, validation_ratio=0.2)
        baselines = evaluate_baselines(test)

        self.assertEqual(len(train), 6)
        self.assertEqual(len(validation), 2)
        self.assertEqual(len(test), 2)
        self.assertIn("total_rule_score_gt_0", baselines)
        self.assertIn("mean_return_when_pred_up", baselines["always_up"])
        self.assertIn("roc_auc", baselines["always_up"])
        self.assertIn("selected_stock_count", baselines["always_up"])

    def test_split_by_time_keeps_same_date_in_one_partition(self):
        dataset = pd.DataFrame(
            [
                {
                    "date": f"2026-05-{day:02d}",
                    "stock_code": stock_code,
                    "target_up": day % 2,
                    "next_day_return": 0.01,
                    "total_rule_score": 1,
                    "quant_score": 1,
                    "ai_score": 0,
                }
                for day in range(1, 7)
                for stock_code in ["005930", "000660"]
            ]
        )

        train, validation, test = split_by_time(dataset, train_ratio=0.5, validation_ratio=0.25)
        train_dates = set(train["date"])
        validation_dates = set(validation["date"])
        test_dates = set(test["date"])

        self.assertFalse(train_dates & validation_dates)
        self.assertFalse(train_dates & test_dates)
        self.assertFalse(validation_dates & test_dates)

    def test_success_gate_requires_baseline_improvement_and_trades(self):
        baseline_metrics = {
            "total_rule_score_gt_0": {
                "precision": 0.5,
                "mean_return_when_pred_up": 0.01,
            }
        }
        model_metrics = {
            "precision": 0.5,
            "mean_return_when_pred_up": 0.02,
            "trade_count": 3,
            "selected_stock_count": 1,
        }

        result = success_gate(
            model_metrics,
            baseline_metrics,
            min_trade_count=3,
            min_selected_stock_count=1,
        )

        self.assertTrue(result["passes"])
        self.assertTrue(result["improves_mean_return"])
        self.assertTrue(result["enough_stock_coverage"])

    def test_success_gate_rejects_single_stock_model_by_default(self):
        baseline_metrics = {
            "total_rule_score_gt_0": {
                "precision": 0.5,
                "mean_return_when_pred_up": 0.01,
            }
        }
        model_metrics = {
            "precision": 0.6,
            "mean_return_when_pred_up": 0.02,
            "trade_count": 10,
            "selected_stock_count": 1,
        }

        result = success_gate(model_metrics, baseline_metrics)

        self.assertFalse(result["passes"])
        self.assertFalse(result["enough_stock_coverage"])

    def test_train_logistic_regression_saves_and_loads_model(self):
        dataset = pd.DataFrame(
            [
                {**self._sample_features().iloc[0].to_dict(), "target_up": 1, "next_day_return": 0.02},
                {**self._sample_features().iloc[1].to_dict(), "target_up": 0, "next_day_return": -0.01},
                {**self._sample_features().iloc[0].to_dict(), "date": "2026-05-12", "target_up": 1, "next_day_return": 0.03},
                {**self._sample_features().iloc[1].to_dict(), "date": "2026-05-13", "target_up": 0, "next_day_return": -0.02},
            ]
        )

        model = train_logistic_regression(dataset, epochs=20)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            model.save(path)
            loaded = load_logistic_regression(path)

        probabilities = loaded.predict_proba(dataset)

        self.assertEqual(loaded.model_name, "logistic_regression_v1")
        self.assertEqual(loaded.features_version, "v1")
        self.assertEqual(len(probabilities), len(dataset))
        self.assertTrue(((probabilities >= 0) & (probabilities <= 1)).all())

    def test_evaluate_backtest_suite_includes_baselines_and_model(self):
        dataset = pd.DataFrame(
            [
                {**self._sample_features().iloc[0].to_dict(), "target_up": 1, "next_day_return": 0.02},
                {**self._sample_features().iloc[1].to_dict(), "target_up": 0, "next_day_return": -0.01},
                {**self._sample_features().iloc[0].to_dict(), "date": "2026-05-12", "target_up": 1, "next_day_return": 0.03},
                {**self._sample_features().iloc[1].to_dict(), "date": "2026-05-13", "target_up": 0, "next_day_return": -0.02},
            ]
        )
        model = train_logistic_regression(dataset, epochs=20)

        result = evaluate_backtest_suite(dataset, model)

        self.assertIn("total_rule_score_gt_0", result["validation"])
        self.assertIn("model", result["test"])
        self.assertIn("cumulative_return", result["test"]["model"])

    def test_feature_row_from_report_matches_prd_columns(self):
        quant = [
            QuantSignal(label="골든크로스 (MA5/MA20)", direction="positive", score=2, value=1.0, api_used="mock"),
            QuantSignal(label="이격도 (MA20 대비 현재가 %)", direction="negative", score=-2, value=120.0, api_used="mock"),
        ]
        ai = [AISignal(label="뉴스", direction="positive", score=1, summary="호재", confidence=0.8)]
        financial = [
            FinancialSignal(label="매출 성장률", metric="revenue_growth", direction="negative", score=-1),
            FinancialSignal(label="부채비율", metric="debt_ratio", direction="positive", score=2),
        ]
        report = OutlookReport(
            stock_code="005930",
            stock_name="삼성전자",
            score=combine_signals(quant, ai, financial),
            quant_signals=quant,
            ai_signals=ai,
            financial_signals=financial,
            evidence=[
                Evidence(evidence_id="news-1", kind="news", source="mock", title="뉴스"),
                Evidence(evidence_id="disc-1", kind="disclosure", source="mock", title="공시"),
                Evidence(evidence_id="fin-1", kind="financial", source="mock", title="재무"),
            ],
        )

        row = feature_row_from_report(report, as_of_date="2026-05-11")
        model_features = prepare_model_features(pd.DataFrame([row]))

        self.assertEqual(row["date"], "2026-05-11")
        self.assertEqual(row["golden_cross_score"], 2)
        self.assertEqual(row["disparity_score"], -2)
        self.assertEqual(row["financial_revenue_growth_score"], -1)
        self.assertEqual(row["financial_debt_score"], 2)
        self.assertEqual(row["news_count"], 1)
        self.assertEqual(float(model_features.iloc[0]["llm_direction"]), 1.0)

    def test_runtime_predictor_returns_ml_prediction(self):
        dataset = pd.DataFrame(
            [
                {**self._sample_features().iloc[0].to_dict(), "target_up": 1, "next_day_return": 0.02},
                {**self._sample_features().iloc[1].to_dict(), "target_up": 0, "next_day_return": -0.01},
                {**self._sample_features().iloc[0].to_dict(), "date": "2026-05-12", "target_up": 1, "next_day_return": 0.03},
                {**self._sample_features().iloc[1].to_dict(), "date": "2026-05-13", "target_up": 0, "next_day_return": -0.02},
            ]
        )
        model = train_logistic_regression(dataset, epochs=20)
        predictor = OutlookMLPredictor(model)
        report = OutlookReport(
            stock_code="005930",
            stock_name="삼성전자",
            score=combine_signals(),
        )

        prediction = predictor.predict_report(report)

        self.assertEqual(prediction.target, "next_day_up")
        self.assertGreaterEqual(prediction.probability, 0.0)
        self.assertLessEqual(prediction.probability, 1.0)
        self.assertEqual(prediction.rule_score, report.score.total_score)
        self.assertIsNotNone(prediction.explanation)
        self.assertTrue(prediction.top_contributions)

    def test_outlook_report_jsonl_can_be_converted_to_feature_rows(self):
        report = OutlookReport(
            stock_code="005930",
            stock_name="삼성전자",
            score=combine_signals(),
        )
        row = feature_row_from_report(report, as_of_date="2026-05-11")

        self.assertEqual(row["date"], "2026-05-11")
        self.assertEqual(row["stock_code"], "005930")
        self.assertEqual(row["total_rule_score"], 0)


if __name__ == "__main__":
    unittest.main()
