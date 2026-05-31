# Quantum Electronics

Quantum Electronics is a FastAPI-based investment outlook service for Korean stocks. It combines four signal axes — deterministic quant signals, OpenAI GPT-based news/disclosure analysis, Logistic Regression ML prediction, and DART-sourced financial metrics — into a single `OutlookReport` that shows not just a verdict but the evidence behind it.

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
- `GET /outlook/stock/{code}`: build an `OutlookReport` for a stock code.

Example:

```bash
curl "http://127.0.0.1:8000/outlook/stock/005930"
```

Without KIS, DART, Naver, or LLM credentials, the API still returns a structured report with neutral/partial signals and recoverable error entries.

Stock-name lookup uses the root `kospi.csv` stock master when present. DART disclosure/financial collection still needs a `corp_code`, which is resolved from `disclosure/kospi.csv`; if that mapping is missing, the service returns a recoverable DART mapping error.

News collection searches by exact stock name plus Naver search operators, for example `"삼성전자" +경제 | +증권 | +금융 | +실적`, requests Naver results in latest-first order, and keeps only recent items. The manual LLM check script defaults to the last 7 days and can be adjusted with `--news-days`.

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
- `ml/`: feature schema, dataset/label builders, training, runtime predictor, and `historical.py` for PRD Phase-2 backfill.

## Signal Learning Pipeline (PRD §2)

`PRD_신호학습_백테스트.md` defines a four-phase pipeline that turns the daily
outlook signals into a supervised next-day prediction. Current status:

| Phase | Status | Artifact |
|-------|--------|----------|
| 1. Dataset + baseline | ✅ | `ml/artifacts/signal_learning_v1/ml_dataset.csv`, `baseline_metrics.json` |
| 2. Historical feature generator | ✅ (quant + DART + LLM; news skipped) | `ml/historical.py`, `scripts/backfill_signal_features.py` |
| 3. Logistic Regression learning | ✅ | `outlook_logistic_v1.json`, `outlook_logistic_v1.metrics.json` |
| 4. FastAPI integration | ✅ via `OUTLOOK_ML_MODEL_PATH` | `web.main:/outlook/stock/{code}` includes `ml_prediction` |
| 5. RL/DPO | deferred per PRD §6.3, §9 | — |

Known constraints vs PRD §10.1:

- Backfilled to **3 stocks × 154 calendar days** (PRD §10.1 minimum: ≥3
  stocks × ≥90 days). Adding more stocks requires re-running the backfill
  script.
- News evidence is intentionally empty for historical rows because Naver
  Search has no date filter; daily live collection keeps populating real
  news going forward.
- `foreign_investor_score` is filled in by a separate post-15:40-KST refresh
  (`scripts/refresh_foreign_investor.py`) because the KIS daily-investor
  endpoint is rate-gated to after market close.

### Re-running the backfill / refresh

```bash
# One-off historical backfill (3 stocks × all dates in data/prices.csv)
python scripts/backfill_signal_features.py --kis-auth

# After 15:40 KST, fill in foreign-investor scores on already-backfilled rows
python scripts/refresh_foreign_investor.py

# Rebuild dataset + baseline + model artifacts
python scripts/run_signal_learning_workflow.py \
    --features data/features.csv --prices data/prices.csv \
    --output-dir ml/artifacts/signal_learning_v1 \
    --min-calendar-days 90 --min-stocks 3 --min-selected-stock-count 3
```

The OpenAI Responses analyzer is wrapped by `CachedLLMAnalyzer`; set
`OUTLOOK_LLM_CACHE_PATH=data/llm_cache.json` so both live collection and
historical backfill share the same on-disk cache.

## LLM Preference Learning (PRD_LLM_선호학습.md)

> **Status**: experimental pipeline, not active in production. The service defaults to OpenAI.

`scripts/build_dpo_pairs.py` derives DPO training triples from the existing
dataset: any (date, stock) row where the LLM judgment direction did not
match the realized `next_day_return` becomes one `(prompt, chosen, rejected)`
pair. The prompt is rebuilt with the same `build_evidence_prompt()` used at
inference, so a Colab-trained LoRA adapter sees identical text in training
and serving.

```bash
python scripts/build_dpo_pairs.py \
    --dataset ml/artifacts/signal_learning_v1/ml_dataset.csv \
    --reports data/outlook_reports.jsonl \
    --output data/dpo_pairs.jsonl
```

Training runs on Colab (`notebooks/dpo_qwen_colab.ipynb`, free T4) against
`Qwen/Qwen2.5-3B-Instruct` + LoRA. After download, point
`OUTLOOK_LOCAL_LLM_ADAPTER_PATH=/path/to/adapter` and the outlook service
swaps `OpenAIResponsesAnalyzer` for the locally-loaded Qwen adapter. The
swap is fail-soft: any load/import failure logs a warning and the service
falls back to OpenAI.

## Frontend

A Next.js (App Router) visualization lives at `/Users/gimhangyeol/졸작_프론트`
(separate git repo). It renders the FastAPI response — score breakdown,
quant/AI/financial signals, ML prediction, position context, evidence — in
a Binance-inspired dark theme. Run it alongside the backend:

```bash
# Terminal 1 — backend
uvicorn web.main:app --reload

# Terminal 2 — frontend
cd /Users/gimhangyeol/졸작_프론트
npm run dev    # webpack mode (Turbopack panics on non-ASCII paths)
# → http://localhost:3000
```

The backend now sets `Access-Control-Allow-Origin` for
`http://localhost:3000` and `http://127.0.0.1:3000` by default; override with
the `OUTLOOK_CORS_ORIGINS` env var (comma-separated).

## Decision-Support (PRD_의사결정보조.md)

`/outlook/stock/{code}` accepts three optional query parameters
(`avg_price`, `quantity`, `held_since`) for a user-held position. When all
three are supplied, the response includes a `position_context` block with
deterministic facts only (unrealized PnL, breakeven %, 52-week distances).
Every response carries a fixed disclaimer making clear the block is *not*
a buy/sell recommendation. See `PRD_의사결정보조.md` §4 for the phased plan
covering scenario fields, comparison API, and supply-flow refinement.

```bash
curl "http://127.0.0.1:8000/outlook/stock/005930?avg_price=80000&quantity=10&held_since=2024-01-15"
```

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
