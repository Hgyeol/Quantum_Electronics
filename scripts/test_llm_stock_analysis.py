"""Manual live test for stock evidence collection + LLM analysis.

Usage:
    python scripts/test_llm_stock_analysis.py
    # then enter: 삼성전자

    python scripts/test_llm_stock_analysis.py --kis-auth
    python scripts/test_llm_stock_analysis.py 삼성전자
    python scripts/test_llm_stock_analysis.py 005930 --stock-name 삼성전자

The script loads `.env` if present, collects KIS quant signals, Naver news,
DART disclosures, and DART financial statements. It derives deterministic
financial signals, sends the collected Evidence to the configured LLM analyzer,
then combines quant + LLM + financial scores into the final outlook score.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from analysis.scoring import combine_signals
from disclosure.disclosure_api import enrich_disclosure_texts, search_disclosures
from disclosure.financial_statement_single_account_api import fetch_all_reports_last_n_years
from financial.metrics import analyze_financials
from llm.analyzer import DisabledLLMAnalyzer, OpenAIResponsesAnalyzer
from news.kis_news_title import fetch_kis_news_titles
from news.naver_news_api import build_stock_news_query, search_naver_news, search_naver_news_by_titles
from quant.engine import QuantEngine
from services.outlook import lookup_corp_code, lookup_stock_master


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
            "Korean stock code or exact stock name. Name lookup uses root kospi.csv + kosdaq.csv; "
            "DART corp_code mapping uses disclosure/kospi.csv + disclosure/kosdaq.csv."
        ),
    )
    parser.add_argument("--stock-name", help="Optional stock name when query is a stock code")
    parser.add_argument("--news-display", type=int, default=5, help="Naver news item count")
    parser.add_argument("--kis-news-limit", type=int, default=5, help="KIS news-title item count")
    parser.add_argument("--kis-auth", action="store_true", help="Authenticate KIS before collecting KIS news titles")
    parser.add_argument("--kis-server", default="prod", choices=["prod", "vps"], help="KIS server for --kis-auth")
    parser.add_argument("--quant-env", default="real", choices=["real", "demo"], help="KIS env_dv for quant APIs")
    parser.add_argument("--news-days", type=int, default=7, help="Keep only news from the last N days")
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
                    "KIS_CONFIG_FILE": is_configured("KIS_CONFIG_FILE"),
                    "KIS_CONFIG_ROOT": is_configured("KIS_CONFIG_ROOT"),
                    "KIS_TOKEN_PATH": is_configured("KIS_TOKEN_PATH"),
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
    quant_signals = []
    financial_signals = []
    kis_authenticated = False
    if args.kis_auth:
        try:
            import kis_auth

            kis_auth.auth(svr=args.kis_server)
            kis_authenticated = True
        except Exception as exc:
            errors.append(
                {
                    "source": "kis_auth",
                    "code": "auth_failed",
                    "message": f"KIS auth failed: {exc}",
                    "recoverable": True,
                }
            )
    stock = lookup_stock_master(query)
    if stock:
        stock_code = stock["stock_code"]
        stock_name = args.stock_name or stock["corp_name"]
        corp_code = stock.get("corp_code") or lookup_corp_code(stock_code)
    else:
        stock_code = query
        stock_name = args.stock_name or query
        corp_code = None
        errors.append(
            {
                "source": "stock_lookup",
                "code": "not_listed_or_not_found",
                "message": (
                    f"Could not resolve '{query}' from the local KOSPI/KOSDAQ stock master. "
                    "News, disclosure, financial, and LLM analysis were skipped."
                ),
                "recoverable": True,
            }
        )
        output = {
            "stock": {"code": stock_code, "name": stock_name, "corp_code": corp_code},
            "skipped": True,
            "skip_reason": "not_listed_or_not_found",
            "counts": {
                "evidence": 0,
                "quant_signals": 0,
                "news": 0,
                "disclosures": 0,
                "financial": 0,
                "financial_signals": 0,
                "llm_signals": 0,
                "errors": len(errors),
            },
            "score": model_dump_jsonable(combine_signals()),
            "quant_signals": [],
            "llm_signals": [],
            "financial_signals": [],
            "evidence_preview": [],
            "errors": errors,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    try:
        quant_signals = QuantEngine().get_signals(stock_code, stock_name, env_dv=args.quant_env)
    except Exception as exc:
        errors.append(
            {
                "source": "quant",
                "code": "failed",
                "message": f"Quant analysis failed: {exc}",
                "recoverable": True,
            }
        )

    news_end = datetime.now(timezone.utc)
    news_start = news_end - timedelta(days=args.news_days)
    kis_news_result = fetch_kis_news_titles(stock_code, stock_name, limit=args.kis_news_limit)
    errors.extend(kis_news_result.errors)
    kis_title_naver_result = search_naver_news_by_titles(
        [item.title for item in kis_news_result.titles],
        max_results=args.kis_news_limit,
        start_date=news_start,
        end_date=news_end,
    )
    evidence.extend(kis_title_naver_result.evidence)
    errors.extend(kis_title_naver_result.errors)

    news_query = build_stock_news_query(stock_name)
    news_result = search_naver_news(
        news_query,
        display=args.news_display,
        start_date=news_start,
        end_date=news_end,
    )
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
    score = combine_signals(
        quant_signals=quant_signals,
        ai_signals=llm_result.signals,
        financial_signals=financial_signals,
    )

    output = {
        "stock": {"code": stock_code, "name": stock_name, "corp_code": corp_code},
        "kis_authenticated": kis_authenticated,
        "score": model_dump_jsonable(score),
        "news_query": news_query,
        "news_filter": {
            "sort": "date",
            "days": args.news_days,
            "start_date": news_start.isoformat(),
            "end_date": news_end.isoformat(),
        },
        "counts": {
            "evidence": len(evidence),
            "quant_signals": len(quant_signals),
            "news": len([item for item in evidence if item.kind == "news"]),
            "kis_news": len([item for item in evidence if item.kind == "news" and item.source.startswith("KIS:")]),
            "naver_news": len([item for item in evidence if item.kind == "news" and item.source == "Naver News"]),
            "disclosures": len([item for item in evidence if item.kind == "disclosure"]),
            "financial": len([item for item in evidence if item.kind == "financial"]),
            "financial_signals": len(financial_signals),
            "llm_signals": len(llm_result.signals),
            "errors": len(errors),
        },
        "kis_news_titles": [item.title for item in kis_news_result.titles],
        "quant_signals": model_dump_jsonable(quant_signals),
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
