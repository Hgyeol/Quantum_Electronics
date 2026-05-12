"""Convert saved OutlookReport JSONL records into PRD feature rows.

Each input line must be one OutlookReport JSON object. Optional `as_of_date`
metadata can be included either as a top-level field or inside `metadata`; if
absent, the report generated_at date is used.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.models import OutlookReport
from ml.features import feature_row_from_report


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _as_of_date(payload_as_of_date: str | None, metadata: dict, report: OutlookReport) -> date:
    raw_value = payload_as_of_date or metadata.get("as_of_date")
    if raw_value:
        return date.fromisoformat(str(raw_value))
    return report.generated_at.date()


def _cutoff_datetime(value: date, cutoff_time: str | None, cutoff_timezone: str) -> datetime:
    if cutoff_time is None:
        return datetime.combine(value, time.max, tzinfo=timezone.utc)
    hour, minute = [int(part) for part in cutoff_time.split(":", maxsplit=1)]
    local_cutoff = datetime.combine(value, time(hour=hour, minute=minute), tzinfo=ZoneInfo(cutoff_timezone))
    return local_cutoff.astimezone(timezone.utc)


def _remove_future_evidence(
    report: OutlookReport,
    as_of_date: date,
    cutoff_time: str | None = "15:30",
    cutoff_timezone: str = "Asia/Seoul",
) -> OutlookReport:
    cutoff = _cutoff_datetime(as_of_date, cutoff_time, cutoff_timezone)
    evidence = []
    for item in report.evidence:
        if item.published_at is None:
            evidence.append(item)
            continue
        published_at = item.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        if published_at <= cutoff:
            evidence.append(item)
    return report.model_copy(update={"evidence": evidence})


def iter_report_feature_rows(
    path: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    drop_future_evidence: bool = True,
    cutoff_time: str | None = "15:30",
    cutoff_timezone: str = "Asia/Seoul",
):
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        as_of_date = payload.pop("as_of_date", None)
        metadata = payload.pop("metadata", {}) or {}
        report = OutlookReport.model_validate(payload)
        row_date = _as_of_date(as_of_date, metadata, report)
        if start_date and row_date < start_date:
            continue
        if end_date and row_date > end_date:
            continue
        if drop_future_evidence:
            report = _remove_future_evidence(report, row_date, cutoff_time, cutoff_timezone)
        yield feature_row_from_report(report, as_of_date=row_date)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build signal feature CSV from OutlookReport JSONL")
    parser.add_argument("--reports", required=True, help="Input JSONL path with one OutlookReport per line")
    parser.add_argument("--output", required=True, help="Output feature CSV")
    parser.add_argument("--start-date", help="Optional inclusive start date in YYYY-MM-DD")
    parser.add_argument("--end-date", help="Optional inclusive end date in YYYY-MM-DD")
    parser.add_argument(
        "--keep-future-evidence",
        action="store_true",
        help="Do not drop evidence published after the row as_of_date",
    )
    parser.add_argument(
        "--keep-after-market-close",
        action="store_true",
        help="Do not drop same-day evidence published after market close",
    )
    parser.add_argument("--market-close-time", default="15:30", help="Market close cutoff time, HH:MM")
    parser.add_argument("--market-timezone", default="Asia/Seoul", help="Timezone for market close cutoff")
    args = parser.parse_args()

    rows = list(
        iter_report_feature_rows(
            Path(args.reports),
            start_date=_parse_date(args.start_date),
            end_date=_parse_date(args.end_date),
            drop_future_evidence=not args.keep_future_evidence,
            cutoff_time=None if args.keep_after_market_close else args.market_close_time,
            cutoff_timezone=args.market_timezone,
        )
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).drop_duplicates(subset=["date", "stock_code"], keep="last").to_csv(output_path, index=False)
    print(f"wrote {len(rows)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
