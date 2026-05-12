import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.export_stock_universe import export_stock_universe


class ExportStockUniverseTests(unittest.TestCase):
    def test_export_stock_universe_uses_root_kospi_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            master = tmp / "kospi.csv"
            output = tmp / "stock_codes.csv"
            pd.DataFrame(
                [
                    {
                        "표준코드": "KR7005930003",
                        "단축코드": "005930",
                        "한글 종목명": "삼성전자보통주",
                        "한글 종목약명": "삼성전자",
                        "시장구분": "KOSPI",
                    },
                    {
                        "표준코드": "KR7000660001",
                        "단축코드": "000660",
                        "한글 종목명": "SK하이닉스보통주",
                        "한글 종목약명": "SK하이닉스",
                        "시장구분": "KOSPI",
                    },
                ]
            ).to_csv(master, index=False, encoding="cp949")

            count = export_stock_universe(master, output, limit=1)
            exported = pd.read_csv(output, dtype={"stock_code": str})

            self.assertEqual(count, 1)
            self.assertEqual(exported.iloc[0]["stock_code"], "005930")
            self.assertEqual(exported.iloc[0]["stock_name"], "삼성전자")


if __name__ == "__main__":
    unittest.main()
