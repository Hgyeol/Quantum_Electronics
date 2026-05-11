# Quantum Electronics

Quantum Electronics is a FastAPI-based investment outlook service for Korean stocks. The target workflow is to combine deterministic quant and financial signals with structured LLM interpretation of news, disclosures, and financial evidence.

The service is analysis-only. Real trading and order APIs are not part of the default execution path and must remain disabled unless explicitly implemented behind a separate safety gate.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Create local environment values from `.env.example`. Do not commit real API keys, account numbers, access tokens, or KIS YAML files.

```bash
export KIS_CONFIG_FILE=/absolute/path/to/kis_devlp.yaml
export DISCLOSURE_CRTFC_KEY=
export NAVER_NEWS_API_CLIENT=
export NAVER_NEWS_API_SECRET=
export OPENAI_API_KEY=
export OPENAI_MODEL=gpt-5.2
export ENABLE_REAL_TRADING=false
```

KIS configuration is loaded lazily. Importing project modules does not create token files or read `~/KIS/config/kis_devlp.yaml`; actual KIS calls require `KIS_CONFIG_FILE` or the default KIS config path.

## Verification

```bash
python -c "import quant.models"
python -c "import quant.engine"
python -m py_compile kis_auth.py quant/models.py quant/engine.py quant/signals/foreign_investor.py web/main.py
pytest
```

If external API credentials are absent, collectors and analyzers should return partial results with error information instead of crashing the API process.

## Run API

```bash
uvicorn web.main:app --reload
```

Useful endpoints:

- `GET /health`: service liveness.
- `GET /outlook/stock/{code}?stock_name=...`: build an `OutlookReport` for a stock code.
- `POST /outlook/query`: JSON body `{"query": "005930", "stock_name": "삼성전자"}`.
- `GET /outlook/market`: partial skeleton for future market-wide reports.

Example:

```bash
curl "http://127.0.0.1:8000/outlook/stock/005930?stock_name=%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90"
```

Without KIS, DART, Naver, or LLM credentials, the API still returns a structured report with neutral/partial signals and recoverable error entries.

Stock-name lookup uses the root `kospi.csv` stock master when present. DART disclosure/financial collection still needs a `corp_code`, which is resolved from `disclosure/kospi.csv`; if that mapping is missing, the service returns a recoverable DART mapping error.

## Project Structure

- `analysis/`: Pydantic report, signal, evidence, error, and scoring models.
- `financial/`: deterministic pandas-based financial metric and financial signal analysis.
- `kis_auth.py`: KIS authentication and request helpers, now import-safe and lazily configured.
- `llm/`: structured LLM evidence analyzer with disabled and injectable-client modes.
- `quant/`: deterministic quant signal models and engine.
- `services/`: application orchestration for `OutlookReport`.
- `tools/`: KIS sample API modules and strategy helpers used by quant signals.
- `disclosure/`: DART disclosure and financial statement helpers.
- `news/`: news API and crawler modules.
- `web/`: FastAPI application entry point.

## Safety Constraints

- Never commit API keys, KIS tokens, account numbers, or provider secrets.
- Keep real trading disabled by default with `ENABLE_REAL_TRADING=false`.
- Do not connect order APIs to the outlook report flow.
- Use LLMs only for text interpretation and report drafting.
- Keep financial ratios, scoring, and numeric comparisons deterministic in code.
- Validate structured LLM output with Pydantic models.

## Current Implementation Notes

- Real order modules under `tools/` are not connected to FastAPI routes or outlook orchestration.
- `llm/` uses disabled analysis by default and switches to an OpenAI Responses API analyzer when `OPENAI_API_KEY` is configured.
- DART disclosure and financial collection only call external APIs when keys are configured.
- KIS-backed quant signals degrade to neutral/error paths when KIS auth is not initialized.
