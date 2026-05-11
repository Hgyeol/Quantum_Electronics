"""Orchestration for investment outlook reports."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from analysis.models import AnalysisError, OutlookReport
from analysis.scoring import combine_signals
from disclosure.disclosure_api import enrich_disclosure_texts, search_disclosures
from disclosure.financial_statement_single_account_api import fetch_all_reports_last_n_years
from financial.metrics import analyze_financials
from llm.analyzer import DisabledLLMAnalyzer, OpenAIResponsesAnalyzer
from news.naver_news_api import build_stock_news_query, search_naver_news
from quant.engine import QuantEngine
from quant.models import QuantSignal

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_STOCK_MASTER_CSV = _PROJECT_ROOT / "kospi.csv"
_KOSPI_CSV = _PROJECT_ROOT / "disclosure" / "kospi.csv"


class OutlookQuery(BaseModel):
    query: str = Field(min_length=1)
    stock_name: str | None = None


class OutlookService:
    def __init__(self, quant_engine: QuantEngine | None = None):
        self.quant_engine = quant_engine or QuantEngine()
        self.llm_analyzer = (
            OpenAIResponsesAnalyzer()
            if os.getenv("OPENAI_API_KEY")
            else DisabledLLMAnalyzer()
        )

    def build_report(self, stock_code: str, stock_name: str | None = None) -> OutlookReport:
        stock = lookup_stock_master(stock_code) or lookup_dart_stock_mapping(stock_code)
        normalized_code = stock["stock_code"] if stock else stock_code.strip()
        display_name = stock_name or (stock["corp_name"] if stock else normalized_code)
        errors: list[AnalysisError] = []

        quant_signals = self._get_quant_signals(normalized_code, display_name, errors)
        evidence = []

        news_end = datetime.now(timezone.utc)
        news_start = news_end - timedelta(days=7)
        news_result = search_naver_news(
            build_stock_news_query(display_name),
            start_date=news_start,
            end_date=news_end,
        )
        evidence.extend(news_result.evidence)
        errors.extend(news_result.errors)

        corp_code = lookup_corp_code(normalized_code)
        financial_signals = []
        if corp_code:
            end = datetime.now()
            start = end - timedelta(days=45)
            disclosure_result = search_disclosures(
                corp_code=corp_code,
                bgn_de=start.strftime("%Y%m%d"),
                end_de=end.strftime("%Y%m%d"),
            )
            enriched_disclosures = enrich_disclosure_texts(disclosure_result.evidence)
            evidence.extend(enriched_disclosures.evidence)
            errors.extend(disclosure_result.errors)
            errors.extend(enriched_disclosures.errors)

            financial_result = fetch_all_reports_last_n_years(corp_code)
            errors.extend(financial_result.errors)
            if not financial_result.dataframe.empty:
                analyzed_financials = analyze_financials(financial_result.dataframe)
                financial_signals = analyzed_financials.signals
                evidence.extend(analyzed_financials.evidence)
                errors.extend(analyzed_financials.errors)
        else:
            errors.append(
                AnalysisError(
                    source="corp_code",
                    code="not_found",
                    message=f"No DART corp_code mapping found for stock code {normalized_code}",
                )
            )

        llm_result = self.llm_analyzer.analyze_evidence(evidence)
        errors.extend(llm_result.errors)

        score = combine_signals(
            quant_signals=quant_signals,
            ai_signals=llm_result.signals,
            financial_signals=financial_signals,
        )

        return OutlookReport(
            stock_code=normalized_code,
            stock_name=stock_name,
            summary=f"{display_name} outlook is {score.direction} with total score {score.total_score}.",
            score=score,
            quant_signals=quant_signals,
            ai_signals=llm_result.signals,
            financial_signals=financial_signals,
            evidence=evidence,
            errors=errors,
        )

    def _get_quant_signals(
        self,
        stock_code: str,
        stock_name: str,
        errors: list[AnalysisError],
    ) -> list[QuantSignal]:
        try:
            return self.quant_engine.get_signals(stock_code, stock_name)
        except Exception as exc:
            errors.append(
                AnalysisError(source="quant", code="failed", message=f"Quant analysis failed: {exc}")
            )
            return []


def _read_csv_rows(csv_path: Path, encodings: tuple[str, ...] = ("utf-8-sig", "cp949", "euc-kr")):
    for encoding in encodings:
        try:
            with csv_path.open(encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    return []


def lookup_corp_code(stock_code: str, csv_path: Path = _KOSPI_CSV) -> str | None:
    stock = lookup_dart_stock_mapping(stock_code, csv_path=csv_path)
    return stock["corp_code"] if stock else None


def lookup_stock_master(query: str, csv_path: Path = _STOCK_MASTER_CSV) -> dict[str, str] | None:
    """Lookup stock code/name from the local KOSPI stock master CSV."""
    if not csv_path.exists():
        return None

    normalized_query = query.strip()
    for row in _read_csv_rows(csv_path):
        stock_code = (row.get("단축코드") or "").strip()
        full_name = (row.get("한글 종목명") or "").strip()
        short_name = (row.get("한글 종목약명") or "").strip()
        if normalized_query in (stock_code, full_name, short_name):
            return {
                "stock_code": stock_code,
                "corp_name": short_name or full_name,
                "market": (row.get("시장구분") or "").strip(),
            }
    return None


def lookup_dart_stock_mapping(query: str, csv_path: Path = _KOSPI_CSV) -> dict[str, str] | None:
    """Best-effort lookup from the local DART corp-code CSV.

    This is not a complete stock master. The current CSV is used for DART
    financial/disclosure corp_code mapping and may not cover every listed stock.
    """
    if not csv_path.exists():
        return None

    normalized_query = query.strip()
    for row in _read_csv_rows(csv_path):
        stock_code = (row.get("stock_code") or "").strip()
        corp_name = (row.get("corp_name") or "").strip()
        if normalized_query in (stock_code, corp_name):
            return {
                "corp_code": (row.get("corp_code") or "").strip(),
                "corp_name": corp_name,
                "stock_code": stock_code,
            }
    return None
