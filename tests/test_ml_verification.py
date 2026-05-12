import unittest

import pandas as pd

from ml.dataset import FEATURE_COLUMNS, LABEL_COLUMNS
from ml.verification import verify_labeled_dataset


def _row(date, stock_code, target_up=1):
    row = {column: 0 for column in FEATURE_COLUMNS + LABEL_COLUMNS}
    row.update(
        {
            "date": date,
            "stock_code": stock_code,
            "stock_name": stock_code,
            "close": 100,
            "next_close": 101 if target_up else 99,
            "next_day_return": 0.01 if target_up else -0.01,
            "target_up": target_up,
            "llm_direction": "neutral",
        }
    )
    return row


class MLVerificationTests(unittest.TestCase):
    def test_verifier_accepts_prd_ready_dataset_shape(self):
        rows = []
        dates = pd.date_range("2026-01-01", periods=91, freq="D")
        stocks = ["005930", "000660", "005380", "373220", "035420"]
        for idx, date in enumerate(dates):
            for stock in stocks:
                rows.append(_row(date.date().isoformat(), stock, target_up=idx % 2))

        result = verify_labeled_dataset(pd.DataFrame(rows))

        self.assertTrue(result.ok)
        self.assertEqual(result.stock_count, 5)
        self.assertEqual(result.date_count, 91)
        self.assertEqual(result.issues, [])

    def test_verifier_rejects_small_or_duplicate_dataset(self):
        dataset = pd.DataFrame(
            [
                _row("2026-01-01", "005930", target_up=1),
                _row("2026-01-01", "005930", target_up=1),
            ]
        )

        result = verify_labeled_dataset(dataset)
        codes = {issue.code for issue in result.issues}

        self.assertFalse(result.ok)
        self.assertIn("duplicate_rows", codes)
        self.assertIn("too_few_stocks", codes)
        self.assertIn("insufficient_history", codes)
        self.assertIn("single_class_target", codes)


if __name__ == "__main__":
    unittest.main()
