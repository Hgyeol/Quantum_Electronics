import unittest

from fastapi.testclient import TestClient

from analysis.models import OutlookReport
from analysis.scoring import combine_signals
from quant.models import QuantSignal
from web.main import app, get_outlook_service


class FakeOutlookService:
    def build_report(self, stock_code, stock_name=None):
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

    def test_stock_outlook(self):
        response = self.client.get("/outlook/stock/005930", params={"stock_name": "삼성전자"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["stock_code"], "005930")
        self.assertEqual(payload["stock_name"], "삼성전자")
        self.assertEqual(payload["score"]["direction"], "positive")
        self.assertEqual(payload["quant_signals"][0]["api_used"], "mock")

    def test_query_outlook(self):
        response = self.client.post(
            "/outlook/query",
            json={"query": "000660", "stock_name": "SK하이닉스"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stock_code"], "000660")

    def test_market_skeleton(self):
        response = self.client.get("/outlook/market")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "partial")


if __name__ == "__main__":
    unittest.main()
