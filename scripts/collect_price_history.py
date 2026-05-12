"""Collect KIS daily close prices for ML labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "strategy"))


def read_codes(codes: list[str], codes_file: str | None = None) -> list[str]:
    collected = list(codes)
    if codes_file:
        for raw_line in Path(codes_file).read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                code = line.split(",")[0].strip()
                if code.lower() != "stock_code":
                    collected.append(code)

    deduped = []
    seen = set()
    for code in collected:
        if code not in seen:
            deduped.append(code)
            seen.add(code)
    return deduped


def collect_price_history(
    codes: list[str],
    output_csv: str | Path,
    days: int = 120,
    env_dv: str = "real",
    price_fetcher=None,
) -> dict[str, int]:
    fetcher = price_fetcher
    if fetcher is None:
        from core import data_fetcher

        fetcher = data_fetcher.get_daily_prices

    rows = []
    for code in codes:
        df = fetcher(code, days=days, env_dv=env_dv)
        if df is None or df.empty:
            continue
        price_rows = df[["date", "close"]].copy()
        price_rows["stock_code"] = code
        rows.append(price_rows[["date", "stock_code", "close"]])

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    new_rows = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "stock_code", "close"])
    if output_path.exists():
        existing = pd.read_csv(output_path, dtype={"stock_code": str})
        merged = pd.concat([existing, new_rows], ignore_index=True)
    else:
        merged = new_rows
    merged["date"] = merged["date"].astype(str)
    merged["stock_code"] = merged["stock_code"].astype(str).str.zfill(6)
    merged = merged.drop_duplicates(subset=["date", "stock_code"], keep="last")
    merged = merged.sort_values(["date", "stock_code"])
    merged.to_csv(output_path, index=False)
    return {"stocks_requested": len(codes), "rows_written": len(merged)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect daily close prices for ML labels")
    parser.add_argument("codes", nargs="*", help="Stock codes, e.g. 005930 000660")
    parser.add_argument("--codes-file", help="Optional newline or CSV file whose first column is stock_code")
    parser.add_argument("--output", required=True, help="Output price CSV path")
    parser.add_argument("--days", type=int, default=120, help="Number of daily bars to request per stock")
    parser.add_argument("--env-dv", default="real", choices=["real", "demo"], help="KIS env_dv")
    parser.add_argument("--kis-auth", action="store_true", help="Authenticate KIS before collection")
    parser.add_argument("--force-kis-token", action="store_true", help="Delete cached KIS token before auth")
    parser.add_argument("--kis-server", default="prod", choices=["prod", "vps"], help="KIS server for --kis-auth")
    args = parser.parse_args()

    if args.kis_auth:
        import kis_auth

        if args.force_kis_token:
            Path(kis_auth.get_token_path()).unlink(missing_ok=True)
        kis_auth.auth(svr=args.kis_server)

    codes = read_codes(args.codes, args.codes_file)
    if not codes:
        parser.error("At least one stock code is required")
    result = collect_price_history(codes, args.output, days=args.days, env_dv=args.env_dv)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
