"""Exercise the evaluator with the real candidate orchestration and offline providers."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.rag.candidate import pipeline
from app.rag.evidence import Evidence
from scripts import evaluate_answers as ev


KB_ANSWER = "ปั๊มอัลฟามีปริมาณ 250 ml [D1]\nยังไม่พบข้อมูล: ราคาปั๊มอัลฟา"
WEB_ANSWER = "ปั๊มอัลฟาราคา 900 บาท [W1]"


class CandidateEvaluation(unittest.TestCase):
    def run_offline(self, replies, count):
        args = SimpleNamespace(
            pipeline="candidate", model="model-a", prompt="full", judge_model="model-b",
            skip_judge=True, split="dev", no_answer_only=True, limit=count, ids=None,
            gold=ev.GOLD, attempt_timeout=25, kb_budget=None, request_timeout=None,
            output="candidate-unit", reasoning_effort="low", answer_mode="natural")
        cases = [{"id": f"pump-{i}", "query": "ปั๊มอัลฟามีปริมาณและราคาเท่าไร",
                  "expected_answer": "250 ml และ 900 บาท", "must_contain": ["250", "900"],
                  "evidence_groups": [{"pages": [{"source_file": "pumps.pdf", "page_number": "1"}]}]}
                 for i in range(count)]
        kb = Evidence("D1", "ปั๊มอัลฟามีปริมาณ 250 ml", "pumps.pdf", "1")
        web = Evidence("W1", "ปั๊มอัลฟาราคา 900 บาท",
                       url="https://example.org/pumps/alpha", title="Pump price")
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"API_KEY": "test"}))
            stack.enter_context(patch.object(ev, "OUT_DIR", Path(folder)))
            stack.enter_context(patch.object(ev, "load_cases", return_value=cases))
            stack.enter_context(patch("app.rag.rag_service.FALLBACK_MODELS", []))
            stack.enter_context(patch("app.rag.rag_service.secondary_enabled", return_value=False))
            stack.enter_context(patch("app.rag.crag_service.run_crag_pipeline",
                                      side_effect=AssertionError("candidate must not call baseline")))
            for name, value in (("llm_pool_error", ""), ("retrieve_evidence", [kb]),
                                ("search_web_fallback", []), ("web_evidence", [web])):
                stack.enter_context(patch.object(pipeline, name, return_value=value))
            call = stack.enter_context(patch.object(pipeline, "call_llm", side_effect=replies))
            status = ev.run(args)
            report = json.loads((Path(folder) / "candidate-unit.json").read_text(encoding="utf-8"))
            self.assertTrue((Path(folder) / "candidate-unit.csv").exists())
            self.assertIs(pipeline.call_llm, call, "trace hook must restore the provider alias")
            return status, report, call.call_count

    def test_candidate_selected_and_each_generation_traced_without_quality_claim(self):
        status, report, calls = self.run_offline([KB_ANSWER, WEB_ANSWER], 1)
        self.assertEqual((status, calls), (0, 2))
        config, row = report["config"], report["rows"][0]
        self.assertEqual(config["pipeline"], "candidate")
        self.assertEqual(config["answer_mode"], "candidate")
        self.assertEqual(config["case_ids"], ["pump-0"])
        self.assertEqual(len(config["gold_sha256"]), 64)
        self.assertEqual([g["raw_answer"] for g in row["trace"]["generation"]], [KB_ANSWER, WEB_ANSWER])
        self.assertEqual(len(row["trace"]["retrieval"]), 1)
        self.assertEqual(len(row["trace"]["web"]), 1)
        self.assertIn("250 ml", row["answer"])
        self.assertIn("900 บาท", row["answer"])
        self.assertEqual(row["pipeline_result"]["semantic_quality"], "not_assessed")
        self.assertIsNone(report["summary"]["quality_review"]["pass_rate"])

    def test_two_partial_provider_failures_stop_even_with_usable_kb_answers(self):
        status, report, calls = self.run_offline(
            [KB_ANSWER, TimeoutError("offline timeout"), KB_ANSWER, TimeoutError("offline timeout")], 3)
        self.assertEqual((status, calls), (1, 4))
        self.assertEqual([r["outcome"] for r in report["rows"]], ["answered", "answered", "not_run"])
        for row in report["rows"][:2]:
            self.assertIn("250 ml", row["answer"])
            self.assertEqual(row["error_code"], "timeout")
            self.assertEqual(row["trace"]["generation"][1]["error_type"], "TimeoutError")

    def test_existing_report_is_preserved_before_any_provider_setup(self):
        args = SimpleNamespace(pipeline="candidate", model="model-a", prompt="full", output="existing")
        with tempfile.TemporaryDirectory() as folder, patch.object(ev, "OUT_DIR", Path(folder)), \
                patch.object(ev, "pin_model") as pin:
            target = Path(folder) / "existing.json"
            target.write_text("original baseline", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                ev.run(args)
            pin.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "original baseline")


if __name__ == "__main__":
    unittest.main()
