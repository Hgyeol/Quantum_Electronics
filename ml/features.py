"""Feature extraction from OutlookReport objects."""

from __future__ import annotations

from datetime import date
from typing import Any

from analysis.models import OutlookReport

QUANT_LABEL_FEATURES = {
    "골든크로스": "golden_cross_score",
    "이격도": "disparity_score",
    "모멘텀": "momentum_score",
    "외인 순매수": "foreign_investor_score",
    "거래량 급증": "volume_score",
}
FINANCIAL_METRIC_FEATURES = {
    "revenue_growth": "financial_revenue_growth_score",
    "operating_margin": "financial_margin_score",
    "debt_ratio": "financial_debt_score",
}


def _find_quant_score(report: OutlookReport, label_part: str) -> int:
    for signal in report.quant_signals:
        if label_part in signal.label:
            return signal.score
    return 0


def _find_financial_score(report: OutlookReport, metric: str) -> int:
    for signal in report.financial_signals:
        if signal.metric == metric:
            return signal.score
    return 0


def _primary_llm_direction(report: OutlookReport) -> str:
    if not report.ai_signals:
        return "neutral"
    return report.ai_signals[0].direction


def _primary_llm_score(report: OutlookReport) -> int:
    if not report.ai_signals:
        return 0
    return report.ai_signals[0].score


def _primary_llm_confidence(report: OutlookReport) -> float:
    if not report.ai_signals:
        return 0.0
    return report.ai_signals[0].confidence


def feature_row_from_report(report: OutlookReport, as_of_date: date | str | None = None) -> dict[str, Any]:
    """Convert a report into the PRD feature-row schema."""
    row_date = as_of_date or report.generated_at.date()
    row = {
        "date": str(row_date),
        "stock_code": report.stock_code,
        "stock_name": report.stock_name,
        "quant_score": report.score.quant_score,
        "ai_score": report.score.ai_score,
        "financial_score": report.score.financial_score,
        "total_rule_score": report.score.total_score,
        "llm_direction": _primary_llm_direction(report),
        "llm_score": _primary_llm_score(report),
        "llm_confidence": _primary_llm_confidence(report),
        "news_count": sum(1 for item in report.evidence if item.kind == "news"),
        "disclosure_count": sum(1 for item in report.evidence if item.kind == "disclosure"),
        "financial_evidence_count": sum(1 for item in report.evidence if item.kind == "financial"),
    }
    for label_part, column in QUANT_LABEL_FEATURES.items():
        row[column] = _find_quant_score(report, label_part)
    for metric, column in FINANCIAL_METRIC_FEATURES.items():
        row[column] = _find_financial_score(report, metric)
    return row


def historical_feature_row(
    stock_code: str,
    as_of_date: date,
    report_provider,
) -> dict[str, Any]:
    """Build one historical feature row through an as_of_date-aware provider.

    The provider owns data availability rules so future information can be
    excluded at collection time.
    """
    report = report_provider(stock_code=stock_code, as_of_date=as_of_date)
    return feature_row_from_report(report, as_of_date=as_of_date)
