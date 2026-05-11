"""Manual live test for stock evidence collection + LLM analysis.

Usage:
    python scripts/test_llm_stock_analysis.py
    # then enter: 삼성전자

    python scripts/test_llm_stock_analysis.py 삼성전자
    python scripts/test_llm_stock_analysis.py 005930 --stock-name 삼성전자

The script loads `.env` if present, collects Naver news, DART disclosures, DART
financial statements, derives deterministic financial signals, then sends the
collected Evidence to the configured LLM analyzer.

Required for live LLM analysis:
    DISCLOSURE_CRTFC_KEY
    NAVER_NEWS_API_CLIENT
    NAVER_NEWS_API_SECRET
    OPENAI_API_KEY

Secrets are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from disclosure.disclosure_api import enrich_disclosure_texts, search_disclosures
from disclosure.financial_statement_single_account_api import fetch_all_reports_last_n_years
from financial.metrics import analyze_financials
from llm.analyzer import DisabledLLMAnalyzer, OpenAIResponsesAnalyzer
from news.naver_news_api import search_naver_news
from services.outlook import lookup_corp_code, lookup_dart_stock_mapping, lookup_stock_master


def load_dotenv_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def is_configured(name: str) -> bool:
    return bool(os.getenv(name))


def model_dump_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [model_dump_jsonable(item) for item in obj]
    if isinstance(obj, dict):
        return {key: model_dump_jsonable(value) for key, value in obj.items()}
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(description="Live LLM stock analysis test")
    parser.add_argument(
        "query",
        nargs="?",
        help=(
            "Korean stock code or exact stock name. Name lookup uses root kospi.csv; "
            "DART corp_code mapping still depends on disclosure/kospi.csv."
        ),
    )
    parser.add_argument("--stock-name", help="Optional stock name when query is a stock code")
    parser.add_argument("--news-display", type=int, default=5, help="Naver news item count")
    parser.add_argument("--days", type=int, default=45, help="DART disclosure lookback days")
    parser.add_argument(
        "--disclosure-docs",
        type=int,
        default=3,
        help="Number of DART disclosure zip documents to download and extract",
    )
    args = parser.parse_args()

    load_dotenv_file()

    query = args.query
    if not query:
        query = input("종목명 또는 종목코드를 입력하세요: ").strip()
    if not query:
        parser.error("종목명 또는 종목코드가 필요합니다.")

    print(
        json.dumps(
            {
                "configured": {
                    "DISCLOSURE_CRTFC_KEY": is_configured("DISCLOSURE_CRTFC_KEY"),
                    "NAVER_NEWS_API_CLIENT": is_configured("NAVER_NEWS_API_CLIENT"),
                    "NAVER_NEWS_API_SECRET": is_configured("NAVER_NEWS_API_SECRET"),
                    "OPENAI_API_KEY": is_configured("OPENAI_API_KEY"),
                    "OPENAI_MODEL": os.getenv("OPENAI_MODEL") or "gpt-5.2",
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    errors = []
    evidence = []
    financial_signals = []
    stock = lookup_stock_master(query) or lookup_dart_stock_mapping(query)
    if stock:
        stock_code = stock["stock_code"]
        stock_name = args.stock_name or stock["corp_name"]
        corp_code = stock.get("corp_code") or lookup_corp_code(stock_code)
    else:
        stock_code = query
        stock_name = args.stock_name or query
        corp_code = None
        if not query.isdigit():
            errors.append(
                {
                    "source": "stock_lookup",
                    "code": "name_not_found",
                    "message": (
                        f"Could not resolve stock name '{query}' from local stock master. "
                        "Retry with a 6-digit stock code and --stock-name."
                    ),
                    "recoverable": True,
                }
            )

    news_result = search_naver_news(stock_name, display=args.news_display)
    evidence.extend(news_result.evidence)
    errors.extend(news_result.errors)

    if corp_code:
        end = datetime.now()
        start = end - timedelta(days=args.days)

        disclosure_result = search_disclosures(
            corp_code=corp_code,
            bgn_de=start.strftime("%Y%m%d"),
            end_de=end.strftime("%Y%m%d"),
        )
        enriched_disclosures = enrich_disclosure_texts(
            disclosure_result.evidence,
            max_documents=args.disclosure_docs,
        )
        evidence.extend(enriched_disclosures.evidence)
        errors.extend(disclosure_result.errors)
        errors.extend(enriched_disclosures.errors)

        financial_result = fetch_all_reports_last_n_years(corp_code)
        errors.extend(financial_result.errors)
        if not financial_result.dataframe.empty:
            analyzed_financials = analyze_financials(financial_result.dataframe)
            evidence.extend(analyzed_financials.evidence)
            financial_signals.extend(analyzed_financials.signals)
            errors.extend(analyzed_financials.errors)
    else:
        errors.append(
            {
                "source": "corp_code",
                "code": "not_found",
                "message": f"No DART corp_code mapping found for {query}",
                "recoverable": True,
            }
        )

    analyzer = OpenAIResponsesAnalyzer() if os.getenv("OPENAI_API_KEY") else DisabledLLMAnalyzer()
    llm_result = analyzer.analyze_evidence(evidence)
    errors.extend(llm_result.errors)

    output = {
        "stock": {"code": stock_code, "name": stock_name, "corp_code": corp_code},
        "counts": {
            "evidence": len(evidence),
            "news": len([item for item in evidence if item.kind == "news"]),
            "disclosures": len([item for item in evidence if item.kind == "disclosure"]),
            "financial": len([item for item in evidence if item.kind == "financial"]),
            "financial_signals": len(financial_signals),
            "llm_signals": len(llm_result.signals),
            "errors": len(errors),
        },
        "llm_signals": model_dump_jsonable(llm_result.signals),
        "financial_signals": model_dump_jsonable(financial_signals),
        "evidence_preview": [
            {
                "evidence_id": item.evidence_id,
                "kind": item.kind,
                "source": item.source,
                "title": item.title,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "has_content": bool(item.content),
            }
            for item in evidence[:10]
        ],
        "errors": model_dump_jsonable(errors),
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
