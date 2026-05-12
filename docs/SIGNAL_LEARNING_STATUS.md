# Signal Learning PRD Status

This document tracks concrete progress against `PRD_신호학습_백테스트.md`.

## Current Data Status

Last checked with:

```bash
python scripts/check_signal_learning_inputs.py
python scripts/audit_signal_learning_prd.py
```

Current local inputs:

- Feature rows: 5
- Feature stocks: 5
- Feature dates: 1 calendar day, `2026-05-12`
- Price rows: 500
- Price stocks: 5
- Price range: `2025-12-11` to `2026-05-12`
- Labelable feature rows: 0
- PRD remaining calendar days: 89
- PRD remaining stocks: 0

The current blocker is not code execution. The blocker is data availability:
the collected `2026-05-12` feature rows do not yet have a next trading-day price.

## Requirement Checklist

| PRD requirement | Status | Evidence |
| --- | --- | --- |
| Feature CSV input | Implemented | `scripts/collect_signal_features.py`, `scripts/build_signal_features.py` |
| Price CSV input | Implemented | `scripts/collect_price_history.py` |
| Next-day labels | Implemented | `ml/dataset.py`, `scripts/build_ml_dataset.py` |
| Duplicate `(date, stock_code)` rejection | Implemented | `ml/dataset.py`, tests |
| Baseline evaluation | Implemented | `ml/evaluation.py`, `scripts/evaluate_ml_dataset.py` |
| Logistic Regression training | Implemented | `ml/training.py`, `scripts/train_outlook_model.py` |
| Time-ordered split | Implemented | date-level `split_by_time` in `ml/evaluation.py` |
| Backtest metrics | Implemented | accuracy, precision, recall, ROC-AUC, win rate, turnover, return, drawdown |
| LLM cache | Implemented | `llm/cache.py`, `OUTLOOK_LLM_CACHE_PATH` |
| FastAPI ML prediction hook | Implemented | `ml/runtime.py`, `analysis/models.py`, `services/outlook.py` |
| Model explanation | Implemented | `ml_prediction.explanation`, `top_contributions` |
| Daily data collection | Implemented | `scripts/collect_daily_signal_learning_inputs.py` |
| Workflow runner | Implemented | `scripts/run_signal_learning_workflow.py` |
| PRD audit | Implemented | `scripts/audit_signal_learning_prd.py` |
| 3 months actual feature dataset | Not complete | current feature calendar days: 1 |
| 5+ stocks actual dataset | Data input met | current feature stock count: 5 |
| Validation/test model success gate | Not complete | requires labeled dataset and model metrics |

## Daily Command

Run once per trading day:

```bash
python scripts/collect_daily_signal_learning_inputs.py \
  --kis-auth \
  --stock-limit 5
```

If KIS requires a fresh token:

```bash
python scripts/collect_daily_signal_learning_inputs.py \
  --kis-auth \
  --force-kis-token \
  --stock-limit 5
```

Then check readiness:

```bash
python scripts/check_signal_learning_inputs.py
```

When labelable rows exist and enough history has accumulated, run:

```bash
python scripts/run_signal_learning_workflow.py \
  --features data/features.csv \
  --prices data/prices.csv \
  --output-dir ml/artifacts/signal_learning_v1

python scripts/audit_signal_learning_prd.py
```
