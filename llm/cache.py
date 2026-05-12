"""File-backed cache wrapper for LLM evidence analysis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from analysis.models import AISignal, AnalysisError
from llm.analyzer import LLMAnalysisResult


class EvidenceAnalyzer(Protocol):
    def analyze_evidence(self, evidence): ...


def _jsonable_evidence(evidence) -> list[dict]:
    return [
        {
            "evidence_id": item.evidence_id,
            "kind": item.kind,
            "source": item.source,
            "title": item.title,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "url": str(item.url) if item.url else None,
            "content": item.content,
            "metadata": item.metadata,
        }
        for item in evidence
    ]


def cache_key_for_evidence(evidence) -> str:
    payload = json.dumps(_jsonable_evidence(evidence), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CachedLLMAnalyzer:
    def __init__(self, analyzer: EvidenceAnalyzer, cache_path: str | Path):
        self.analyzer = analyzer
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        return json.loads(self.cache_path.read_text(encoding="utf-8"))

    def _write_cache(self, cache: dict) -> None:
        self.cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def analyze_evidence(self, evidence) -> LLMAnalysisResult:
        key = cache_key_for_evidence(evidence)
        cache = self._load_cache()
        if key in cache:
            payload = cache[key]
            return LLMAnalysisResult(
                signals=[
                    AISignal.model_validate(signal)
                    for signal in payload.get("signals", [])
                ],
                errors=[
                    AnalysisError.model_validate(error)
                    for error in payload.get("errors", [])
                ],
            )

        result = self.analyzer.analyze_evidence(evidence)
        cache[key] = {
            "signals": [signal.model_dump(mode="json") for signal in result.signals],
            "errors": [error.model_dump(mode="json") for error in result.errors],
        }
        self._write_cache(cache)
        return result
