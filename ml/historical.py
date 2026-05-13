"""Historical OutlookReport assembly for PRD Phase 2 backfill.

Live `services.outlook.OutlookService` anchors every call at `datetime.now()`,
which is fine for daily collection but cannot produce reports for past dates.
This module reconstructs an `OutlookReport` for an arbitrary `as_of_date` by
pre-fetching per-stock data once and slicing it per date.

News evidence is intentionally skipped: the Naver News Search API does not
support historical date filtering, so we cannot honor PRD §5 data-leakage
rules with arbitrary past news. LLM analysis runs on DART evidence only.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from analysis.evidence import normalize_evidence
from analysis.models import AISignal, AnalysisError, Evidence, OutlookReport
from analysis.scoring import combine_signals
from disclosure.disclosure_api import enrich_disclosure_texts, search_disclosures
from disclosure.financial_statement_single_account_api import fetch_all_reports_last_n_years
from financial.metrics import analyze_financials
from llm.analyzer import DisabledLLMAnalyzer
from llm.cache import CachedLLMAnalyzer, EvidenceAnalyzer
from quant.models import QuantSignal
from services.outlook import lookup_corp_code, lookup_stock_master

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Quant signal computation from a price slice
# ---------------------------------------------------------------------------


def _ensure_sorted(prices: pd.DataFrame) -> pd.DataFrame:
    df = prices.copy()
    df["date"] = df["date"].astype(str)
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("close", "open", "high", "low", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _to_kis_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def prices_up_to(prices: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    """Return the rows whose date is on or before `as_of_date`, sorted asc."""
    df = _ensure_sorted(prices)
    cutoff = _to_kis_date(as_of_date)
    return df[df["date"] <= cutoff].reset_index(drop=True)


def _quant_neutral(label: str, api: str = "inquire_daily_itemchartprice") -> QuantSignal:
    return QuantSignal(label=label, direction="neutral", score=0, value=None, api_used=api)


def golden_cross_signal_from_prices(prices: pd.DataFrame) -> QuantSignal:
    """MA5/MA20 cross direction at the latest available row."""
    label = "골든크로스 (MA5/MA20)"
    if prices.empty or len(prices) < 21:
        return _quant_neutral(label)

    ma_short = prices["close"].rolling(5).mean()
    ma_long = prices["close"].rolling(20).mean()
    prev_short, curr_short = ma_short.iloc[-2], ma_short.iloc[-1]
    prev_long, curr_long = ma_long.iloc[-2], ma_long.iloc[-1]
    if pd.isna(prev_short) or pd.isna(prev_long):
        return _quant_neutral(label)

    if prev_short < prev_long and curr_short > curr_long:
        return QuantSignal(
            label=label, direction="positive", score=2,
            value=round(float(curr_short), 2), api_used="inquire_daily_itemchartprice",
        )
    if prev_short > prev_long and curr_short < curr_long:
        return QuantSignal(
            label=label, direction="negative", score=-2,
            value=round(float(curr_short), 2), api_used="inquire_daily_itemchartprice",
        )
    return QuantSignal(
        label=label, direction="neutral", score=0,
        value=round(float(curr_short), 2), api_used="inquire_daily_itemchartprice",
    )


def disparity_signal_from_prices(prices: pd.DataFrame) -> QuantSignal:
    """이격도 = close / MA20 * 100; <90 매수, >110 매도."""
    label = "이격도 (MA20 대비 현재가 %)"
    if prices.empty or len(prices) < 20:
        return _quant_neutral(label)

    ma20 = prices["close"].rolling(20).mean().iloc[-1]
    close = prices["close"].iloc[-1]
    if pd.isna(ma20) or ma20 == 0:
        return _quant_neutral(label)

    disparity = round(float(close / ma20 * 100), 2)
    if disparity < 90.0:
        return QuantSignal(label=label, direction="positive", score=2, value=disparity, api_used="inquire_daily_itemchartprice")
    if disparity > 110.0:
        return QuantSignal(label=label, direction="negative", score=-2, value=disparity, api_used="inquire_daily_itemchartprice")
    return QuantSignal(label=label, direction="neutral", score=0, value=disparity, api_used="inquire_daily_itemchartprice")


def momentum_signal_from_prices(prices: pd.DataFrame, lookback_days: int = 60) -> QuantSignal:
    """60-day return: ≥+30% 매수, ≤-20% 매도."""
    label = "모멘텀 (60일 수익률)"
    if prices.empty or len(prices) < lookback_days + 1:
        return _quant_neutral(label)

    curr = prices["close"].iloc[-1]
    base = prices["close"].iloc[-(lookback_days + 1)]
    if pd.isna(curr) or pd.isna(base) or base == 0:
        return _quant_neutral(label)

    ret = round(float((curr - base) / base), 4)
    if ret >= 0.30:
        return QuantSignal(label=label, direction="positive", score=1, value=ret, api_used="inquire_daily_itemchartprice")
    if ret <= -0.20:
        return QuantSignal(label=label, direction="negative", score=-1, value=ret, api_used="inquire_daily_itemchartprice")
    return QuantSignal(label=label, direction="neutral", score=0, value=ret, api_used="inquire_daily_itemchartprice")


def volume_spike_signal_from_prices(prices: pd.DataFrame) -> QuantSignal:
    """latest volume / 20-day avg ratio; ≥2.0 급증(+1), ≤0.5 위축(-1)."""
    label = "거래량 급증 (20일 평균 대비)"
    if prices.empty or len(prices) < 21 or "volume" not in prices.columns:
        return _quant_neutral(label)

    avg_vol = prices["volume"].iloc[-21:-1].mean()
    if pd.isna(avg_vol) or avg_vol <= 0:
        return _quant_neutral(label)

    ratio = round(float(prices["volume"].iloc[-1] / avg_vol), 2)
    if ratio >= 2.0:
        return QuantSignal(label=label, direction="positive", score=1, value=ratio, api_used="inquire_daily_itemchartprice")
    if ratio <= 0.5:
        return QuantSignal(label=label, direction="negative", score=-1, value=ratio, api_used="inquire_daily_itemchartprice")
    return QuantSignal(label=label, direction="neutral", score=0, value=ratio, api_used="inquire_daily_itemchartprice")


def foreign_investor_signal_from_daily(
    investor_daily: pd.DataFrame,
    as_of_date: date,
    lookback_days: int = 3,
) -> QuantSignal:
    """Sum of foreign net buying over the last `lookback_days` rows up to as_of_date."""
    label = "외인 순매수 (3일 누적)"
    api = "investor_trade_by_stock_daily"
    if investor_daily is None or investor_daily.empty:
        return QuantSignal(label=label, direction="neutral", score=0, value=None, api_used=api)

    df = investor_daily.copy()
    if "stck_bsop_date" in df.columns:
        df["date"] = df["stck_bsop_date"].astype(str)
    elif "date" in df.columns:
        df["date"] = df["date"].astype(str)
    else:
        return QuantSignal(label=label, direction="neutral", score=0, value=None, api_used=api)

    cutoff = _to_kis_date(as_of_date)
    df = df[df["date"] <= cutoff].sort_values("date")
    df = df.tail(lookback_days)
    if df.empty:
        return QuantSignal(label=label, direction="neutral", score=0, value=None, api_used=api)

    qty_col = next(
        (col for col in ("frgn_ntby_qty", "frgn_seln_vol", "frgn_ntby_qtyrt") if col in df.columns),
        None,
    )
    if qty_col is None:
        return QuantSignal(label=label, direction="neutral", score=0, value=None, api_used=api)

    net_qty = pd.to_numeric(df[qty_col], errors="coerce").fillna(0).sum()
    if net_qty > 0:
        return QuantSignal(label=label, direction="positive", score=2, value=float(net_qty), api_used=api)
    if net_qty < 0:
        return QuantSignal(label=label, direction="negative", score=-2, value=float(net_qty), api_used=api)
    return QuantSignal(label=label, direction="neutral", score=0, value=float(net_qty), api_used=api)


def compute_quant_signals_at(
    prices: pd.DataFrame,
    investor_daily: pd.DataFrame,
    as_of_date: date,
) -> list[QuantSignal]:
    sliced = prices_up_to(prices, as_of_date)
    return [
        golden_cross_signal_from_prices(sliced),
        disparity_signal_from_prices(sliced),
        momentum_signal_from_prices(sliced),
        foreign_investor_signal_from_daily(investor_daily, as_of_date),
        volume_spike_signal_from_prices(sliced),
    ]


# ---------------------------------------------------------------------------
# DART evidence/financial slicing
# ---------------------------------------------------------------------------


def disclosures_as_of(
    all_disclosures: list[Evidence],
    as_of_date: date,
    lookback_days: int = 45,
) -> list[Evidence]:
    """Return disclosures published in [as_of_date - lookback_days, as_of_date]."""
    start = datetime.combine(as_of_date - timedelta(days=lookback_days), datetime.min.time())
    end = datetime.combine(as_of_date, datetime.max.time())
    filtered = []
    for item in all_disclosures:
        if item.published_at is None:
            continue
        published = item.published_at
        if published.tzinfo is not None:
            published = published.replace(tzinfo=None)
        if start <= published <= end:
            filtered.append(item)
    return normalize_evidence(filtered)


def _statement_published_on_or_before(rcept_no: Any, as_of_date: date) -> bool:
    text = str(rcept_no or "")
    if len(text) < 8 or not text[:8].isdigit():
        return False
    try:
        published = datetime.strptime(text[:8], "%Y%m%d").date()
    except ValueError:
        return False
    return published <= as_of_date


def financials_as_of(statements: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    if statements is None or statements.empty or "rcept_no" not in statements.columns:
        return pd.DataFrame()
    mask = statements["rcept_no"].map(lambda v: _statement_published_on_or_before(v, as_of_date))
    return statements[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Per-stock data prefetch
# ---------------------------------------------------------------------------


@dataclass
class StockHistory:
    stock_code: str
    stock_name: str | None
    corp_code: str | None
    prices: pd.DataFrame
    investor_daily: pd.DataFrame
    disclosure_evidence: list[Evidence] = field(default_factory=list)
    financials: pd.DataFrame = field(default_factory=pd.DataFrame)
    errors: list[AnalysisError] = field(default_factory=list)


_INVESTOR_TOOL_PATH = PROJECT_ROOT / "tools" / "domestic_stock" / "investor_trade_by_stock_daily.py"


def _load_investor_daily_tool():
    spec = importlib.util.spec_from_file_location(
        "investor_trade_by_stock_daily_tool", _INVESTOR_TOOL_PATH,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load KIS investor-trade tool from {_INVESTOR_TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.investor_trade_by_stock_daily


def _call_investor_daily(fetch_fn, *, stock_code: str, end_date: date) -> pd.DataFrame:
    kwargs = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code,
        "fid_input_date_1": _to_kis_date(end_date),
        "fid_org_adj_prc": "",
        "fid_etc_cls_code": "",
    }
    if callable(fetch_fn):
        result = fetch_fn(**kwargs)
    elif hasattr(fetch_fn, "invoke"):
        result = fetch_fn.invoke(kwargs)
    elif hasattr(fetch_fn, "func") and callable(fetch_fn.func):
        result = fetch_fn.func(**kwargs)
    else:
        raise TypeError(f"Unsupported KIS investor-daily callable: {type(fetch_fn).__name__}")
    if isinstance(result, tuple):
        return result[1] if len(result) > 1 else result[0]
    return result


def fetch_investor_daily(
    stock_code: str,
    end_date: date,
    investor_daily_fn=None,
) -> tuple[pd.DataFrame, list[AnalysisError]]:
    try:
        fetch_fn = investor_daily_fn or _load_investor_daily_tool()
        df = _call_investor_daily(fetch_fn, stock_code=stock_code, end_date=end_date)
    except Exception as exc:
        return pd.DataFrame(), [
            AnalysisError(
                source="kis_investor_daily",
                code="fetch_failed",
                message=f"investor_trade_by_stock_daily failed for {stock_code}: {exc}",
            )
        ]
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame(), []


def _fetch_kis_prices_with_volume(stock_code: str, days: int = 150) -> pd.DataFrame:
    """Fetch KIS daily prices with the volume column (which prices.csv strips)."""
    try:
        sys_path = str(PROJECT_ROOT / "tools" / "strategy")
        import sys
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from core import data_fetcher
        df = data_fetcher.get_daily_prices(stock_code, days=days, env_dv="real")
        if df is None or df.empty:
            return pd.DataFrame()
        return df
    except Exception as exc:
        logger.warning("KIS price fetch failed for %s: %s", stock_code, exc)
        return pd.DataFrame()


def prefetch_stock_history(
    stock_code: str,
    prices: pd.DataFrame,
    backfill_start: date,
    backfill_end: date,
    disclosure_lookback_days: int = 60,
    financial_years: int = 3,
    investor_daily_fn=None,
    fetch_kis_prices: bool = True,
) -> StockHistory:
    stock = lookup_stock_master(stock_code)
    stock_name = stock["corp_name"] if stock else None
    corp_code = lookup_corp_code(stock_code)
    errors: list[AnalysisError] = []

    # KIS gives prices WITH volume (prices.csv strips it). Backfill window ends
    # at `backfill_end`, which is at most today, so the latest ~150 KIS days
    # cover our window.
    kis_prices = _fetch_kis_prices_with_volume(stock_code) if fetch_kis_prices else pd.DataFrame()
    if not kis_prices.empty and "volume" in kis_prices.columns:
        merged_prices = kis_prices
    else:
        merged_prices = prices

    investor_daily, investor_errors = fetch_investor_daily(
        stock_code, backfill_end, investor_daily_fn=investor_daily_fn,
    )
    errors.extend(investor_errors)

    disclosure_evidence: list[Evidence] = []
    financials = pd.DataFrame()
    if corp_code:
        disclosure_start = backfill_start - timedelta(days=disclosure_lookback_days)
        disclosure_result = search_disclosures(
            corp_code=corp_code,
            bgn_de=_to_kis_date(disclosure_start),
            end_de=_to_kis_date(backfill_end),
            page_count=100,
        )
        errors.extend(disclosure_result.errors)
        # Disclosure title alone carries the trading signal; the zipped body is
        # large and the DART document API is rate-limited, so we keep evidence
        # at title-level for backfill.
        disclosure_evidence = disclosure_result.evidence

        try:
            financial_result = fetch_all_reports_last_n_years(
                corp_code,
                years=financial_years,
                current_year=backfill_end.year,
            )
            errors.extend(financial_result.errors)
            financials = financial_result.dataframe
        except Exception as exc:
            errors.append(
                AnalysisError(
                    source="dart_financial",
                    code="fetch_failed",
                    message=f"fetch_all_reports_last_n_years failed for {stock_code}: {exc}",
                )
            )
    else:
        errors.append(
            AnalysisError(
                source="corp_code",
                code="not_found",
                message=f"No DART corp_code mapping found for stock code {stock_code}",
            )
        )

    return StockHistory(
        stock_code=stock_code,
        stock_name=stock_name,
        corp_code=corp_code,
        prices=_ensure_sorted(merged_prices),
        investor_daily=investor_daily,
        disclosure_evidence=disclosure_evidence,
        financials=financials,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# OutlookReport assembly
# ---------------------------------------------------------------------------


class HistoricalOutlookProvider:
    """Build an `OutlookReport` for (stock_code, as_of_date) from cached data.

    News is intentionally omitted (no historical Naver search). DART evidence
    is filtered by publication date relative to as_of_date so the report
    respects PRD §5 data-leakage rules.
    """

    def __init__(
        self,
        histories: dict[str, StockHistory],
        llm_analyzer: EvidenceAnalyzer | None = None,
        disclosure_lookback_days: int = 45,
    ):
        self._histories = histories
        self._llm_analyzer = llm_analyzer or DisabledLLMAnalyzer()
        self._disclosure_lookback_days = disclosure_lookback_days

    def __call__(self, *, stock_code: str, as_of_date: date) -> OutlookReport:
        history = self._histories.get(stock_code)
        if history is None:
            return _empty_report(stock_code, as_of_date, reason="no prefetched history")

        quant_signals = compute_quant_signals_at(history.prices, history.investor_daily, as_of_date)

        disclosure_evidence = disclosures_as_of(
            history.disclosure_evidence, as_of_date, lookback_days=self._disclosure_lookback_days,
        )

        financial_signals: list[Any] = []
        financial_evidence: list[Evidence] = []
        if not history.financials.empty:
            applicable = financials_as_of(history.financials, as_of_date)
            if not applicable.empty:
                analyzed = analyze_financials(applicable)
                financial_signals = analyzed.signals
                financial_evidence = analyzed.evidence

        evidence: list[Evidence] = []
        evidence.extend(disclosure_evidence)
        evidence.extend(financial_evidence)

        llm_result = self._llm_analyzer.analyze_evidence(evidence)
        ai_signals = list(llm_result.signals) or []

        score = combine_signals(
            quant_signals=quant_signals,
            ai_signals=ai_signals,
            financial_signals=financial_signals,
        )

        generated_at = datetime.combine(as_of_date, datetime.min.time(), tzinfo=timezone.utc)
        return OutlookReport(
            stock_code=stock_code,
            stock_name=history.stock_name,
            generated_at=generated_at,
            summary=f"{history.stock_name or stock_code} historical outlook ({as_of_date.isoformat()}) "
                    f"is {score.direction} with total score {score.total_score}.",
            score=score,
            quant_signals=quant_signals,
            ai_signals=ai_signals,
            financial_signals=financial_signals,
            evidence=evidence,
            errors=list(history.errors) + list(llm_result.errors),
        )


def _empty_report(stock_code: str, as_of_date: date, reason: str) -> OutlookReport:
    score = combine_signals()
    return OutlookReport(
        stock_code=stock_code,
        stock_name=None,
        generated_at=datetime.combine(as_of_date, datetime.min.time(), tzinfo=timezone.utc),
        summary=f"Historical outlook unavailable: {reason}",
        score=score,
        quant_signals=[],
        ai_signals=[],
        financial_signals=[],
        evidence=[],
        errors=[
            AnalysisError(
                source="historical",
                code="missing_history",
                message=reason,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Backfill orchestration helpers
# ---------------------------------------------------------------------------


def load_prices_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"stock_code": str, "date": str})
    return _ensure_sorted(df)


def trading_dates_for_stock(prices: pd.DataFrame, stock_code: str) -> list[date]:
    df = prices[prices["stock_code"] == stock_code]
    dates: list[date] = []
    for raw in df["date"].astype(str).tolist():
        if len(raw) == 8 and raw.isdigit():
            try:
                dates.append(datetime.strptime(raw, "%Y%m%d").date())
            except ValueError:
                continue
    return sorted(set(dates))


def slice_prices_for_stock(prices: pd.DataFrame, stock_code: str) -> pd.DataFrame:
    return prices[prices["stock_code"] == stock_code].copy()


def make_llm_analyzer(cache_path: str | Path | None = None) -> EvidenceAnalyzer:
    """Build a (cached) OpenAI analyzer if OPENAI_API_KEY is set; else disabled."""
    import os
    if not os.getenv("OPENAI_API_KEY"):
        return DisabledLLMAnalyzer()

    from llm.analyzer import OpenAIResponsesAnalyzer

    analyzer: EvidenceAnalyzer = OpenAIResponsesAnalyzer()
    cache = cache_path or os.getenv("OUTLOOK_LLM_CACHE_PATH")
    if cache:
        analyzer = CachedLLMAnalyzer(analyzer, cache)
    return analyzer
