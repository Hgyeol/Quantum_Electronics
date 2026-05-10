import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from analysis.evidence import normalize_evidence
from analysis.models import Evidence
from disclosure.disclosure_api import search_disclosures
from news.naver_news_api import search_naver_news
from news.news_crawler import fetch_article_text


class MockResponse:
    def __init__(self, status_code=200, payload=None, text="", content=b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.content = content or text.encode("utf-8")

    def json(self):
        return self._payload


class MockSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class EvidenceCollectionTests(unittest.TestCase):
    def test_normalize_evidence_deduplicates_and_filters_dates(self):
        old = Evidence(
            evidence_id="news-1",
            kind="news",
            source="Naver",
            title="old",
            published_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            url="https://example.com/old",
        )
        duplicate = Evidence(
            evidence_id="news-2",
            kind="news",
            source="Naver",
            title="duplicate",
            published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            url="https://example.com/item",
        )
        duplicate_same_url = duplicate.model_copy(update={"evidence_id": "news-3"})

        result = normalize_evidence(
            [old, duplicate, duplicate_same_url],
            start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual([item.evidence_id for item in result], ["news-2"])

    def test_naver_news_mock_response_to_evidence(self):
        session = MockSession(
            MockResponse(
                payload={
                    "items": [
                        {
                            "title": "<b>삼성전자</b> 실적 개선",
                            "description": "영업이익 증가",
                            "link": "https://news.example.com/a",
                            "originallink": "https://origin.example.com/a",
                            "pubDate": "Mon, 04 May 2026 09:00:00 +0900",
                        },
                        {
                            "title": "삼성전자 실적 개선",
                            "description": "중복",
                            "link": "https://news.example.com/a",
                            "pubDate": "Mon, 04 May 2026 09:00:00 +0900",
                        },
                    ]
                }
            )
        )

        result = search_naver_news(
            "삼성전자",
            client_id="id",
            client_secret="secret",
            session=session,
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0].title, "삼성전자 실적 개선")
        self.assertEqual(result.evidence[0].kind, "news")

    def test_naver_missing_credentials_returns_error_without_request(self):
        session = MockSession(MockResponse())
        with patch.dict(os.environ, {"NAVER_CLIENT_ID": "", "NAVER_CLIENT_SECRET": ""}, clear=False):
            result = search_naver_news("삼성전자", session=session)

        self.assertEqual(result.evidence, [])
        self.assertEqual(result.errors[0].code, "missing_credentials")
        self.assertEqual(session.calls, [])

    def test_disclosure_mock_response_to_evidence(self):
        session = MockSession(
            MockResponse(
                payload={
                    "status": "000",
                    "list": [
                        {
                            "corp_name": "삼성전자",
                            "stock_code": "005930",
                            "rcept_no": "20260501000123",
                            "report_nm": "분기보고서",
                            "rcept_dt": "20260501",
                        }
                    ],
                }
            )
        )

        result = search_disclosures(
            corp_code="00126380",
            bgn_de="20260501",
            end_de="20260510",
            api_key="dart-key",
            session=session,
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.evidence[0].evidence_id, "disclosure-20260501000123")
        self.assertEqual(result.evidence[0].kind, "disclosure")
        self.assertEqual(result.evidence[0].metadata["stock_code"], "005930")

    def test_news_crawler_extracts_article_text(self):
        html = "<html><body><article id='dic_area'>첫 문장<br/>둘째 문장</article></body></html>"
        result = fetch_article_text("https://news.example.com/a", session=MockSession(MockResponse(text=html)))

        self.assertEqual(result.error, None)
        self.assertIn("첫 문장", result.text)
        self.assertIn("둘째 문장", result.text)


if __name__ == "__main__":
    unittest.main()
