import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from services.technical_indicators import calculate_indicators, list_indicator_definitions
from web.main import app


def _price_frame(rows: int = 80) -> pd.DataFrame:
    values = list(range(1000, 1000 + rows))
    return pd.DataFrame(
        {
            "date": [f"202605{(idx % 28) + 1:02d}" for idx in range(rows)],
            "open": values,
            "high": [value + 10 for value in values],
            "low": [value - 10 for value in values],
            "close": values,
            "volume": [100_000 + idx for idx in range(rows)],
        }
    )


class TechnicalIndicatorTests(unittest.TestCase):
    def test_catalog_includes_strategy_builder_indicators(self):
        definitions = list_indicator_definitions()
        ids = {definition.id for definition in definitions}

        self.assertGreaterEqual(len(definitions), 80)
        for indicator_id in ["rsi", "macd", "bb_upper", "supertrend", "beta", "alpha"]:
            self.assertIn(indicator_id, ids)

    def test_calculates_selected_indicators_with_defaults(self):
        with patch("services.technical_indicators.data_fetcher.get_daily_prices", return_value=_price_frame()):
            result = calculate_indicators("005930", indicator_ids=["ma", "rsi", "beta"], days=80)

        self.assertEqual(result.errors, [])
        by_id = {item.id: item for item in result.indicators}
        self.assertEqual(set(by_id), {"ma", "rsi", "beta"})
        self.assertIsNotNone(by_id["ma"].value)
        self.assertEqual(by_id["ma"].parameters["period"], 20)
        self.assertTrue(by_id["beta"].uses_default_benchmark)

    def test_frontend_and_indicator_api_routes(self):
        client = TestClient(app)

        front = client.get("/")
        catalog = client.get("/technical/indicators")

        self.assertEqual(front.status_code, 200)
        self.assertIn("기술 지표 조회", front.text)
        self.assertEqual(catalog.status_code, 200)
        self.assertIn("indicators", catalog.json())

        with patch("services.technical_indicators.data_fetcher.get_daily_prices", return_value=_price_frame()):
            calculated = client.get("/technical/indicators/005930", params={"ids": "ma,rsi", "days": 80})

        self.assertEqual(calculated.status_code, 200)
        payload = calculated.json()
        self.assertEqual(payload["stock_code"], "005930")
        self.assertEqual([item["id"] for item in payload["indicators"]], ["ma", "rsi"])


if __name__ == "__main__":
    unittest.main()
