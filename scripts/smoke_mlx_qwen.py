"""Smoke test for MLX-LM + DPO LoRA adapter (Apple Silicon path).

Loads `mlx-community/Qwen2.5-3B-Instruct-4bit` (~1.8 GB on disk, fits in
8 GB RAM) and applies the converted MLX LoRA adapter at
`ml/artifacts/llm_dpo_v1_mlx/`. Runs one inference against a tiny
synthetic Evidence list. Used to validate the local stack before
flipping `.env`.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlx_lm import generate, load  # noqa: E402

MODEL_REPO = os.getenv("OUTLOOK_MLX_BASE", "mlx-community/Qwen2.5-3B-Instruct-4bit")
ADAPTER_PATH = os.getenv(
    "OUTLOOK_MLX_ADAPTER_PATH",
    str(ROOT / "ml" / "artifacts" / "llm_dpo_v1_mlx"),
)


def main() -> int:
    print(f"[smoke] base: {MODEL_REPO}", flush=True)
    print(f"[smoke] adapter: {ADAPTER_PATH}", flush=True)

    t0 = time.perf_counter()
    model, tokenizer = load(MODEL_REPO, adapter_path=ADAPTER_PATH)
    print(f"[smoke] loaded in {time.perf_counter() - t0:.1f}s", flush=True)

    messages = [
        {
            "role": "user",
            "content": (
                "다음 evidence만 근거로 한국어로 한 문장 요약하라.\n\n"
                "evidence: 삼성전자 1분기 영업이익 컨센서스 상회. HBM 수요 견조."
            ),
        }
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )

    t1 = time.perf_counter()
    text = generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=128,
        verbose=False,
    )
    dt = time.perf_counter() - t1
    print(f"[smoke] generated in {dt:.1f}s", flush=True)
    print("[smoke] output:")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
