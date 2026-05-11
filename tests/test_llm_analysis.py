import json
import unittest

from analysis.models import Evidence
from llm.analyzer import (
    DisabledLLMAnalyzer,
    OpenAIResponsesAnalyzer,
    StructuredLLMAnalyzer,
    build_evidence_prompt,
)


class MockOpenAIResponse:
    status_code = 200

    def json(self):
        return {
            "output_text": json.dumps(
                {
                    "label": "news interpretation",
                    "direction": "positive",
                    "score": 1,
                    "summary": "실적 개선 근거",
                    "evidence_ids": ["news-1"],
                    "confidence": 0.6,
                }
            )
        }


class MockOpenAISession:
    def __init__(self):
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return MockOpenAIResponse()


class LLMAnalysisTests(unittest.TestCase):
    def test_disabled_llm_analyzer_returns_neutral_signal(self):
        evidence = [
            Evidence(
                evidence_id="news-1",
                kind="news",
                source="mock",
                title="실적 개선",
                content="영업이익 증가",
            )
        ]

        result = DisabledLLMAnalyzer().analyze_evidence(evidence)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.signals[0].direction, "neutral")
        self.assertEqual(result.signals[0].score, 0)
        self.assertEqual(result.signals[0].evidence_ids, ["news-1"])

    def test_structured_llm_analyzer_validates_json_with_pydantic(self):
        evidence = [Evidence(evidence_id="disc-1", kind="disclosure", source="DART", title="분기보고서")]

        def completion(prompt):
            self.assertIn("evidence_id: disc-1", prompt)
            return json.dumps(
                {
                    "label": "disclosure risk",
                    "direction": "negative",
                    "score": -2,
                    "summary": "수익성 악화가 언급됨",
                    "evidence_ids": ["disc-1"],
                    "confidence": 0.7,
                }
            )

        result = StructuredLLMAnalyzer(completion).analyze_evidence(evidence)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.signals[0].label, "disclosure risk")
        self.assertEqual(result.signals[0].score, -2)

    def test_invalid_json_output_returns_recoverable_error(self):
        evidence = [Evidence(evidence_id="news-1", kind="news", source="mock", title="기사")]
        result = StructuredLLMAnalyzer(lambda prompt: "not-json").analyze_evidence(evidence)

        self.assertEqual(result.signals, [])
        self.assertEqual(result.errors[0].code, "invalid_json")
        self.assertTrue(result.errors[0].recoverable)

    def test_unknown_evidence_id_is_rejected(self):
        evidence = [Evidence(evidence_id="news-1", kind="news", source="mock", title="기사")]
        result = StructuredLLMAnalyzer(
            lambda prompt: json.dumps(
                {
                    "label": "unsupported",
                    "direction": "positive",
                    "score": 1,
                    "summary": "unknown id",
                    "evidence_ids": ["news-2"],
                    "confidence": 0.5,
                }
            )
        ).analyze_evidence(evidence)

        self.assertEqual(result.signals, [])
        self.assertEqual(result.errors[0].code, "unknown_evidence_id")

    def test_prompt_limits_analysis_to_evidence_ids(self):
        evidence = [Evidence(evidence_id="fin-1", kind="financial", source="DART", title="재무제표")]
        prompt = build_evidence_prompt(evidence)

        self.assertIn("반드시 한국어로만 답한다", prompt)
        self.assertIn("score는 반드시 -2, -1, 0, 1, 2", prompt)
        self.assertIn("evidence_ids는 아래에 표시된 evidence_id만 사용한다", prompt)
        self.assertIn("evidence_id: fin-1", prompt)

    def test_openai_responses_adapter_parses_output_text(self):
        session = MockOpenAISession()
        analyzer = OpenAIResponsesAnalyzer(api_key="test-key", model="gpt-test", session=session)
        evidence = [Evidence(evidence_id="news-1", kind="news", source="mock", title="기사")]

        result = analyzer.analyze_evidence(evidence)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.signals[0].direction, "positive")
        self.assertEqual(session.calls[0][1]["json"]["model"], "gpt-test")
        self.assertEqual(session.calls[0][1]["json"]["temperature"], 0)


if __name__ == "__main__":
    unittest.main()
