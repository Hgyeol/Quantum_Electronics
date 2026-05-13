"""Build DPO training pairs from the existing outlook dataset.

Pairs are emitted only for rows where the LLM judgment direction did not
match the realized next-day return direction (PRD_LLM_선호학습.md §4.1).
The prompt is reconstructed via `build_evidence_prompt` so the Colab DPO
trainer sees exactly the same text as production inference.

Output JSONL columns are aligned with `trl.DPOTrainer`:

    {"prompt": str, "chosen": str, "rejected": str, "metadata": {...}}
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analysis.models import Evidence
from llm.analyzer import build_evidence_prompt, filter_llm_evidence

logger = logging.getLogger(__name__)

NEUTRAL_RETURN_THRESHOLD = 0.005  # |next_day_return| < ε → neutral

_POSITIVE_SUMMARIES = (
    "evidence 점검 결과 다음 거래일은 상승 방향으로 정렬되는 신호가 우세함.",
    "공시·재무 evidence에서 우호적 흐름이 우세해 다음 거래일 상승 정렬이 합당함.",
    "evidence 묶음의 핵심 신호가 다음 거래일 상승 방향에 정렬됨.",
    "evidence가 가리키는 다음 거래일 방향성은 상승 쪽으로 더 무게가 실림.",
)
_NEGATIVE_SUMMARIES = (
    "evidence 점검 결과 다음 거래일은 하락 방향으로 정렬되는 신호가 우세함.",
    "공시·재무 evidence에서 부정 흐름이 우세해 다음 거래일 하락 정렬이 합당함.",
    "evidence 묶음의 핵심 신호가 다음 거래일 하락 방향에 정렬됨.",
    "evidence가 가리키는 다음 거래일 방향성은 하락 쪽으로 더 무게가 실림.",
)
_NEUTRAL_SUMMARIES = (
    "evidence가 상승·하락 양쪽 근거를 모두 포함하고 있어 다음 거래일 방향성은 중립으로 정렬됨.",
    "evidence 강도가 약해 다음 거래일은 방향성 단정이 어렵고 중립으로 정렬하는 것이 합당함.",
)


def _label_for_direction(direction: str) -> str:
    if direction == "positive":
        return "다음 거래일 상승 방향성 정렬"
    if direction == "negative":
        return "다음 거래일 하락 방향성 정렬"
    return "다음 거래일 방향성 정렬 어려움"


def _score_for_direction(direction: str) -> int:
    return {"positive": 2, "negative": -2, "neutral": 0}[direction]


def _summary_for_direction(direction: str, rng: random.Random) -> str:
    if direction == "positive":
        return rng.choice(_POSITIVE_SUMMARIES)
    if direction == "negative":
        return rng.choice(_NEGATIVE_SUMMARIES)
    return rng.choice(_NEUTRAL_SUMMARIES)


def realized_direction(next_day_return: float, neutral_eps: float = NEUTRAL_RETURN_THRESHOLD) -> str:
    if next_day_return is None:
        return "neutral"
    if next_day_return > neutral_eps:
        return "positive"
    if next_day_return < -neutral_eps:
        return "negative"
    return "neutral"


def synthesize_chosen_response(
    target_direction: str,
    evidence_ids: list[str],
    rng: random.Random,
) -> dict[str, Any]:
    return {
        "label": _label_for_direction(target_direction),
        "direction": target_direction,
        "score": _score_for_direction(target_direction),
        "summary": _summary_for_direction(target_direction, rng),
        "evidence_ids": list(evidence_ids),
        "confidence": 0.5,
    }


def _evidence_from_report(report: dict[str, Any]) -> list[Evidence]:
    raw_evidence = report.get("evidence") or []
    return [Evidence.model_validate(item) for item in raw_evidence]


def _ai_signal_payload(report: dict[str, Any]) -> dict[str, Any] | None:
    signals = report.get("ai_signals") or []
    if not signals:
        return None
    primary = signals[0]
    return {
        "label": primary.get("label"),
        "direction": primary.get("direction"),
        "score": primary.get("score"),
        "summary": primary.get("summary"),
        "evidence_ids": primary.get("evidence_ids") or [],
        "confidence": primary.get("confidence", 0.0),
    }


def load_reports(reports_jsonl: Path) -> dict[tuple[str, str], dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_line in reports_jsonl.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        as_of = str(payload.get("as_of_date") or "")
        code = str(payload.get("stock_code") or "").strip()
        if as_of and code:
            by_key[(as_of, code)] = payload
    return by_key


def build_pairs(
    dataset_csv: Path,
    reports_jsonl: Path,
    output_jsonl: Path,
    neutral_eps: float = NEUTRAL_RETURN_THRESHOLD,
    seed: int = 0,
) -> dict[str, Any]:
    dataset = pd.read_csv(dataset_csv, dtype={"stock_code": str, "date": str})
    reports = load_reports(reports_jsonl)
    rng = random.Random(seed)

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "input_rows": int(len(dataset)),
        "reports": len(reports),
        "pairs": 0,
        "skipped_no_report": 0,
        "skipped_aligned": 0,
        "skipped_no_evidence": 0,
        "skipped_no_ai_signal": 0,
    }

    with output_jsonl.open("w", encoding="utf-8") as out:
        for _, row in dataset.iterrows():
            key = (str(row["date"]), str(row["stock_code"]))
            report = reports.get(key)
            if report is None:
                summary["skipped_no_report"] += 1
                continue

            evidence_list = _evidence_from_report(report)
            llm_evidence = filter_llm_evidence(evidence_list)
            if not llm_evidence:
                summary["skipped_no_evidence"] += 1
                continue

            rejected_signal = _ai_signal_payload(report)
            if rejected_signal is None:
                summary["skipped_no_ai_signal"] += 1
                continue

            actual_direction = realized_direction(
                float(row.get("next_day_return")) if pd.notna(row.get("next_day_return")) else 0.0,
                neutral_eps=neutral_eps,
            )
            llm_direction = str(rejected_signal.get("direction", "neutral"))
            if llm_direction == actual_direction:
                summary["skipped_aligned"] += 1
                continue

            allowed_ids = [item.evidence_id for item in llm_evidence]
            chosen_evidence_ids = [
                evidence_id
                for evidence_id in (rejected_signal.get("evidence_ids") or allowed_ids)
                if evidence_id in set(allowed_ids)
            ] or allowed_ids[: min(len(allowed_ids), 5)]

            chosen_signal = synthesize_chosen_response(actual_direction, chosen_evidence_ids, rng)
            prompt = build_evidence_prompt(llm_evidence)
            pair = {
                "prompt": prompt,
                "chosen": json.dumps(chosen_signal, ensure_ascii=False),
                "rejected": json.dumps(rejected_signal, ensure_ascii=False),
                "metadata": {
                    "date": key[0],
                    "stock_code": key[1],
                    "llm_direction": llm_direction,
                    "actual_direction": actual_direction,
                    "next_day_return": float(row.get("next_day_return"))
                    if pd.notna(row.get("next_day_return"))
                    else None,
                    "generated_at": datetime.utcnow().isoformat() + "Z",
                },
            }
            out.write(json.dumps(pair, ensure_ascii=False) + "\n")
            summary["pairs"] += 1

    return summary


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build DPO training pairs from outlook dataset")
    parser.add_argument(
        "--dataset",
        default="ml/artifacts/signal_learning_v1/ml_dataset.csv",
        help="Labeled dataset CSV with next_day_return column",
    )
    parser.add_argument(
        "--reports",
        default="data/outlook_reports.jsonl",
        help="JSONL of OutlookReport payloads (one per (date, stock))",
    )
    parser.add_argument(
        "--output",
        default="data/dpo_pairs.jsonl",
        help="Output JSONL of DPO training pairs",
    )
    parser.add_argument("--neutral-eps", type=float, default=NEUTRAL_RETURN_THRESHOLD)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    summary = build_pairs(
        dataset_csv=Path(args.dataset),
        reports_jsonl=Path(args.reports),
        output_jsonl=Path(args.output),
        neutral_eps=args.neutral_eps,
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
