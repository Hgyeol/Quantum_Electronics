"""Convert saved OutlookReport JSONL records into PRD feature rows.

Each input line must be one OutlookReport JSON object. Optional `as_of_date`
metadata can be included either as a top-level field or inside `metadata`; if
absent, the report generated_at date is used.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.models import OutlookReport
from ml.features import feature_row_from_report


def _iter_report_rows(path: Path):
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        as_of_date = payload.pop("as_of_date", None)
        metadata = payload.pop("metadata", {}) or {}
        report = OutlookReport.model_validate(payload)
        yield feature_row_from_report(report, as_of_date=as_of_date or metadata.get("as_of_date"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build signal feature CSV from OutlookReport JSONL")
    parser.add_argument("--reports", required=True, help="Input JSONL path with one OutlookReport per line")
    parser.add_argument("--output", required=True, help="Output feature CSV")
    args = parser.parse_args()

    rows = list(_iter_report_rows(Path(args.reports)))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)
    print(f"wrote {len(rows)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
