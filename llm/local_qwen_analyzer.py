"""Local Qwen + LoRA inference adapter for the outlook LLM signal.

Runs on Apple Silicon via MLX-LM with a 4-bit Qwen2.5-3B-Instruct base
plus the DPO LoRA adapter produced by `notebooks/dpo_qwen_colab.ipynb`
and converted with `scripts/convert_peft_to_mlx_adapter.py`. The
implementation re-uses the `EvidenceAnalyzer` protocol so it slots into
`OutlookService` without further changes.

Heavy ML dependencies (`mlx`, `mlx_lm`) are imported lazily so the rest
of the project keeps importing on machines without them. Construction
failures degrade to a documented exception that the caller catches and
falls back to the OpenAI analyzer.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from analysis.models import AISignal, AnalysisError, Evidence
from llm.analyzer import build_evidence_prompt, filter_llm_evidence

logger = logging.getLogger(__name__)


class LocalQwenAdapterUnavailable(RuntimeError):
    """Raised when the local Qwen + LoRA stack cannot be initialized."""


class LocalQwenAnalyzer:
    """`EvidenceAnalyzer` backed by MLX-LM + a converted LoRA adapter."""

    def __init__(
        self,
        adapter_path: str | None = None,
        base_model: str | None = None,
        max_new_tokens: int = 512,
    ):
        self.adapter_path = adapter_path or os.getenv("OUTLOOK_LOCAL_LLM_ADAPTER_PATH")
        self.base_model = base_model or os.getenv(
            "OUTLOOK_LOCAL_LLM_BASE", "mlx-community/Qwen2.5-3B-Instruct-4bit"
        )
        self.max_new_tokens = max_new_tokens
        if not self.adapter_path:
            raise LocalQwenAdapterUnavailable(
                "OUTLOOK_LOCAL_LLM_ADAPTER_PATH is not configured."
            )
        self._tokenizer, self._model = self._load()

    def _load(self):
        try:
            from mlx_lm import load
        except ImportError as exc:
            raise LocalQwenAdapterUnavailable(
                f"mlx_lm not installed: {exc}"
            ) from exc

        try:
            model, tokenizer = load(self.base_model, adapter_path=self.adapter_path)
        except Exception as exc:
            raise LocalQwenAdapterUnavailable(
                f"failed to load Qwen base + LoRA adapter: {exc}"
            ) from exc
        return tokenizer, model

    def _generate(self, prompt: str) -> str:
        from mlx_lm import generate

        messages = [{"role": "user", "content": prompt}]
        chat_input = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        return generate(
            self._model,
            self._tokenizer,
            prompt=chat_input,
            max_tokens=self.max_new_tokens,
            verbose=False,
        ).strip()

    def analyze_evidence(self, evidence: list[Evidence]):
        from llm.analyzer import LLMAnalysisResult

        llm_evidence = filter_llm_evidence(evidence)
        if not llm_evidence:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="local_qwen",
                        code="no_evidence",
                        message="No evidence available for local Qwen analysis.",
                    )
                ]
            )

        prompt = build_evidence_prompt(llm_evidence)
        try:
            raw_output = self._generate(prompt)
        except Exception as exc:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="local_qwen",
                        code="generation_failed",
                        message=str(exc),
                    )
                ]
            )

        payload = _extract_first_json_object(raw_output)
        if payload is None:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="local_qwen",
                        code="invalid_json",
                        message="local Qwen output did not contain a JSON object",
                    )
                ]
            )

        try:
            signal = AISignal.model_validate(payload)
        except Exception as exc:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="local_qwen",
                        code="schema_validation_failed",
                        message=str(exc),
                    )
                ]
            )

        allowed_ids = {item.evidence_id for item in llm_evidence}
        unknown = [eid for eid in signal.evidence_ids if eid not in allowed_ids]
        if unknown:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="local_qwen",
                        code="unknown_evidence_id",
                        message=f"local Qwen referenced unknown evidence ids: {unknown}",
                    )
                ]
            )

        return LLMAnalysisResult(signals=[signal])


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Pull the first balanced JSON object out of a free-form completion."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : idx + 1])
                except json.JSONDecodeError:
                    return None
    return None
