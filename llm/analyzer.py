"""Structured LLM analyzer with disabled and injectable-client modes."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import requests
from pydantic import ValidationError

from analysis.models import AISignal, AnalysisError, Evidence

CompletionFn = Callable[[str], str]


@dataclass
class LLMAnalysisResult:
    signals: list[AISignal] = field(default_factory=list)
    errors: list[AnalysisError] = field(default_factory=list)


class DisabledLLMAnalyzer:
    def analyze_evidence(self, evidence: list[Evidence]) -> LLMAnalysisResult:
        return LLMAnalysisResult(
            signals=[
                AISignal(
                    label="LLM analysis disabled",
                    direction="neutral",
                    score=0,
                    summary="LLM analysis is disabled because no provider is configured.",
                    evidence_ids=[item.evidence_id for item in evidence],
                    confidence=0.0,
                )
            ]
        )


class StructuredLLMAnalyzer:
    def __init__(self, completion_fn: CompletionFn):
        self._completion_fn = completion_fn

    def analyze_evidence(self, evidence: list[Evidence]) -> LLMAnalysisResult:
        prompt = build_evidence_prompt(evidence)
        try:
            raw_output = self._completion_fn(prompt)
            payload = json.loads(raw_output)
            signal = AISignal.model_validate(payload)
        except json.JSONDecodeError as exc:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="llm",
                        code="invalid_json",
                        message=f"LLM output was not valid JSON: {exc}",
                    )
                ]
            )
        except ValidationError as exc:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="llm",
                        code="schema_validation_failed",
                        message=str(exc),
                    )
                ]
            )
        except Exception as exc:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="llm",
                        code="request_failed",
                        message=str(exc),
                    )
                ]
            )

        allowed_ids = {item.evidence_id for item in evidence}
        unknown_ids = [evidence_id for evidence_id in signal.evidence_ids if evidence_id not in allowed_ids]
        if unknown_ids:
            return LLMAnalysisResult(
                errors=[
                    AnalysisError(
                        source="llm",
                        code="unknown_evidence_id",
                        message=f"LLM referenced unknown evidence ids: {unknown_ids}",
                    )
                ]
            )

        return LLMAnalysisResult(signals=[signal])


class OpenAIResponsesAnalyzer(StructuredLLMAnalyzer):
    """OpenAI Responses API adapter.

    Official OpenAI docs recommend the Responses API for new text generation
    integrations. This adapter is optional and only used when OPENAI_API_KEY is
    configured.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        session: Any = requests,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.2")
        self.session = session
        self.timeout = timeout
        super().__init__(self._complete)

    def _complete(self, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        response = self.session.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": prompt,
                "text": {"format": {"type": "json_object"}},
            },
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"OpenAI Responses API returned HTTP {response.status_code}")

        payload = response.json()
        if payload.get("output_text"):
            return payload["output_text"]

        texts: list[str] = []
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    texts.append(content["text"])
        if not texts:
            raise RuntimeError("OpenAI response did not include output text")
        return "\n".join(texts)


def build_evidence_prompt(evidence: list[Evidence]) -> str:
    evidence_lines = []
    for item in evidence:
        content = (item.content or "")[:1200]
        evidence_lines.append(
            "\n".join(
                [
                    f"evidence_id: {item.evidence_id}",
                    f"kind: {item.kind}",
                    f"title: {item.title}",
                    f"source: {item.source}",
                    f"content: {content}",
                ]
            )
        )

    return (
        "You analyze only the evidence below. Do not use facts that are not present. "
        "Return one JSON object matching this schema: "
        '{"label": str, "direction": "positive|negative|neutral", "score": int, '
        '"summary": str, "evidence_ids": [str], "confidence": float}. '
        "The direction and score must agree: positive > 0, negative < 0, neutral = 0. "
        "Use only evidence_id values shown below.\n\n"
        + "\n\n---\n\n".join(evidence_lines)
    )
