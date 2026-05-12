"""Collect daily OutlookReport records and feature rows for stock codes.

This is the accumulation entry point for the PRD's historical feature dataset.
Run it once per trading day for the target stock universe, then build labels
later with `scripts/build_ml_dataset.py` once price data is available.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.features import feature_row_from_report
from services.outlook import OutlookService


def _read_codes(args) -> list[str]:
    codes: list[str] = []
    if args.codes:
        codes.extend(args.codes)
    if args.codes_file:
        for raw_line in Path(args.codes_file).read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                codes.append(line.split(",")[0].strip())
    deduped = []
    seen = set()
    for code in codes:
        if code not in seen:
            deduped.append(code)
            seen.add(code)
    return deduped


def _append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _merge_feature_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_rows = pd.DataFrame(rows)
    if path.exists():
        existing = pd.read_csv(path, dtype={"stock_code": str})
        merged = pd.concat([existing, new_rows], ignore_index=True)
    else:
        merged = new_rows
    merged = merged.drop_duplicates(subset=["date", "stock_code"], keep="last")
    merged = merged.sort_values(["date", "stock_code"])
    merged.to_csv(path, index=False)


def collect_signal_features(
    codes: list[str],
    as_of_date: date,
    reports_jsonl: str | Path,
    features_csv: str | Path,
    service: OutlookService | None = None,
    allow_date_override: bool = False,
) -> dict[str, int]:
    if as_of_date != date.today() and not allow_date_override:
        raise ValueError(
            "collect_signal_features uses current live data, so as_of_date must be today. "
            "Use allow_date_override only when replaying already time-correct reports."
        )

    outlook_service = service or OutlookService()
    report_records = []
    feature_rows = []
    for code in codes:
        report = outlook_service.build_report(code)
        payload = report.model_dump(mode="json")
        payload["as_of_date"] = as_of_date.isoformat()
        report_records.append(payload)
        feature_rows.append(feature_row_from_report(report, as_of_date=as_of_date))

    _append_jsonl(Path(reports_jsonl), report_records)
    _merge_feature_csv(Path(features_csv), feature_rows)
    return {"reports": len(report_records), "features": len(feature_rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect daily signal features for stock codes")
    parser.add_argument("codes", nargs="*", help="Stock codes, e.g. 005930 000660")
    parser.add_argument("--codes-file", help="Optional newline or CSV file whose first column is stock_code")
    parser.add_argument("--as-of-date", default=date.today().isoformat(), help="Feature date in YYYY-MM-DD")
    parser.add_argument(
        "--allow-date-override",
        action="store_true",
        help="Allow non-today as_of_date only for controlled replays of time-correct data",
    )
    parser.add_argument("--reports-jsonl", required=True, help="Append-only OutlookReport JSONL path")
    parser.add_argument("--features-csv", required=True, help="Deduplicated feature CSV path")
    args = parser.parse_args()

    codes = _read_codes(args)
    if not codes:
        parser.error("At least one stock code is required")
    result = collect_signal_features(
        codes=codes,
        as_of_date=date.fromisoformat(args.as_of_date),
        reports_jsonl=args.reports_jsonl,
        features_csv=args.features_csv,
        allow_date_override=args.allow_date_override,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
