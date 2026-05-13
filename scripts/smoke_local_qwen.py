"""Smoke test for LocalQwenAnalyzer.

Loads the Qwen base model + DPO LoRA adapter and runs a single inference
against a tiny synthetic Evidence list. Used after Colab training to
verify the local stack before flipping the .env switch.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "OUTLOOK_LOCAL_LLM_ADAPTER_PATH",
    str(ROOT / "ml" / "artifacts" / "llm_dpo_v1_mlx"),
)

from analysis.models import Evidence  # noqa: E402
from llm.local_qwen_analyzer import LocalQwenAnalyzer  # noqa: E402


def main() -> int:
    print("[smoke] adapter:", os.environ["OUTLOOK_LOCAL_LLM_ADAPTER_PATH"], flush=True)
    t0 = time.perf_counter()
    analyzer = LocalQwenAnalyzer()
    print(f"[smoke] loaded in {time.perf_counter() - t0:.1f}s", flush=True)

    evidence = [
        Evidence(
            evidence_id="e1",
            kind="news",
            title="삼성전자 1분기 영업이익 컨센서스 상회",
            content="삼성전자는 1분기 영업이익이 전년 동기 대비 두 배로 증가하며 컨센서스를 상회했다고 발표했다. HBM 수요가 견조하며 메모리 반도체 가격이 회복세를 보였다.",
            source="press",
        ),
        Evidence(
            evidence_id="e2",
            kind="news",
            title="삼성전자 노조 임금 협상 난항",
            content="삼성전자 노조는 임금 인상 요구안을 두고 사측과 협상 중이며, 아직 합의에 이르지 못했다고 밝혔다.",
            source="press",
        ),
    ]

    t1 = time.perf_counter()
    result = analyzer.analyze_evidence(evidence)
    print(f"[smoke] inference in {time.perf_counter() - t1:.1f}s", flush=True)

    if result.errors:
        print("[smoke] errors:")
        for err in result.errors:
            print(f"  - {err.source} / {err.code}: {err.message}")
        return 1

    for signal in result.signals:
        print("[smoke] signal:")
        print(f"  label:        {signal.label}")
        print(f"  direction:    {signal.direction}")
        print(f"  score:        {signal.score}")
        print(f"  confidence:   {signal.confidence}")
        print(f"  evidence_ids: {signal.evidence_ids}")
        print(f"  summary:      {signal.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
