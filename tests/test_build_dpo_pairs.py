"""Unit tests for the DPO pair generator."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.build_dpo_pairs import (
    NEUTRAL_RETURN_THRESHOLD,
    build_pairs,
    realized_direction,
    synthesize_chosen_response,
)


def _evidence(eid: str, kind: str = "disclosure", title: str = "공시 제목") -> dict:
    return {
        "evidence_id": eid,
        "kind": kind,
        "source": "DART",
        "title": title,
        "metadata": {},
    }


def _ai_signal(direction: str, score: int, evidence_ids: list[str]) -> dict:
    return {
        "label": "test",
        "direction": direction,
        "score": score,
        "summary": "summary",
        "evidence_ids": evidence_ids,
        "confidence": 0.4,
    }


def _report(date: str, code: str, direction: str, score: int, evidence_ids: list[str]) -> dict:
    return {
        "as_of_date": date,
        "stock_code": code,
        "stock_name": code,
        "generated_at": f"{date}T00:00:00Z",
        "summary": "",
        "score": {
            "quant_score": 0,
            "ai_score": score,
            "financial_score": 0,
            "total_score": score,
            "direction": direction,
        },
        "quant_signals": [],
        "ai_signals": [_ai_signal(direction, score, evidence_ids)],
        "financial_signals": [],
        "evidence": [_evidence(eid) for eid in evidence_ids],
        "errors": [],
    }


class RealizedDirectionTests(unittest.TestCase):
    def test_positive_when_above_threshold(self):
        self.assertEqual(realized_direction(0.01), "positive")

    def test_negative_when_below_neg_threshold(self):
        self.assertEqual(realized_direction(-0.02), "negative")

    def test_neutral_inside_band(self):
        self.assertEqual(realized_direction(0.0), "neutral")
        self.assertEqual(realized_direction(0.001), "neutral")

    def test_custom_epsilon(self):
        self.assertEqual(realized_direction(0.001, neutral_eps=0.0005), "positive")


class SynthesizeChosenTests(unittest.TestCase):
    def test_chosen_score_matches_direction(self):
        import random as _rng
        for direction, score in (("positive", 2), ("negative", -2), ("neutral", 0)):
            chosen = synthesize_chosen_response(direction, ["x", "y"], _rng.Random(0))
            self.assertEqual(chosen["direction"], direction)
            self.assertEqual(chosen["score"], score)
            self.assertEqual(chosen["evidence_ids"], ["x", "y"])
            self.assertEqual(chosen["confidence"], 0.5)


class BuildPairsTests(unittest.TestCase):
    def test_pair_generated_for_misaligned_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dataset = pd.DataFrame(
                [
                    # row 0: LLM neutral, return strongly negative → misaligned
                    {"date": "2026-05-01", "stock_code": "005930", "next_day_return": -0.05},
                    # row 1: LLM positive, return positive → aligned, should skip
                    {"date": "2026-05-02", "stock_code": "005930", "next_day_return": 0.04},
                ]
            )
            dataset_csv = tmp_path / "ml_dataset.csv"
            dataset.to_csv(dataset_csv, index=False)

            reports_jsonl = tmp_path / "reports.jsonl"
            reports_jsonl.write_text(
                "\n".join(
                    json.dumps(rec, ensure_ascii=False)
                    for rec in [
                        _report("2026-05-01", "005930", "neutral", 0, ["disclosure-1"]),
                        _report("2026-05-02", "005930", "positive", 2, ["disclosure-2"]),
                    ]
                ),
                encoding="utf-8",
            )

            output_jsonl = tmp_path / "dpo_pairs.jsonl"
            summary = build_pairs(dataset_csv, reports_jsonl, output_jsonl)
            self.assertEqual(summary["pairs"], 1)
            self.assertEqual(summary["skipped_aligned"], 1)

            lines = output_jsonl.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            pair = json.loads(lines[0])
            self.assertIn("prompt", pair)
            self.assertIn("evidence_id: disclosure-1", pair["prompt"])  # exact prompt body
            chosen = json.loads(pair["chosen"])
            rejected = json.loads(pair["rejected"])
            self.assertEqual(chosen["direction"], "negative")
            self.assertEqual(rejected["direction"], "neutral")
            self.assertEqual(pair["metadata"]["actual_direction"], "negative")
            self.assertEqual(pair["metadata"]["llm_direction"], "neutral")

    def test_skips_row_without_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dataset = pd.DataFrame(
                [{"date": "2026-05-01", "stock_code": "005930", "next_day_return": -0.05}]
            )
            dataset_csv = tmp_path / "ml_dataset.csv"
            dataset.to_csv(dataset_csv, index=False)
            reports_jsonl = tmp_path / "reports.jsonl"
            reports_jsonl.write_text("", encoding="utf-8")

            output_jsonl = tmp_path / "dpo_pairs.jsonl"
            summary = build_pairs(dataset_csv, reports_jsonl, output_jsonl)
            self.assertEqual(summary["pairs"], 0)
            self.assertEqual(summary["skipped_no_report"], 1)

    def test_skips_disabled_llm_responses_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dataset = pd.DataFrame(
                [{"date": "2026-05-01", "stock_code": "005930", "next_day_return": -0.05}]
            )
            dataset_csv = tmp_path / "ml_dataset.csv"
            dataset.to_csv(dataset_csv, index=False)

            empty_report = _report("2026-05-01", "005930", "neutral", 0, [])
            empty_report["evidence"] = []
            empty_report["ai_signals"] = []
            reports_jsonl = tmp_path / "reports.jsonl"
            reports_jsonl.write_text(
                json.dumps(empty_report, ensure_ascii=False), encoding="utf-8"
            )

            output_jsonl = tmp_path / "dpo_pairs.jsonl"
            summary = build_pairs(dataset_csv, reports_jsonl, output_jsonl)
            self.assertEqual(summary["pairs"], 0)
            self.assertEqual(summary["skipped_no_evidence"], 1)


if __name__ == "__main__":
    unittest.main()
