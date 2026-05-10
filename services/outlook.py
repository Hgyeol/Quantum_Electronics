"""Orchestration for investment outlook reports."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from analysis.models import AnalysisError, OutlookReport
from analysis.scoring import combine_signals
from disclosure.disclosure_api import search_disclosures
from disclosure.financial_statement_single_account_api import fetch_all_reports_last_n_years
from financial.metrics import analyze_financials
from llm.analyzer import DisabledLLMAnalyzer, OpenAIResponsesAnalyzer
from news.naver_news_api import search_naver_news
from quant.engine import QuantEngine
from quant.models import QuantSignal

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
        normalized_code = stock_code.strip()
        display_name = stock_name or normalized_code
        errors: list[AnalysisError] = []

        quant_signals = self._get_quant_signals(normalized_code, display_name, errors)
        evidence = []

        news_result = search_naver_news(display_name)
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
            evidence.extend(disclosure_result.evidence)
            errors.extend(disclosure_result.errors)

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


def lookup_corp_code(stock_code: str, csv_path: Path = _KOSPI_CSV) -> str | None:
    if not csv_path.exists():
        return None

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("stock_code") == stock_code:
                return row.get("corp_code") or None
    return None
