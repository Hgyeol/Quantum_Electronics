import os
import unittest
from datetime import timezone
from unittest.mock import patch

import pandas as pd

from disclosure.financial_statement_single_account_api import fetch_all_reports_last_n_years
from financial.metrics import analyze_financials, calculate_financial_metrics, parse_amount


class FinancialAnalysisTests(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(parse_amount("1,234"), 1234.0)
        self.assertEqual(parse_amount("(1,234)"), -1234.0)
        self.assertIsNone(parse_amount("-"))

    def test_calculate_financial_metrics_from_mock_data(self):
        statements = pd.DataFrame(
            [
                {"bsns_year": "2024", "account_nm": "매출액", "thstrm_amount": "1,000"},
                {"bsns_year": "2025", "account_nm": "매출액", "thstrm_amount": "1,200"},
                {"bsns_year": "2025", "account_nm": "영업이익", "thstrm_amount": "180"},
                {"bsns_year": "2025", "account_nm": "당기순이익", "thstrm_amount": "120"},
                {"bsns_year": "2025", "account_nm": "부채총계", "thstrm_amount": "500"},
                {
                    "bsns_year": "2025",
                    "account_nm": "자본총계",
                    "thstrm_amount": "1,000",
                    "rcept_no": "20260401001234",
                },
            ]
        )

        metrics = calculate_financial_metrics(statements)

        self.assertEqual(metrics["revenue"], 1200.0)
        self.assertEqual(metrics["operating_income"], 180.0)
        self.assertEqual(metrics["net_income"], 120.0)
        self.assertEqual(metrics["operating_margin"], 15.0)
        self.assertEqual(metrics["debt_ratio"], 50.0)
        self.assertEqual(metrics["roe"], 12.0)
        self.assertEqual(metrics["revenue_growth"], 20.0)

    def test_analyze_financials_generates_deterministic_signals(self):
        statements = pd.DataFrame(
            [
                {"bsns_year": "2024", "account_nm": "매출액", "thstrm_amount": "1,000"},
                {"bsns_year": "2025", "account_nm": "매출액", "thstrm_amount": "1,200"},
                {"bsns_year": "2025", "account_nm": "영업이익", "thstrm_amount": "180"},
                {"bsns_year": "2025", "account_nm": "당기순이익", "thstrm_amount": "120"},
                {"bsns_year": "2025", "account_nm": "부채총계", "thstrm_amount": "500"},
                {
                    "bsns_year": "2025",
                    "account_nm": "자본총계",
                    "thstrm_amount": "1,000",
                    "rcept_no": "20260401001234",
                },
            ]
        )

        result = analyze_financials(statements)
        directions = {signal.metric: signal.direction for signal in result.signals}

        self.assertEqual(result.errors, [])
        self.assertEqual(directions["operating_margin"], "positive")
        self.assertEqual(directions["debt_ratio"], "positive")
        self.assertEqual(directions["roe"], "positive")
        self.assertEqual(result.evidence[0].evidence_id, "financial-statements")
        self.assertEqual(result.evidence[0].published_at.date().isoformat(), "2026-04-01")
        self.assertEqual(result.evidence[0].published_at.tzinfo, timezone.utc)

    def test_missing_dart_key_returns_error_result(self):
        with patch.dict(os.environ, {"DART_API_KEY": "", "DISCLOSURE_CRTFC_KEY": ""}, clear=False):
            result = fetch_all_reports_last_n_years("00126380", current_year=2026)

        self.assertTrue(result.dataframe.empty)
        self.assertEqual(result.errors[0].code, "missing_api_key")
        self.assertTrue(result.errors[0].recoverable)


if __name__ == "__main__":
    unittest.main()
