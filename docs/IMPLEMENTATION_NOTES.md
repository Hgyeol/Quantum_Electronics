# Implementation Notes

## PRD Coverage

- FastAPI service: implemented in `web/main.py` with `/health`, `/outlook/stock/{code}`, `/outlook/query`, and a partial `/outlook/market` skeleton.
- Outlook report schema: implemented with Pydantic models in `analysis/models.py`.
- Quant signals: existing `quant/engine.py` is wired into `services/outlook.py`; failures are converted into report errors or neutral signals by the existing quant code.
- News evidence: `news/naver_news_api.py` returns normalized `Evidence` and does not call Naver at import time.
- Disclosure evidence: `disclosure/disclosure_api.py` searches DART filings and normalizes results as `Evidence`.
- Financial analysis: `financial/metrics.py` calculates revenue, operating income, net income, operating margin, debt ratio, ROE, and revenue growth deterministically.
- LLM analysis: `llm/analyzer.py` validates JSON output into Pydantic `AISignal`, rejects unknown `evidence_id` references, and includes an optional OpenAI Responses API adapter.

## Safety Policy

- Real trading is disabled by default through policy and documentation.
- Order APIs are not imported or called from `web/`, `services/`, `analysis/`, `financial/`, `news/`, `disclosure/`, or `llm/`.
- Secrets are represented only as environment variable names and `.env.example` placeholders.
- KIS auth loads config lazily; importing modules does not create token files or read KIS secrets.

## Known Gaps

- The LLM provider client is OpenAI Responses API only; other providers can be added behind the same `StructuredLLMAnalyzer` contract.
- DART corp code lookup currently uses `disclosure/kospi.csv`; non-KOSPI or missing mappings return recoverable errors.
- Market-wide outlook is a skeleton endpoint.
- External API behavior is covered with mock tests; live API tests require local credentials and should not be committed with secrets.
