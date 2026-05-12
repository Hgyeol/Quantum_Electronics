import json
import tempfile
import unittest
from pathlib import Path

from analysis.models import AISignal, Evidence
from llm.analyzer import LLMAnalysisResult
from llm.cache import CachedLLMAnalyzer


class CountingAnalyzer:
    def __init__(self):
        self.calls = 0

    def analyze_evidence(self, evidence):
        self.calls += 1
        return LLMAnalysisResult(
            signals=[
                AISignal(
                    label="cached",
                    direction="positive",
                    score=1,
                    summary="cacheable result",
                    evidence_ids=[evidence[0].evidence_id],
                    confidence=0.7,
                )
            ]
        )


class LLMCacheTests(unittest.TestCase):
    def test_cached_llm_analyzer_reuses_cached_signal(self):
        evidence = [Evidence(evidence_id="news-1", kind="news", source="mock", title="뉴스")]
        analyzer = CountingAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "llm_cache.json"
            cached = CachedLLMAnalyzer(analyzer, cache_path)

            first = cached.analyze_evidence(evidence)
            second = cached.analyze_evidence(evidence)

            self.assertEqual(analyzer.calls, 1)
            self.assertEqual(first.signals[0].summary, second.signals[0].summary)
            self.assertTrue(json.loads(cache_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
