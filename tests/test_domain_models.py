import unittest

from pydantic import ValidationError

from analysis.models import AISignal, Evidence, FinancialSignal, OutlookReport
from analysis.scoring import combine_signals, direction_from_score
from ml.prediction import MLPrediction
from quant.models import QuantSignal


class DomainModelTests(unittest.TestCase):
    def test_direction_score_validation(self):
        with self.assertRaises(ValidationError):
            AISignal(label="bad", direction="positive", score=0, summary="invalid")

        with self.assertRaises(ValidationError):
            FinancialSignal(label="bad", metric="roe", direction="neutral", score=1)

        signal = AISignal(
            label="news sentiment",
            direction="negative",
            score=-2,
            summary="negative evidence",
            evidence_ids=["news-1"],
            confidence=0.8,
        )

        self.assertEqual(signal.direction, "negative")
        self.assertEqual(signal.score, -2)

    def test_direction_from_score(self):
        self.assertEqual(direction_from_score(3), "positive")
        self.assertEqual(direction_from_score(-1), "negative")
        self.assertEqual(direction_from_score(0), "neutral")

    def test_combine_signal_scores(self):
        quant = [
            QuantSignal(
                label="momentum",
                direction="positive",
                score=1,
                value=0.31,
                api_used="mock",
            )
        ]
        ai = [
            AISignal(
                label="disclosure interpretation",
                direction="negative",
                score=-2,
                summary="risk factor",
                evidence_ids=["disc-1"],
            )
        ]
        financial = [
            FinancialSignal(
                label="roe",
                metric="roe",
                direction="positive",
                score=3,
                value=18.2,
                period="2025",
            )
        ]

        score = combine_signals(quant, ai, financial)

        self.assertEqual(score.quant_score, 1)
        self.assertEqual(score.ai_score, -2)
        self.assertEqual(score.financial_score, 3)
        self.assertEqual(score.total_score, 2)
        self.assertEqual(score.direction, "positive")

    def test_outlook_report_accepts_partial_errors_and_evidence(self):
        score = combine_signals()
        report = OutlookReport(
            stock_code="005930",
            stock_name="Samsung Electronics",
            score=score,
            evidence=[
                Evidence(
                    evidence_id="news-1",
                    kind="news",
                    source="mock",
                    title="sample",
                )
            ],
            errors=[
                {
                    "source": "naver",
                    "code": "missing_credentials",
                    "message": "Naver credentials are not configured",
                }
            ],
        )

        self.assertEqual(report.stock_code, "005930")
        self.assertEqual(report.score.direction, "neutral")
        self.assertTrue(report.errors[0].recoverable)

    def test_outlook_report_accepts_ml_prediction(self):
        report = OutlookReport(
            stock_code="005930",
            score=combine_signals(),
            ml_prediction=MLPrediction(
                probability=0.57,
                model="logistic_regression_v1",
                features_version="v1",
            ),
        )

        self.assertEqual(report.ml_prediction.target, "next_day_up")
        self.assertEqual(report.ml_prediction.probability, 0.57)


if __name__ == "__main__":
    unittest.main()
