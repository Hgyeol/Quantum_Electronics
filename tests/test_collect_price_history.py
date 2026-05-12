import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.collect_price_history import collect_price_history, read_codes


class CollectPriceHistoryTests(unittest.TestCase):
    def test_read_codes_dedupes_args_and_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "codes.csv"
            path.write_text("stock_code,stock_name,market\n005930,삼성전자,KOSPI\n000660,SK하이닉스,KOSPI\n", encoding="utf-8")

            codes = read_codes(["005930"], str(path))

        self.assertEqual(codes, ["005930", "000660"])

    def test_collect_price_history_merges_and_dedupes_rows(self):
        def fake_fetcher(code, days, env_dv):
            return pd.DataFrame(
                [
                    {"date": "20260510", "close": 100},
                    {"date": "20260511", "close": 101},
                ]
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "prices.csv"
            output.write_text("date,stock_code,close\n20260510,005930,99\n", encoding="utf-8")

            result = collect_price_history(
                ["005930"],
                output,
                days=2,
                env_dv="real",
                price_fetcher=fake_fetcher,
            )

            prices = pd.read_csv(output, dtype={"stock_code": str})

        self.assertEqual(result["stocks_requested"], 1)
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices.loc[prices["date"] == 20260510, "close"].iloc[0], 100)


if __name__ == "__main__":
    unittest.main()
