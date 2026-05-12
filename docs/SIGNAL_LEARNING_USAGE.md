# Signal Learning Usage

This workflow implements the first practical steps from `PRD_신호학습_백테스트.md`.

## 1. Build Feature CSV

If you already have saved `OutlookReport` JSONL records:

```bash
python scripts/build_signal_features.py \
  --reports data/outlook_reports.jsonl \
  --output data/features.csv
```

Each JSONL line should be one `OutlookReport` object. You may include an `as_of_date` field to force the feature row date.

## 2. Build Labeled Dataset

Prepare a price CSV with:

```text
date,stock_code,close
```

Then build next-day labels:

```bash
python scripts/build_ml_dataset.py \
  --features data/features.csv \
  --prices data/prices.csv \
  --output data/ml_dataset.csv
```

The output adds:

```text
close,next_close,next_day_return,target_up
```

## 3. Evaluate Baselines

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

## 4. Train Logistic Regression

```bash
python scripts/train_outlook_model.py \
  --dataset data/ml_dataset.csv \
  --output ml/artifacts/outlook_logistic_v1.json
```

The script uses chronological train/validation/test splits and prints baseline-vs-model metrics.

## 5. Use Model in FastAPI

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

## 6. Cache LLM Signals

Historical feature generation can call the same evidence repeatedly. Enable a
file-backed LLM cache to avoid repeated provider calls for identical evidence:

```bash
export OUTLOOK_LLM_CACHE_PATH=/absolute/path/to/runtime/llm_cache.json
```

The cache key is based on normalized evidence content, so identical evidence
sets reuse the same structured LLM signal.
