"""News article text extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup

from analysis.models import AnalysisError


@dataclass
class ArticleTextResult:
    text: str | None = None
    error: AnalysisError | None = None


def fetch_article_text(
    url: str,
    session: Any = requests,
    timeout: float = 10.0,
) -> ArticleTextResult:
    try:
        response = session.get(url, timeout=timeout)
    except Exception as exc:
        return ArticleTextResult(
            error=AnalysisError(source="news_crawler", code="request_failed", message=str(exc))
        )

    if response.status_code != 200:
        return ArticleTextResult(
            error=AnalysisError(
                source="news_crawler",
                code="http_error",
                message=f"Article request returned HTTP {response.status_code}",
            )
        )

    soup = BeautifulSoup(response.text, "html.parser")
    article = soup.find("article", id="dic_area") or soup.find("article")
    if article is None:
        return ArticleTextResult(
            error=AnalysisError(
                source="news_crawler",
                code="article_not_found",
                message="No article body was found in the HTML document",
            )
        )

    text = article.get_text(separator="\n", strip=True)
    return ArticleTextResult(text=text or None)
