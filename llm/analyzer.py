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
        llm_evidence = filter_llm_evidence(evidence)
        prompt = build_evidence_prompt(llm_evidence)
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

        allowed_ids = {item.evidence_id for item in llm_evidence}
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
                "temperature": 0,
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


_LOW_PRIORITY_LABOR_TERMS = (
    "노사",
    "노조",
    "파업",
    "성과급",
    "임금",
    "보상",
)

_MATERIAL_LABOR_IMPACT_TERMS = (
    "생산 차질",
    "가동 중단",
    "조업 중단",
    "장기 파업",
    "회사 공시",
    "공시",
    "확정 비용",
    "실적 반영",
    "가이던스 하향",
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_low_priority_labor_evidence(item: Evidence) -> bool:
    text = f"{item.title}\n{item.content or ''}"
    return _contains_any(text, _LOW_PRIORITY_LABOR_TERMS) and not _contains_any(
        text,
        _MATERIAL_LABOR_IMPACT_TERMS,
    )


def filter_llm_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Remove low-priority labor/compensation news before LLM analysis."""
    return [item for item in evidence if not _is_low_priority_labor_evidence(item)]


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
        "아래 evidence만 근거로 한국 주식 투자 전망 신호를 작성한다. "
        "반드시 한국어로만 답한다. 영어 회사명 대신 evidence의 한국어 종목명을 우선 사용한다. "
        "evidence에 없는 사실, 추정, 일반 지식은 사용하지 않는다. "
        "같은 입력에서는 같은 결론을 내리도록 보수적으로 판단한다. "
        "투자 전망 판단의 우선순위는 다음과 같다. "
        "1순위: 실적, 영업이익, 가이던스, 업황, 수요/공급, 메모리 가격, AI/HBM, 환율, 대규모 계약, 생산능력, CAPEX. "
        "2순위: 외국인/기관 수급, 주가 모멘텀, 밸류에이션, 시장 점유율, 경쟁 구도. "
        "3순위: 공시 중 지분 변동, 대규모 투자, 소송, 제재, 자금조달, 경영권 이슈. "
        "낮은 우선순위: 노조, 성과급, 일반 정치 발언, 시장 전체 분위기, 코스피 전체 전망, 단순 인물 발언. "
        "낮은 우선순위 이슈는 evidence에 매출/이익/생산 차질/비용 증가/규제 비용 같은 직접 영향이 명시된 경우에만 score에 반영한다. "
        "직접 영향이 명시되지 않은 노조/성과급/정치 발언은 summary에서 부수적 리스크로 짧게만 언급하고 direction을 바꾸지 않는다. "
        "노조/성과급/보상 이슈는 언론 또는 증권사의 비용 추정치가 있어도 단독으로 direction 또는 score를 바꾸지 않는다. "
        "이 이슈를 score에 반영하려면 회사 공시, 실적 발표, 가이던스, 실제 생산 차질, 장기 파업, 확정 비용 증가가 evidence에 명시되어야 한다. "
        "단순 요구안, 협상, 전망, 증권사 추정은 잠재적 부수 리스크로만 다룬다. "
        "고우선순위 긍정 근거가 있고 반대 근거가 낮은 우선순위 이슈뿐이면 neutral로 낮추지 말고 positive를 유지한다. "
        "노조/성과급/정치 발언은 방향성이 단정되기 어렵다는 결론의 주된 이유로 쓰지 않는다. "
        "시장 전체 뉴스는 해당 종목의 실적, 업황, 수급과 직접 연결된 문장이 있을 때만 종목 전망 근거로 사용한다. "
        "상승/하락 근거가 섞여 있거나 근거가 약하면 neutral, score 0을 선택한다. "
        "score는 반드시 -2, -1, 0, 1, 2 중 하나만 사용한다. "
        "positive는 명확한 호재가 악재보다 강할 때만, negative는 명확한 악재가 호재보다 강할 때만 사용한다. "
        "summary는 2문장 이내로 작성한다. 첫 문장은 반드시 실적/업황/수급/주가 모멘텀/재무/공시 중 가장 중요한 고우선순위 근거로 시작한다. "
        "노조/성과급/정치 발언 같은 낮은 우선순위 이슈는 꼭 필요할 때 마지막에 1회만 짧게 언급한다. "
        "Return one JSON object matching this schema: "
        '{"label": str, "direction": "positive|negative|neutral", "score": int, '
        '"summary": str, "evidence_ids": [str], "confidence": float}. '
        "direction과 score는 반드시 일치해야 한다: positive > 0, negative < 0, neutral = 0. "
        "evidence_ids는 아래에 표시된 evidence_id만 사용한다.\n\n"
        + "\n\n---\n\n".join(evidence_lines)
    )
