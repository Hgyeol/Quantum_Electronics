"""Audit local artifacts against PRD_신호학습_백테스트.md success criteria."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.verification import verify_labeled_dataset
from scripts.check_signal_learning_inputs import check_signal_learning_inputs


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _check(name: str, ok: bool, evidence: str, details: dict | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "evidence": evidence,
        "details": details or {},
    }


def _dataset_check(dataset_path: Path, min_calendar_days: int, min_stocks: int) -> dict[str, Any]:
    if not dataset_path.exists():
        return _check(
            "technical.dataset_ready",
            False,
            f"Dataset file not found: {dataset_path}",
        )
    dataset = pd.read_csv(dataset_path, dtype={"stock_code": str})
    verification = verify_labeled_dataset(
        dataset,
        min_calendar_days=min_calendar_days,
        min_stocks=min_stocks,
    )
    return _check(
        "technical.dataset_ready",
        verification.ok,
        f"Verified {dataset_path}",
        verification.to_dict(),
    )


def _input_readiness_check(
    features_path: Path,
    prices_path: Path,
    min_calendar_days: int,
    min_stocks: int,
) -> dict[str, Any]:
    result = check_signal_learning_inputs(
        features_path,
        prices_path,
        min_calendar_days=min_calendar_days,
        min_stocks=min_stocks,
    )
    return _check(
        "technical.input_readiness",
        bool(result.get("ok")),
        f"Checked features={features_path}, prices={prices_path}",
        result,
    )


def _workflow_output_checks(workflow_dir: Path) -> list[dict[str, Any]]:
    expected_files = {
        "technical.labeled_dataset_output": workflow_dir / "ml_dataset.csv",
        "technical.verification_output": workflow_dir / "verification.json",
        "phase1.baseline_metrics_output": workflow_dir / "baseline_metrics.json",
        "phase3.model_artifact_output": workflow_dir / "outlook_logistic_v1.json",
        "phase3.model_metrics_output": workflow_dir / "outlook_logistic_v1.metrics.json",
        "workflow.summary_output": workflow_dir / "workflow_summary.json",
    }
    return [
        _check(name, path.exists(), str(path))
        for name, path in expected_files.items()
    ]


def _model_success_check(metrics_path: Path) -> dict[str, Any]:
    metrics = _load_json(metrics_path)
    if metrics is None:
        return _check("model.success_gate", False, f"Model metrics not found: {metrics_path}")
    validation_gate = metrics.get("validation", {}).get("success_gate", {})
    test_gate = metrics.get("test", {}).get("success_gate", {})
    ok = bool(validation_gate.get("passes")) and bool(test_gate.get("passes"))
    return _check(
        "model.success_gate",
        ok,
        f"Read {metrics_path}",
        {
            "validation_success_gate": validation_gate,
            "test_success_gate": test_gate,
        },
    )


def _service_contract_check(model_path: Path) -> dict[str, Any]:
    model = _load_json(model_path)
    if model is None:
        return _check("service.model_version_traceable", False, f"Model artifact not found: {model_path}")
    ok = model.get("model_type") == "logistic_regression" and bool(model.get("feature_columns"))
    return _check(
        "service.model_version_traceable",
        ok,
        f"Read {model_path}",
        {
            "model_type": model.get("model_type"),
            "feature_count": len(model.get("feature_columns", [])),
        },
    )


def _llm_cache_check() -> dict[str, Any]:
    cache_path = Path("llm/cache.py")
    service_path = Path("services/outlook.py")
    cache_source = cache_path.read_text(encoding="utf-8") if cache_path.exists() else ""
    service_source = service_path.read_text(encoding="utf-8") if service_path.exists() else ""
    ok = (
        "CachedLLMAnalyzer" in cache_source
        and "cache_key_for_evidence" in cache_source
        and "OUTLOOK_LLM_CACHE_PATH" in service_source
        and "CachedLLMAnalyzer" in service_source
    )
    return _check(
        "technical.llm_cache_available",
        ok,
        "Checked llm/cache.py and services/outlook.py",
        {
            "cache_module": str(cache_path),
            "service_module": str(service_path),
            "env_var": "OUTLOOK_LLM_CACHE_PATH",
        },
    )


def audit_signal_learning_prd(
    dataset_path: Path,
    workflow_dir: Path,
    features_path: Path = Path("data/features.csv"),
    prices_path: Path = Path("data/prices.csv"),
    min_calendar_days: int = 90,
    min_stocks: int = 5,
) -> dict[str, Any]:
    checks = [
        _input_readiness_check(features_path, prices_path, min_calendar_days, min_stocks),
        _dataset_check(dataset_path, min_calendar_days, min_stocks),
        *_workflow_output_checks(workflow_dir),
        _llm_cache_check(),
        _model_success_check(workflow_dir / "outlook_logistic_v1.metrics.json"),
        _service_contract_check(workflow_dir / "outlook_logistic_v1.json"),
    ]
    ok = all(item["ok"] for item in checks)
    return {
        "ok": ok,
        "objective": "PRD_신호학습_백테스트.md",
        "checks": checks,
        "missing_or_failed": [item for item in checks if not item["ok"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit signal-learning PRD artifacts")
    parser.add_argument(
        "--dataset",
        default="ml/artifacts/signal_learning_v1/ml_dataset.csv",
        help="Labeled dataset CSV to verify",
    )
    parser.add_argument(
        "--workflow-dir",
        default="ml/artifacts/signal_learning_v1",
        help="Workflow output directory from scripts/run_signal_learning_workflow.py",
    )
    parser.add_argument("--features", default="data/features.csv", help="Raw feature CSV")
    parser.add_argument("--prices", default="data/prices.csv", help="Raw price CSV")
    parser.add_argument("--min-calendar-days", type=int, default=90)
    parser.add_argument("--min-stocks", type=int, default=5)
    args = parser.parse_args()

    result = audit_signal_learning_prd(
        dataset_path=Path(args.dataset),
        workflow_dir=Path(args.workflow_dir),
        features_path=Path(args.features),
        prices_path=Path(args.prices),
        min_calendar_days=args.min_calendar_days,
        min_stocks=args.min_stocks,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
