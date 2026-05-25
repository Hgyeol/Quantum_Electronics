import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from analysis.models import AISignal, Evidence, OutlookReport
from analysis.scoring import combine_signals
from llm.analyzer import LLMAnalysisResult
from ml.prediction import MLFeatureContribution, MLPrediction
from quant.models import QuantSignal
from services.outlook import OutlookService, lookup_dart_stock_mapping, lookup_stock_master
from web.main import app, get_outlook_service


class FakeOutlookService:
    def build_report(
        self,
        stock_code,
        stock_name=None,
        *,
        avg_price=None,
        quantity=None,
        held_since=None,
    ):
        quant_signals = [
            QuantSignal(
                label="mock momentum",
                direction="positive",
                score=1,
                value=1.0,
                api_used="mock",
            )
        ]
        return OutlookReport(
            stock_code=stock_code,
            stock_name=stock_name,
            summary="mock report",
            score=combine_signals(quant_signals=quant_signals),
            quant_signals=quant_signals,
            ai_signals=[],
            financial_signals=[],
            evidence=[],
            errors=[],
        )


class FastAPIServiceTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_outlook_service] = lambda: FakeOutlookService()
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_health(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_stock_outlook_accepts_stock_code_path_variable(self):
        response = self.client.get("/outlook/stock/005930")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["stock_code"], "005930")
        self.assertIsNone(payload["stock_name"])
        self.assertEqual(payload["score"]["direction"], "positive")
        self.assertEqual(payload["quant_signals"][0]["api_used"], "mock")

    def test_query_outlook_route_is_removed(self):
        response = self.client.post("/outlook/query", json={"query": "000660"})

        self.assertEqual(response.status_code, 404)

    def test_market_route_is_removed(self):
        response = self.client.get("/outlook/market")

        self.assertEqual(response.status_code, 404)

    def test_stock_outlook_serializes_ml_prediction(self):
        class FakePredictor:
            def predict_report(self, report):
                return MLPrediction(
                    probability=0.57,
                    model="logistic_regression_v1",
                    features_version="v1",
                    rule_score=report.score.total_score,
                    rule_direction=report.score.direction,
                    explanation="mock explanation",
                    top_contributions=[
                        MLFeatureContribution(
                            feature="quant_score",
                            value=1.0,
                            contribution=0.2,
                            direction="positive",
                        )
                    ],
                )

        class QuietQuantEngine:
            def get_signals(self, stock_code, stock_name):
                return [
                    QuantSignal(
                        label="mock momentum",
                        direction="positive",
                        score=1,
                        value=1.0,
                        api_used="mock",
                    )
                ]

        app.dependency_overrides[get_outlook_service] = lambda: OutlookService(
            quant_engine=QuietQuantEngine(),
            ml_predictor=FakePredictor(),
        )

        response = self.client.get("/outlook/stock/005930")

        self.assertEqual(response.status_code, 200)
        prediction = response.json()["ml_prediction"]
        self.assertEqual(prediction["target"], "next_day_up")
        self.assertEqual(prediction["probability"], 0.57)
        self.assertEqual(prediction["model"], "logistic_regression_v1")
        self.assertEqual(prediction["features_version"], "v1")
        self.assertEqual(prediction["rule_score"], 1)
        self.assertEqual(prediction["top_contributions"][0]["feature"], "quant_score")

    def test_lookup_dart_stock_mapping_by_exact_name(self):
        stock = lookup_dart_stock_mapping("삼성전자")

        self.assertIsNotNone(stock)
        self.assertEqual(stock["stock_code"], "005930")
        self.assertEqual(stock["corp_code"], "00126380")

    def test_lookup_stock_master_by_exact_name(self):
        stock = lookup_stock_master("삼성전자")

        self.assertIsNotNone(stock)
        self.assertEqual(stock["stock_code"], "005930")
        self.assertEqual(stock["corp_name"], "삼성전자")

    def test_position_query_params_attach_position_context(self):
        class QuietQuantEngine:
            def get_signals(self, stock_code, stock_name):
                return [
                    QuantSignal(
                        label="mock momentum",
                        direction="positive",
                        score=1,
                        value=1.0,
                        api_used="mock",
                    )
                ]

        app.dependency_overrides[get_outlook_service] = lambda: OutlookService(
            quant_engine=QuietQuantEngine(),
            price_quote_fn=lambda code: {"price": 13200, "w52_high": 16000, "w52_low": 9500},
        )

        response = self.client.get(
            "/outlook/stock/005930",
            params={"avg_price": 12660, "quantity": 2200, "held_since": "2024-03-15"},
        )

        self.assertEqual(response.status_code, 200)
        ctx = response.json()["position_context"]
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["avg_price"], 12660)
        self.assertEqual(ctx["quantity"], 2200)
        self.assertEqual(ctx["current_price"], 13200)
        self.assertEqual(ctx["unrealized_pnl_amount"], 1188000.0)
        self.assertEqual(ctx["breakeven_required_pct"], 0)
        self.assertIn("권유가 아님", ctx["disclaimer"])

    def test_future_held_since_returns_422(self):
        response = self.client.get(
            "/outlook/stock/005930",
            params={"avg_price": 1000, "quantity": 1, "held_since": "2099-01-01"},
        )
        self.assertEqual(response.status_code, 422)

    def test_outlook_service_skips_non_kospi_query_before_llm(self):
        class ExplodingQuantEngine:
            def get_signals(self, stock_code, stock_name):
                raise AssertionError("quant should not run for non-KOSPI queries")

        service = OutlookService(quant_engine=ExplodingQuantEngine())
        report = service.build_report("애플")

        self.assertEqual(report.score.direction, "neutral")
        self.assertEqual(report.ai_signals, [])
        self.assertEqual(report.evidence, [])
        self.assertEqual(report.errors[0].code, "not_listed_or_not_found")

    def test_llm_evidence_excludes_quant_and_market_data(self):
        class QuietQuantEngine:
            def get_signals(self, stock_code, stock_name):
                return [
                    QuantSignal(
                        label="거래량 급증 (20일 평균 대비)",
                        direction="positive",
                        score=1,
                        value=2.3,
                        api_used="mock",
                    )
                ]

        class CapturingLLM:
            def __init__(self):
                self.evidence = None

            def analyze_evidence(self, evidence):
                self.evidence = list(evidence)
                return LLMAnalysisResult(
                    signals=[
                        AISignal(
                            label="뉴스·공시",
                            direction="positive",
                            score=1,
                            summary="뉴스에 명시된 신사업 기대가 부각됐다.",
                            evidence_ids=["news-1"],
                            confidence=0.8,
                        )
                    ]
                )

        llm = CapturingLLM()
        service = OutlookService(
            quant_engine=QuietQuantEngine(),
            price_quote_fn=lambda code: {
                "price": 13200,
                "change": 1200,
                "change_rate": 10.0,
                "w52_high": 13200,
                "w52_low": 9500,
            },
        )
        service.llm_analyzer = llm

        news_evidence = Evidence(
            evidence_id="news-1",
            kind="news",
            source="Naver News",
            title="로봇 신사업 기대",
            content="휴머노이드 로봇용 액츄에이터 양산체제 구축 계획이 언급됐다.",
        )

        with patch("services.outlook.fetch_kis_news_titles", return_value=SimpleNamespace(titles=[], errors=[])), \
            patch("services.outlook.search_naver_news_by_titles", return_value=SimpleNamespace(evidence=[], errors=[])), \
            patch("services.outlook.search_naver_news", return_value=SimpleNamespace(evidence=[news_evidence], errors=[])), \
            patch("services.outlook.lookup_corp_code", return_value=None):
            report = service.build_report("005930")

        self.assertEqual([item.kind for item in llm.evidence], ["news"])
        self.assertNotIn("market", [item.kind for item in report.evidence])
        self.assertNotIn("quant", [item.kind for item in report.evidence])
        self.assertIsNotNone(report.market_quote)
        self.assertEqual(report.quant_signals[0].label, "거래량 급증 (20일 평균 대비)")


if __name__ == "__main__":
    unittest.main()
