"""KIS stock news-title collection for Naver follow-up searches."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from analysis.models import AnalysisError

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_KIS_NEWS_TITLE_PATH = _PROJECT_ROOT / "tools" / "quatation" / "news-title.py"


@dataclass
class KISNewsTitle:
    title: str
    published_at: str | None = None
    provider: str | None = None
    serial: str | None = None


@dataclass
class KISNewsTitleResult:
    titles: list[KISNewsTitle] = field(default_factory=list)
    errors: list[AnalysisError] = field(default_factory=list)


def _load_kis_news_title_tool():
    spec = importlib.util.spec_from_file_location("kis_news_title_tool", _KIS_NEWS_TITLE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load KIS news title API from {_KIS_NEWS_TITLE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.news_title


def _format_kis_datetime(date_value: Any, time_value: Any) -> str | None:
    date_text = str(date_value or "").strip()
    time_text = str(time_value or "").strip().zfill(6)
    if not date_text:
        return None
    return f"{date_text}{time_text}"


def _row_contains_stock(row: pd.Series, stock_code: str) -> bool:
    return any(str(row.get(f"iscd{idx}", "")).strip() == stock_code for idx in range(1, 11))


def fetch_kis_news_titles(
    stock_code: str,
    stock_name: str,
    limit: int = 5,
    news_title_fn=None,
) -> KISNewsTitleResult:
    try:
        fetch_fn = news_title_fn or _load_kis_news_title_tool()
        df = fetch_fn(fid_input_iscd=stock_code)
    except Exception as exc:
        return KISNewsTitleResult(
            errors=[
                AnalysisError(
                    source="kis_news_title",
                    code="fetch_failed",
                    message=f"KIS news-title fetch failed: {exc}",
                )
            ]
        )

    if df is None or df.empty:
        return KISNewsTitleResult()

    rows = []
    for _, row in df.iterrows():
        if _row_contains_stock(row, stock_code):
            rows.append(row)
        if len(rows) >= limit:
            break

    titles = []
    for idx, row in enumerate(rows, start=1):
        title = str(row.get("hts_pbnt_titl_cntt", "")).strip()
        if not title:
            continue
        serial = str(row.get("cntt_usiq_srno", "")).strip() or str(idx)
        titles.append(
            KISNewsTitle(
                title=title,
                published_at=_format_kis_datetime(row.get("data_dt"), row.get("data_tm")),
                provider=str(row.get("dorg", "")).strip() or None,
                serial=serial,
            )
        )

    return KISNewsTitleResult(titles=titles)
