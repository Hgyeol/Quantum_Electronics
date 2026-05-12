# Signal Learning Usage

This workflow implements the first practical steps from `PRD_신호학습_백테스트.md`.

## 1. Collect Daily Features

The simplest daily collection command is:

```bash
python scripts/collect_daily_signal_learning_inputs.py \
  --kis-auth \
  --stock-limit 5 \
  --run-workflow-if-ready
```

This exports `data/stock_codes.csv` from the root `kospi.csv`, refreshes
`data/prices.csv`, and appends today's reports/features to
`data/outlook_reports.jsonl` and `data/features.csv`. The command also prints a
`readiness` summary showing whether the collected features already have a next
trading-day price available for label generation, plus progress toward the PRD
minimum of 90 calendar days and 5 stocks, including the target calendar end
date for the 90-day gate. With `--run-workflow-if-ready`, it
also starts the dataset/model workflow automatically once labels can be built.

Run this once per trading day for the stocks you want to track:

```bash
python scripts/collect_signal_features.py 005930 000660 \
  --as-of-date 2026-05-12 \
  --reports-jsonl data/outlook_reports.jsonl \
  --features-csv data/features.csv
```

You can also pass a stock-code file:

```bash
python scripts/export_stock_universe.py \
  --output data/stock_codes.csv \
  --limit 5

python scripts/collect_signal_features.py \
  --codes-file data/stock_codes.csv \
  --kis-auth \
  --reports-jsonl data/outlook_reports.jsonl \
  --features-csv data/features.csv
```

`export_stock_universe.py` reads the root `kospi.csv` by default and writes
`stock_code,stock_name,market` rows for collectors.
If the cached KIS token is stale, add `--force-kis-token` with `--kis-auth` to
delete the cached token file before authentication.

`reports-jsonl` is append-only. `features-csv` is deduplicated by
`date,stock_code`, so rerunning the same date overwrites that day's feature row.
The daily collector uses `skip_existing_reports` internally so rerunning it on
the same date does not duplicate raw report JSONL rows.
The collector uses current live data, so it rejects non-today `--as-of-date`
unless `--allow-date-override` is explicitly set for controlled replays of
already time-correct reports.

## 2. Build Feature CSV From Existing Reports

If you already have saved `OutlookReport` JSONL records:

```bash
python scripts/build_signal_features.py \
  --reports data/outlook_reports.jsonl \
  --output data/features.csv \
  --start-date 2026-02-01 \
  --end-date 2026-05-12
```

Each JSONL line should be one `OutlookReport` object. You may include an `as_of_date` field to force the feature row date.
By default, evidence with `published_at` after that row's `as_of_date` is
excluded before feature counts are computed. Same-day evidence after the
default `15:30` Asia/Seoul market close cutoff is also excluded unless
`--keep-after-market-close` is set. This keeps replayed report archives from
leaking future or after-close news/disclosures into earlier rows.

## 3. Build Labeled Dataset

Collect a price CSV with:

```bash
python scripts/collect_price_history.py 005930 000660 \
  --kis-auth \
  --days 120 \
  --output data/prices.csv
```

Or collect for a stock-code file:

```bash
python scripts/collect_price_history.py \
  --codes-file data/stock_codes.csv \
  --kis-auth \
  --days 120 \
  --output data/prices.csv
```

Use `--force-kis-token` here as well when KIS needs a fresh token.

Then build next-day labels:

```bash
python scripts/check_signal_learning_inputs.py \
  --features data/features.csv \
  --prices data/prices.csv

python scripts/build_ml_dataset.py \
  --features data/features.csv \
  --prices data/prices.csv \
  --output data/ml_dataset.csv
```

The output adds:

```text
close,next_close,next_day_return,target_up
```

## 4. Evaluate Baselines

Before evaluation, verify that the dataset is large enough for the PRD gate:

```bash
python scripts/verify_ml_dataset.py --dataset data/ml_dataset.csv
```

By default this requires at least 90 calendar days and 5 stocks. For smoke tests,
you can lower the thresholds:

```bash
python scripts/verify_ml_dataset.py \
  --dataset data/ml_dataset.csv \
  --min-calendar-days 1 \
  --min-stocks 1
```

```bash
python scripts/evaluate_ml_dataset.py --dataset data/ml_dataset.csv
```

This evaluates:

- always-up baseline
- `total_rule_score > 0`
- `quant_score > 0`
- `ai_score > 0`

Metrics include accuracy, precision, recall, ROC-AUC, win rate, trade count, turnover, mean selected return, cumulative return, and max drawdown.

## 5. Train Logistic Regression

```bash
python scripts/train_outlook_model.py \
  --dataset data/ml_dataset.csv \
  --output ml/artifacts/outlook_logistic_v1.json \
  --metrics-output ml/artifacts/outlook_logistic_v1.metrics.json \
  --min-trade-count 5 \
  --min-selected-stock-count 2
```

The script uses chronological train/validation/test splits, prints
baseline-vs-model metrics, and includes a `success_gate` that passes when the
model improves precision or mean selected return over `total_rule_score > 0`
while still making enough trades across more than one selected stock. It also
prints `coefficient_importance`, sorted by absolute logistic-regression
coefficient, so you can inspect which signals influenced the first model most.

## 6. Run The Whole Dataset Workflow

Once `features.csv` and `prices.csv` exist, you can run the build, PRD
verification, baseline evaluation, and model training steps together:

```bash
python scripts/run_signal_learning_workflow.py \
  --features data/features.csv \
  --prices data/prices.csv \
  --output-dir ml/artifacts/signal_learning_v1
```

The workflow writes:

- `ml_dataset.csv`
- `verification.json`
- `baseline_metrics.json`
- `outlook_logistic_v1.json`
- `outlook_logistic_v1.metrics.json`
- `workflow_summary.json`

It exits non-zero if the dataset fails the default PRD readiness gate of 90
calendar days and 5 stocks. If the raw features/prices cannot produce any
next-day labels yet, the workflow stops at `input_readiness` before writing an
empty `ml_dataset.csv`.

You can audit the current local artifacts against the PRD gates at any time:

```bash
python scripts/audit_signal_learning_prd.py
```

This command is intentionally strict: missing data, failed 90-day/5-stock
verification, missing model artifacts, or failed validation/test success gates
make the audit fail. It also checks `data/features.csv` and `data/prices.csv`
first so missing next-day prices are visible before model training starts.

## 7. Use Model in FastAPI

Set:

```bash
export OUTLOOK_ML_MODEL_PATH=/absolute/path/to/ml/artifacts/outlook_logistic_v1.json
export OUTLOOK_ML_MODEL_NAME=logistic_regression_v1
export OUTLOOK_ML_FEATURES_VERSION=v1
```

Then run:

```bash
python -m uvicorn web.main:app --host 127.0.0.1 --port 8000
```

`GET /outlook/stock/{code}` will include `ml_prediction` when the model can be loaded.
The prediction includes the next-day-up probability, model and feature
versions, the current rule score/direction, a short rule-vs-ML explanation, and
the top feature contributions that increased or decreased the model logit.

## 8. Cache LLM Signals

Historical feature generation can call the same evidence repeatedly. Enable a
file-backed LLM cache to avoid repeated provider calls for identical evidence:

```bash
export OUTLOOK_LLM_CACHE_PATH=/absolute/path/to/runtime/llm_cache.json
```

The cache key is based on normalized evidence content, so identical evidence
sets reuse the same structured LLM signal.
