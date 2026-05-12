"""Pandas-based financial metrics and deterministic financial signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from analysis.models import AnalysisError, Evidence, FinancialSignal

ACCOUNT_ALIASES = {
    "revenue": {"매출액", "수익(매출액)", "영업수익"},
    "operating_income": {"영업이익"},
    "net_income": {"당기순이익", "분기순이익", "반기순이익"},
    "liabilities": {"부채총계"},
    "equity": {"자본총계"},
}


@dataclass
class FinancialMetricResult:
    metrics: dict[str, float | None]
    signals: list[FinancialSignal] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    errors: list[AnalysisError] = field(default_factory=list)


def parse_amount(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return float(text)
    except ValueError:
        return None


def _latest_value(df: pd.DataFrame, names: set[str]) -> float | None:
    if df.empty or "account_nm" not in df or "thstrm_amount" not in df:
        return None

    matched = df[df["account_nm"].isin(names)].copy()
    if matched.empty:
        return None
    if "bsns_year" in matched:
        matched = matched.sort_values("bsns_year")

    return parse_amount(matched.iloc[-1]["thstrm_amount"])


def _previous_value(df: pd.DataFrame, names: set[str]) -> float | None:
    if df.empty or "account_nm" not in df or "thstrm_amount" not in df:
        return None

    matched = df[df["account_nm"].isin(names)].copy()
    if len(matched) < 2:
        return None
    if "bsns_year" in matched:
        matched = matched.sort_values("bsns_year")

    return parse_amount(matched.iloc[-2]["thstrm_amount"])


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round((numerator / denominator) * 100, 2)


def _latest_receipt_datetime(statements: pd.DataFrame) -> datetime | None:
    if statements.empty or "rcept_no" not in statements:
        return None
    dates = []
    for value in statements["rcept_no"].dropna():
        text = str(value)
        if len(text) < 8 or not text[:8].isdigit():
            continue
        try:
            dates.append(datetime.strptime(text[:8], "%Y%m%d").replace(tzinfo=timezone.utc))
        except ValueError:
            continue
    return max(dates) if dates else None


def calculate_financial_metrics(statements: pd.DataFrame) -> dict[str, float | None]:
    revenue = _latest_value(statements, ACCOUNT_ALIASES["revenue"])
    prev_revenue = _previous_value(statements, ACCOUNT_ALIASES["revenue"])
    operating_income = _latest_value(statements, ACCOUNT_ALIASES["operating_income"])
    net_income = _latest_value(statements, ACCOUNT_ALIASES["net_income"])
    liabilities = _latest_value(statements, ACCOUNT_ALIASES["liabilities"])
    equity = _latest_value(statements, ACCOUNT_ALIASES["equity"])

    return {
        "revenue": revenue,
        "operating_income": operating_income,
        "net_income": net_income,
        "operating_margin": _ratio(operating_income, revenue),
        "debt_ratio": _ratio(liabilities, equity),
        "roe": _ratio(net_income, equity),
        "revenue_growth": _ratio(
            None if revenue is None or prev_revenue is None else revenue - prev_revenue,
            prev_revenue,
        ),
    }


def _signal(
    label: str,
    metric: str,
    value: float | None,
    positive_at: float | None = None,
    negative_at: float | None = None,
    lower_is_positive: bool = False,
    score: int = 2,
) -> FinancialSignal:
    if value is None:
        return FinancialSignal(
            label=label,
            metric=metric,
            value=None,
            direction="neutral",
            score=0,
            reason="metric unavailable",
        )

    if lower_is_positive:
        if positive_at is not None and value <= positive_at:
            return FinancialSignal(label=label, metric=metric, value=value, direction="positive", score=score)
        if negative_at is not None and value >= negative_at:
            return FinancialSignal(label=label, metric=metric, value=value, direction="negative", score=-score)
    else:
        if positive_at is not None and value >= positive_at:
            return FinancialSignal(label=label, metric=metric, value=value, direction="positive", score=score)
        if negative_at is not None and value <= negative_at:
            return FinancialSignal(label=label, metric=metric, value=value, direction="negative", score=-score)

    return FinancialSignal(label=label, metric=metric, value=value, direction="neutral", score=0)


def build_financial_signals(metrics: dict[str, float | None]) -> list[FinancialSignal]:
    net_income = metrics.get("net_income")
    if net_income is None:
        net_income_signal = FinancialSignal(
            label="순이익",
            metric="net_income",
            value=None,
            direction="neutral",
            score=0,
            reason="metric unavailable",
        )
    elif net_income > 0:
        net_income_signal = FinancialSignal(
            label="순이익", metric="net_income", value=net_income, direction="positive", score=1
        )
    elif net_income < 0:
        net_income_signal = FinancialSignal(
            label="순이익", metric="net_income", value=net_income, direction="negative", score=-1
        )
    else:
        net_income_signal = FinancialSignal(
            label="순이익", metric="net_income", value=net_income, direction="neutral", score=0
        )

    return [
        _signal("매출 성장률", "revenue_growth", metrics.get("revenue_growth"), positive_at=5.0, negative_at=-5.0, score=1),
        _signal("영업이익률", "operating_margin", metrics.get("operating_margin"), positive_at=10.0, negative_at=3.0, score=2),
        _signal("부채비율", "debt_ratio", metrics.get("debt_ratio"), positive_at=100.0, negative_at=200.0, lower_is_positive=True, score=2),
        _signal("ROE", "roe", metrics.get("roe"), positive_at=10.0, negative_at=0.0, score=2),
        net_income_signal,
    ]


def analyze_financials(statements: pd.DataFrame) -> FinancialMetricResult:
    if statements.empty:
        return FinancialMetricResult(
            metrics={},
            errors=[
                AnalysisError(
                    source="financial_analysis",
                    code="empty_financial_data",
                    message="No financial statement rows are available",
                )
            ],
        )

    metrics = calculate_financial_metrics(statements)
    evidence = [
        Evidence(
            evidence_id="financial-statements",
            kind="financial",
            source="DART",
            title="DART single-account financial statements",
            published_at=_latest_receipt_datetime(statements),
            metadata={"rows": int(len(statements))},
        )
    ]
    signals = [
        signal.model_copy(update={"evidence_ids": ["financial-statements"]})
        for signal in build_financial_signals(metrics)
    ]

    return FinancialMetricResult(metrics=metrics, signals=signals, evidence=evidence)
