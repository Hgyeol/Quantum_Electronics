"""Export a stock-code universe file from the local KOSPI/KOSDAQ master CSVs."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Sequence
from pathlib import Path

DEFAULT_MASTER_CSVS: tuple[str, ...] = ("kospi.csv", "kosdaq.csv")


def _read_master_rows(
    csv_path: Path,
    encodings: tuple[str, ...] = ("utf-8-sig", "cp949", "euc-kr"),
) -> list[dict[str, str]]:
    for encoding in encodings:
        try:
            with csv_path.open(encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"Unable to decode {csv_path}")


def export_stock_universe(
    master_csv: str | Path | Sequence[str | Path],
    output_csv: str | Path,
    limit: int | None = None,
) -> int:
    if isinstance(master_csv, (str, Path)):
        master_paths = [Path(master_csv)]
    else:
        master_paths = [Path(p) for p in master_csv]

    exported: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in master_paths:
        for row in _read_master_rows(path):
            code = (row.get("단축코드") or "").strip()
            full_name = (row.get("한글 종목명") or "").strip()
            short_name = (row.get("한글 종목약명") or "").strip()
            market = (row.get("시장구분") or "").strip()
            if not code or code in seen:
                continue
            exported.append(
                {
                    "stock_code": code,
                    "stock_name": short_name or full_name,
                    "market": market,
                }
            )
            seen.add(code)
            if limit is not None and len(exported) >= limit:
                break
        if limit is not None and len(exported) >= limit:
            break

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["stock_code", "stock_name", "market"])
        writer.writeheader()
        writer.writerows(exported)
    return len(exported)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export stock universe CSV from KOSPI/KOSDAQ master CSVs"
    )
    parser.add_argument(
        "--master-csv",
        action="append",
        default=None,
        help=(
            "Master CSV path. Repeat to merge multiple files. "
            f"Defaults to {list(DEFAULT_MASTER_CSVS)} when omitted."
        ),
    )
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--limit", type=int, help="Optional max number of stocks to export")
    args = parser.parse_args()

    master_csvs = args.master_csv if args.master_csv else list(DEFAULT_MASTER_CSVS)
    count = export_stock_universe(master_csvs, args.output, args.limit)
    print(f"wrote {count} stocks to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
