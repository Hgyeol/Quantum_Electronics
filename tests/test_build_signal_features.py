import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from analysis.models import AISignal, Evidence, FinancialSignal, OutlookReport
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
                        published_at=datetime(2026, 5, 11, 5, 0, tzinfo=timezone.utc),
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

    def test_iter_report_feature_rows_carries_after_market_close_to_next_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_path = Path(tmpdir) / "reports.jsonl"
            report = OutlookReport(
                stock_code="005930",
                stock_name="삼성전자",
                score=combine_signals(
                    ai_signals=[
                        AISignal(
                            direction="positive",
                            score=2,
                            label="after close news",
                            summary="장마감 이후 호재",
                            evidence_ids=["news-2"],
                            confidence=0.8,
                        )
                    ],
                    financial_signals=[
                        FinancialSignal(
                            direction="negative",
                            score=-1,
                            label="after close financial",
                            metric="revenue_growth",
                            evidence_ids=["fin-1"],
                        )
                    ],
                ),
                ai_signals=[
                    AISignal(
                        direction="positive",
                        score=2,
                        label="after close news",
                        summary="장마감 이후 호재",
                        evidence_ids=["news-2"],
                        confidence=0.8,
                    )
                ],
                financial_signals=[
                    FinancialSignal(
                        direction="negative",
                        score=-1,
                        label="after close financial",
                        metric="revenue_growth",
                        evidence_ids=["fin-1"],
                    )
                ],
                evidence=[
                    Evidence(
                        evidence_id="news-1",
                        kind="news",
                        source="mock",
                        title="before close",
                        published_at=datetime(2026, 5, 11, 6, 29, tzinfo=timezone.utc),
                    ),
                    Evidence(
                        evidence_id="news-2",
                        kind="news",
                        source="mock",
                        title="after close",
                        published_at=datetime(2026, 5, 11, 6, 31, tzinfo=timezone.utc),
                    ),
                    Evidence(
                        evidence_id="fin-1",
                        kind="financial",
                        source="mock",
                        title="after close financial",
                        published_at=datetime(2026, 5, 11, 6, 31, tzinfo=timezone.utc),
                    ),
                ],
            ).model_dump(mode="json")
            report["as_of_date"] = "2026-05-11"
            next_report = OutlookReport(
                stock_code="005930",
                stock_name="삼성전자",
                score=combine_signals(),
            ).model_dump(mode="json")
            next_report["as_of_date"] = "2026-05-12"
            reports_path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in [report, next_report]),
                encoding="utf-8",
            )

            rows = list(iter_report_feature_rows(reports_path))

            self.assertEqual(rows[0]["news_count"], 1)
            self.assertEqual(rows[0]["financial_evidence_count"], 0)
            self.assertEqual(rows[0]["ai_score"], 0)
            self.assertEqual(rows[0]["financial_score"], 0)
            self.assertEqual(rows[0]["total_rule_score"], 0)
            self.assertEqual(rows[1]["news_count"], 1)
            self.assertEqual(rows[1]["financial_evidence_count"], 1)
            self.assertEqual(rows[1]["ai_score"], 2)
            self.assertEqual(rows[1]["financial_score"], -1)
            self.assertEqual(rows[1]["total_rule_score"], 1)


if __name__ == "__main__":
    unittest.main()
