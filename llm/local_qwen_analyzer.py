"""Local Qwen + LoRA inference adapter for the outlook LLM signal.

This module is the second half of `PRD_LLM_선호학습.md`: after the Colab
notebook produces a LoRA adapter trained against `data/dpo_pairs.jsonl`,
this analyzer loads the base Qwen2.5-3B-Instruct model plus the adapter
and re-implements the `EvidenceAnalyzer` protocol so it is drop-in
compatible with the existing `OutlookService`.

Heavy ML dependencies (`torch`, `transformers`, `peft`) are imported
lazily so the rest of the project keeps importing on machines without
them. Construction failures degrade to a documented exception that the
caller can catch and fall back to the OpenAI analyzer.
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
    """`EvidenceAnalyzer` backed by a locally-loaded Qwen + LoRA adapter."""

    def __init__(
        self,
        adapter_path: str | None = None,
        base_model: str | None = None,
        max_new_tokens: int = 512,
        device: str | None = None,
    ):
        self.adapter_path = adapter_path or os.getenv("OUTLOOK_LOCAL_LLM_ADAPTER_PATH")
        self.base_model = base_model or os.getenv(
            "OUTLOOK_LOCAL_LLM_BASE", "Qwen/Qwen2.5-3B-Instruct"
        )
        self.max_new_tokens = max_new_tokens
        self.device = device or os.getenv("OUTLOOK_LOCAL_LLM_DEVICE", "auto")
        if not self.adapter_path:
            raise LocalQwenAdapterUnavailable(
                "OUTLOOK_LOCAL_LLM_ADAPTER_PATH is not configured."
            )
        self._tokenizer, self._model = self._load()

    def _load(self):
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForCausalLM, AutoTokenizer
            from peft import PeftModel
        except ImportError as exc:
            raise LocalQwenAdapterUnavailable(
                f"transformers/peft/torch not installed: {exc}"
            ) from exc

        try:
            tokenizer = AutoTokenizer.from_pretrained(self.base_model)
            base = AutoModelForCausalLM.from_pretrained(
                self.base_model,
                device_map=self.device,
                torch_dtype="auto",
            )
            model = PeftModel.from_pretrained(base, self.adapter_path)
            model.eval()
        except Exception as exc:
            raise LocalQwenAdapterUnavailable(
                f"failed to load Qwen base + LoRA adapter: {exc}"
            ) from exc
        return tokenizer, model

    def _generate(self, prompt: str) -> str:
        import torch

        messages = [{"role": "user", "content": prompt}]
        chat_input = self._tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self._tokenizer(chat_input, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                temperature=0.0,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        new_tokens = output_ids[0, inputs["input_ids"].shape[-1]:]
        return self._tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

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
