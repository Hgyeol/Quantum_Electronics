"""kospi_category.csv + kosdaq_category.csv → screener DB stocks.sector 컬럼 갱신."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from services.screener_db import init_db, upsert_sectors  # noqa: E402


def main() -> None:
    init_db()

    rows: list[dict] = []
    for fname in ("kospi_category.csv", "kosdaq_category.csv"):
        path = ROOT / fname
        if not path.exists():
            print(f"[skip] {fname} not found")
            continue
        df = pd.read_csv(path, encoding="euc-kr", dtype=str)
        df.columns = df.columns.str.strip()
        for _, row in df.iterrows():
            code = str(row["종목코드"]).strip().zfill(6)
            sector = str(row["업종명"]).strip()
            rows.append({"stock_code": code, "sector": sector})

    upsert_sectors(rows)
    print(f"[done] {len(rows)}개 종목 업종 저장 완료")


if __name__ == "__main__":
    main()
