import json
import unittest

from analysis.models import Evidence
from llm.analyzer import (
    DisabledLLMAnalyzer,
    OpenAIResponsesAnalyzer,
    StructuredLLMAnalyzer,
    build_evidence_prompt,
    filter_llm_evidence,
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
        self.assertIn("투자 전망 판단의 우선순위", prompt)
        self.assertIn("노조, 성과급, 일반 정치 발언", prompt)
        self.assertIn("직접 영향이 명시된 경우에 score에 반영", prompt)
        self.assertIn("구체적 비용 추정", prompt)
        self.assertIn("해당 이슈로 인한 주가 급락이나 매도세", prompt)
        self.assertIn("반대 근거가 직접 영향 없는 낮은 우선순위 이슈뿐이면 neutral로 낮추지 말고 positive를 유지", prompt)
        self.assertIn("비용, 생산, 실적, 주가 반응 중 하나와 직접 연결될 때만", prompt)
        self.assertIn("summary는 2문장 이내로 작성한다. 첫 문장은 반드시", prompt)
        self.assertIn("마지막에 1회만 짧게 언급", prompt)
        self.assertIn("score는 반드시 -2, -1, 0, 1, 2", prompt)
        self.assertIn("evidence_ids는 아래에 표시된 evidence_id만 사용한다", prompt)
        self.assertIn("evidence_id: fin-1", prompt)

    def test_low_priority_labor_news_is_filtered_before_llm_analysis(self):
        evidence = [
            Evidence(
                evidence_id="news-1",
                kind="news",
                source="Naver News",
                title="삼성전자 주가 강세",
                content="영업이익 전망치가 상향되고 주가 모멘텀이 확인된다.",
            ),
            Evidence(
                evidence_id="news-2",
                kind="news",
                source="Naver News",
                title="삼성 노사 성과급 재협상 난항",
                content="노조가 성과급 제도화를 요구했다.",
            ),
        ]

        filtered = filter_llm_evidence(evidence)

        self.assertEqual([item.evidence_id for item in filtered], ["news-1"])

        def completion(prompt):
            self.assertIn("evidence_id: news-1", prompt)
            self.assertNotIn("evidence_id: news-2", prompt)
            self.assertNotIn("삼성 노사 성과급 재협상 난항", prompt)
            self.assertNotIn("노조가 성과급 제도화를 요구했다", prompt)
            return json.dumps(
                {
                    "label": "삼성전자",
                    "direction": "positive",
                    "score": 1,
                    "summary": "영업이익 전망치 상향과 주가 모멘텀이 확인된다.",
                    "evidence_ids": ["news-1"],
                    "confidence": 0.6,
                }
            )

        result = StructuredLLMAnalyzer(completion).analyze_evidence(evidence)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.signals[0].direction, "positive")

    def test_material_labor_news_with_cost_or_stock_reaction_reaches_llm_analysis(self):
        evidence = [
            Evidence(
                evidence_id="news-1",
                kind="news",
                source="Naver News",
                title="삼성전자 노조 리스크에 주가 급락",
                content="JP모건은 성과급 요구 수용 시 추가 인건비 부담이 커질 수 있다고 분석했고 주가 급락이 나타났다.",
            ),
            Evidence(
                evidence_id="news-2",
                kind="news",
                source="Naver News",
                title="삼성 노사 성과급 재협상 난항",
                content="노조가 성과급 제도화를 요구했다.",
            ),
        ]

        filtered = filter_llm_evidence(evidence)

        self.assertEqual([item.evidence_id for item in filtered], ["news-1"])

        def completion(prompt):
            self.assertIn("evidence_id: news-1", prompt)
            self.assertIn("JP모건", prompt)
            self.assertIn("주가 급락", prompt)
            self.assertNotIn("evidence_id: news-2", prompt)
            return json.dumps(
                {
                    "label": "삼성전자",
                    "direction": "negative",
                    "score": -1,
                    "summary": "노조 관련 추가 인건비 부담과 주가 급락이 확인돼 비용/심리 리스크가 커졌다.",
                    "evidence_ids": ["news-1"],
                    "confidence": 0.62,
                }
            )

        result = StructuredLLMAnalyzer(completion).analyze_evidence(evidence)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.signals[0].direction, "negative")

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
