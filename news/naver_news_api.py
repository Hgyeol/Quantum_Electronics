"""Naver News search helpers that return normalized Evidence objects."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from datetime import datetime
from typing import Any

import requests

from analysis.evidence import normalize_evidence
from analysis.models import AnalysisError, Evidence

NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class NewsSearchResult:
    evidence: list[Evidence] = field(default_factory=list)
    errors: list[AnalysisError] = field(default_factory=list)


def _clean_html(value: str | None) -> str:
    if not value:
        return ""
    return _TAG_RE.sub("", value).replace("&quot;", '"').replace("&amp;", "&").strip()


def _parse_pub_date(value: str | None):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def get_naver_credentials(
    client_id: str | None = None,
    client_secret: str | None = None,
) -> tuple[str | None, str | None]:
    return (
        client_id or os.getenv("NAVER_NEWS_API_CLIENT") or os.getenv("NAVER_CLIENT_ID"),
        client_secret or os.getenv("NAVER_NEWS_API_SECRET") or os.getenv("NAVER_CLIENT_SECRET"),
    )


def search_naver_news(
    query: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    display: int = 10,
    sort: str = "date",
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    session: Any = requests,
    timeout: float = 10.0,
) -> NewsSearchResult:
    naver_id, naver_secret = get_naver_credentials(client_id, client_secret)
    if not naver_id or not naver_secret:
        return NewsSearchResult(
            errors=[
                AnalysisError(
                    source="naver_news",
                    code="missing_credentials",
                    message="Naver news API credentials are not configured",
                )
            ]
        )

    response = session.get(
        NAVER_NEWS_URL,
        headers={
            "X-Naver-Client-Id": naver_id,
            "X-Naver-Client-Secret": naver_secret,
        },
        params={"query": query, "display": display, "sort": sort},
        timeout=timeout,
    )
    if response.status_code != 200:
        return NewsSearchResult(
            errors=[
                AnalysisError(
                    source="naver_news",
                    code="http_error",
                    message=f"Naver news API returned HTTP {response.status_code}",
                )
            ]
        )

    items = response.json().get("items", [])
    evidence = [
        Evidence(
            evidence_id=f"news-{idx + 1}",
            kind="news",
            source="Naver News",
            title=_clean_html(item.get("title")) or "Untitled news",
            published_at=_parse_pub_date(item.get("pubDate")),
            url=item.get("link") or item.get("originallink"),
            content=_clean_html(item.get("description")) or None,
            metadata={
                "originallink": item.get("originallink"),
                "query": query,
            },
        )
        for idx, item in enumerate(items)
    ]

    return NewsSearchResult(
        evidence=normalize_evidence(evidence, start_date=start_date, end_date=end_date)
    )


def build_stock_news_query(stock_name: str) -> str:
    return stock_name
