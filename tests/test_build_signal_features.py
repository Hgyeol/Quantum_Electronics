import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from analysis.models import Evidence, OutlookReport
from analysis.scoring import combine_signals
from scripts.build_signal_features import iter_report_feature_rows


class BuildSignalFeaturesTests(unittest.TestCase):
    def test_iter_report_feature_rows_filters_date_range_and_future_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_path = Path(tmpdir) / "reports.jsonl"
            old_report = OutlookReport(
                stock_code="005930",
                stock_name="삼성전자",
                score=combine_signals(),
            ).model_dump(mode="json")
            old_report["as_of_date"] = "2026-05-10"

            report = OutlookReport(
                stock_code="000660",
                stock_name="SK하이닉스",
                score=combine_signals(),
                evidence=[
                    Evidence(
                        evidence_id="news-1",
                        kind="news",
                        source="mock",
                        title="known on date",
                        published_at=datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc),
                    ),
                    Evidence(
                        evidence_id="news-2",
                        kind="news",
                        source="mock",
                        title="future item",
                        published_at=datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc),
                    ),
                ],
            ).model_dump(mode="json")
            report["as_of_date"] = "2026-05-11"
            reports_path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in [old_report, report]),
                encoding="utf-8",
            )

            rows = list(
                iter_report_feature_rows(
                    reports_path,
                    start_date=datetime(2026, 5, 11).date(),
                    end_date=datetime(2026, 5, 11).date(),
                )
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["stock_code"], "000660")
            self.assertEqual(rows[0]["date"], "2026-05-11")
            self.assertEqual(rows[0]["news_count"], 1)


if __name__ == "__main__":
    unittest.main()
