"""Orchestration for investment outlook reports."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analysis.models import AnalysisError, MarketQuote, OutlookReport
from analysis.scoring import combine_signals
from services.position import PriceQuoteFn, _kis_current_price_quote, compute_position_context
from disclosure.disclosure_api import enrich_disclosure_texts, search_disclosures
from disclosure.financial_statement_single_account_api import fetch_all_reports_last_n_years
from financial.metrics import analyze_financials
from llm.cache import CachedLLMAnalyzer
from llm.analyzer import DisabledLLMAnalyzer, OpenAIResponsesAnalyzer
from ml.runtime import OutlookMLPredictor, load_predictor_from_env
from news.kis_news_title import fetch_kis_news_titles
from news.naver_news_api import build_stock_news_query, search_naver_news, search_naver_news_by_titles
from quant.engine import QuantEngine
from quant.models import QuantSignal

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 검색 결과 우선순위 — 서버 시작 시 screener DB 거래량으로 동적 로드
# 로드 전 폴백용 하드코딩 (주요 대형주)
_SEARCH_PRIORITY: dict[str, int] = {
    "005930": 1,  "000660": 2,  "373220": 3,  "207940": 4,  "005490": 5,
    "005380": 6,  "000270": 7,  "068270": 8,  "035420": 9,  "051910": 10,
    "006400": 11, "035720": 12, "003670": 13, "066570": 14, "028260": 15,
    "034730": 16, "018260": 17, "015760": 18, "086520": 19, "011200": 20,
}


def load_search_priority_from_db() -> None:
    """screener DB의 최근 거래량 합산으로 _SEARCH_PRIORITY를 갱신."""
    global _SEARCH_PRIORITY
    try:
        from services.screener_db import get_conn
        from contextlib import closing
        with closing(get_conn()) as conn:
            rows = conn.execute(
                """SELECT stock_code, SUM(CAST(volume AS REAL) * close) AS total_val
                   FROM daily_price
                   GROUP BY stock_code
                   ORDER BY total_val DESC"""
            ).fetchall()
        if rows:
            _SEARCH_PRIORITY = {row["stock_code"]: rank + 1 for rank, row in enumerate(rows)}
    except Exception:
        pass  # DB 없으면 하드코딩 폴백 유지

_STOCK_MASTER_CSVS: tuple[Path, ...] = (
    _PROJECT_ROOT / "kospi.csv",
    _PROJECT_ROOT / "kosdaq.csv",
)
_DART_MAPPING_CSVS: tuple[Path, ...] = (
    _PROJECT_ROOT / "disclosure" / "kospi.csv",
    _PROJECT_ROOT / "disclosure" / "kosdaq.csv",
)


def _select_llm_analyzer():
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIResponsesAnalyzer()
    return DisabledLLMAnalyzer()


class OutlookService:
    def __init__(
        self,
        quant_engine: QuantEngine | None = None,
        ml_predictor: OutlookMLPredictor | None = None,
        price_quote_fn: PriceQuoteFn | None = None,
    ):
        self.quant_engine = quant_engine or QuantEngine()
        self.ml_predictor = ml_predictor or load_predictor_from_env()
        self.price_quote_fn = price_quote_fn
        self.llm_analyzer = _select_llm_analyzer()
        if os.getenv("OUTLOOK_LLM_CACHE_PATH"):
            self.llm_analyzer = CachedLLMAnalyzer(self.llm_analyzer, os.environ["OUTLOOK_LLM_CACHE_PATH"])

    def build_report(
        self,
        stock_code: str,
        stock_name: str | None = None,
        *,
        avg_price: float | None = None,
        quantity: int | None = None,
        held_since: str | None = None,
    ) -> OutlookReport:
        stock = lookup_stock_master(stock_code)
        normalized_code = stock["stock_code"] if stock else stock_code.strip()
        display_name = stock_name or (stock["corp_name"] if stock else normalized_code)
        errors: list[AnalysisError] = []

        if not stock:
            errors.append(
                AnalysisError(
                    source="stock_lookup",
                    code="not_listed_or_not_found",
                    message=(
                        f"'{stock_code}' was not found in the local KOSPI/KOSDAQ stock master. "
                        "LLM analysis was skipped."
                    ),
                )
            )
            score = combine_signals()
            report = OutlookReport(
                stock_code=normalized_code,
                stock_name=stock_name,
                summary=f"{display_name} outlook is unavailable because the stock is not in the KOSPI/KOSDAQ master.",
                score=score,
                quant_signals=[],
                ai_signals=[],
                financial_signals=[],
                evidence=[],
                errors=errors,
            )
            return self._attach_ml_prediction(report, errors)

        quant_signals = self._get_quant_signals(normalized_code, display_name, errors)
        evidence = []

        news_end = datetime.now(timezone.utc)
        news_start = news_end - timedelta(days=7)
        kis_news_result = fetch_kis_news_titles(normalized_code, display_name, limit=5)
        errors.extend(kis_news_result.errors)
        kis_title_naver_result = search_naver_news_by_titles(
            [item.title for item in kis_news_result.titles],
            max_results=5,
            start_date=news_start,
            end_date=news_end,
        )
        evidence.extend(kis_title_naver_result.evidence)
        errors.extend(kis_title_naver_result.errors)

        stock_query_naver_result = search_naver_news(
            build_stock_news_query(display_name),
            display=5,
            start_date=news_start,
            end_date=news_end,
        )
        evidence.extend(stock_query_naver_result.evidence)
        errors.extend(stock_query_naver_result.errors)

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

        fetcher = self.price_quote_fn or _kis_current_price_quote
        quote_dict = fetcher(normalized_code)
        market_quote = _build_market_quote(quote_dict)

        llm_result = self.llm_analyzer.analyze_evidence(evidence)
        errors.extend(llm_result.errors)

        score = combine_signals(
            quant_signals=quant_signals,
            ai_signals=llm_result.signals,
            financial_signals=financial_signals,
        )

        position_context = compute_position_context(
            normalized_code,
            avg_price=avg_price,
            quantity=quantity,
            held_since=held_since,
            price_quote_fn=lambda _code, _q=quote_dict: _q,
        )

        report = OutlookReport(
            stock_code=normalized_code,
            stock_name=stock_name or (stock["corp_name"] if stock else None),
            summary=f"{display_name} outlook is {score.direction} with total score {score.total_score}.",
            score=score,
            quant_signals=quant_signals,
            ai_signals=llm_result.signals,
            financial_signals=financial_signals,
            market_quote=market_quote,
            position_context=position_context,
            evidence=evidence,
            errors=errors,
        )
        return self._attach_ml_prediction(report, errors)

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

    def _attach_ml_prediction(
        self,
        report: OutlookReport,
        errors: list[AnalysisError],
    ) -> OutlookReport:
        if not self.ml_predictor:
            return report
        try:
            prediction = self.ml_predictor.predict_report(report)
        except Exception as exc:
            errors.append(
                AnalysisError(source="ml_prediction", code="failed", message=f"ML prediction failed: {exc}")
            )
            return report.model_copy(update={"errors": errors})
        return report.model_copy(update={"ml_prediction": prediction, "errors": errors})


def _build_market_quote(quote: dict | None) -> MarketQuote | None:
    if not quote:
        return None
    try:
        price = float(quote.get("price") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    def _opt_float(key: str) -> float | None:
        raw = quote.get(key)
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _opt_int(key: str) -> int | None:
        raw = quote.get(key)
        if raw is None:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    try:
        change = float(quote.get("change") or 0)
        change_rate = float(quote.get("change_rate") or 0)
    except (TypeError, ValueError):
        change = 0.0
        change_rate = 0.0

    return MarketQuote(
        price=price,
        change=change,
        change_rate=change_rate,
        high=_opt_float("high"),
        low=_opt_float("low"),
        volume=_opt_int("volume"),
        w52_high=_opt_float("w52_high"),
        w52_low=_opt_float("w52_low"),
    )


def _read_csv_rows(csv_path: Path, encodings: tuple[str, ...] = ("utf-8-sig", "cp949", "euc-kr")):
    for encoding in encodings:
        try:
            with csv_path.open(encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    return []


def _coerce_csv_paths(csv_paths: Path | tuple[Path, ...]) -> tuple[Path, ...]:
    if isinstance(csv_paths, Path):
        return (csv_paths,)
    return tuple(csv_paths)


def lookup_corp_code(
    stock_code: str,
    csv_paths: Path | tuple[Path, ...] = _DART_MAPPING_CSVS,
) -> str | None:
    stock = lookup_dart_stock_mapping(stock_code, csv_paths=csv_paths)
    return stock["corp_code"] if stock else None


def load_all_stock_names(
    csv_paths: Path | tuple[Path, ...] = _STOCK_MASTER_CSVS,
) -> dict[str, str]:
    """전체 종목코드 → 종목명 dict 반환. DB 우선, 없으면 CSV 폴백."""
    try:
        from services.screener_db import get_all_stock_names
        names = get_all_stock_names()
        if names:
            return names
    except Exception:
        pass

    result: dict[str, str] = {}
    for csv_path in _coerce_csv_paths(csv_paths):
        if not csv_path.exists():
            continue
        for row in _read_csv_rows(csv_path):
            code = (row.get("단축코드") or "").strip()
            full = (row.get("한글 종목명") or "").strip()
            short = (row.get("한글 종목약명") or "").strip()
            name = short or full
            if code and code not in result:
                result[code] = name
    return result


def search_stock_master(
    query: str,
    csv_paths: Path | tuple[Path, ...] = _STOCK_MASTER_CSVS,
    limit: int = 10,
) -> list[dict[str, str]]:
    """부분 일치 종목 검색. 코드 또는 이름의 앞부분 일치 우선, 포함 일치 후순위."""
    q = query.strip()
    if not q:
        return []
    q_lower = q.lower()
    exact: list[dict[str, str]] = []
    starts: list[dict[str, str]] = []
    contains: list[dict[str, str]] = []
    seen: set[str] = set()
    for csv_path in _coerce_csv_paths(csv_paths):
        if not csv_path.exists():
            continue
        for row in _read_csv_rows(csv_path):
            code = (row.get("단축코드") or "").strip()
            full = (row.get("한글 종목명") or "").strip()
            short = (row.get("한글 종목약명") or "").strip()
            name = short or full
            if not code or code in seen:
                continue
            if q in (code, full, short):
                seen.add(code)
                exact.append({"stock_code": code, "corp_name": name})
            elif code.startswith(q) or name.lower().startswith(q_lower):
                seen.add(code)
                starts.append({"stock_code": code, "corp_name": name})
            elif q_lower in name.lower():
                seen.add(code)
                contains.append({"stock_code": code, "corp_name": name})
    def _rank(item: dict[str, str]) -> tuple:
        code = item["stock_code"]
        priority = _SEARCH_PRIORITY.get(code, 9999)
        return (priority, len(item["corp_name"]), code)

    results = exact + sorted(starts, key=_rank) + sorted(contains, key=_rank)
    return results[:limit]


def lookup_stock_master(
    query: str,
    csv_paths: Path | tuple[Path, ...] = _STOCK_MASTER_CSVS,
) -> dict[str, str] | None:
    """Lookup stock code/name from the local KOSPI/KOSDAQ stock master CSVs."""
    normalized_query = query.strip()
    for csv_path in _coerce_csv_paths(csv_paths):
        if not csv_path.exists():
            continue
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


def lookup_dart_stock_mapping(
    query: str,
    csv_paths: Path | tuple[Path, ...] = _DART_MAPPING_CSVS,
) -> dict[str, str] | None:
    """Best-effort lookup from the local DART corp-code CSV(s) for KOSPI/KOSDAQ."""
    normalized_query = query.strip()
    for csv_path in _coerce_csv_paths(csv_paths):
        if not csv_path.exists():
            continue
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
