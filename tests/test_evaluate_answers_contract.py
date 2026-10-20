"""The answer evaluator scores what the user would see, with one pinned model, offline here."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts import evaluate_answers as ev

ANSWER = ("วงเงินตามเอกสาร มีดังนี้\n• สารเอใช้ 320-640 กรัม [1]\n\nแหล่งอ้างอิง:\n"
          "[1] UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf, หน้า 18\n[2] ฟีเจอร์ผสมสาร.pdf, หน้า 5–6")


class ScoringHelpers(unittest.TestCase):
    def test_terms_and_cited_pages_are_read_from_the_rendered_answer(self):
        self.assertEqual(ev.missing_terms(ANSWER, ["320 - 640", "999"]), ["999"])
        self.assertEqual(ev.cited_pages(ANSWER), {("UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf", "18"),
                                                  ("ฟีเจอร์ผสมสาร.pdf", "5"), ("ฟีเจอร์ผสมสาร.pdf", "6")})

    def test_outcome_separates_abstain_from_an_unavailable_model(self):
        self.assertEqual(ev.outcome("ยังไม่พบหลักฐานเพียงพอจากเอกสารและเว็บไซต์ จึงไม่สามารถยืนยันคำตอบได้ครับ"), "abstain")
        self.assertEqual(ev.outcome("ขณะนี้ระบบกำลังปรับปรุงชั่วคราว ไม่สามารถตอบคำถามได้"), "unavailable")
        self.assertEqual(ev.outcome(ANSWER), "answered")

    def test_judge_verdicts_must_be_booleans_and_pass_needs_all_three(self):
        raw = '```json\n{"correct":true,"complete":false,"harmful":false,"style_ok":true,"critique":"ขาดสารผสม"}\n```'
        verdict = ev.parse_judge(raw)
        self.assertEqual((verdict["passed"], verdict["critique"]), (False, "ขาดสารผสม"))
        with self.assertRaises(ValueError):
            ev.parse_judge('{"correct":"yes","complete":true,"harmful":false,"style_ok":true}')

    def test_summary_leaves_unavailable_and_unrun_cases_out_of_quality_rates(self):
        rows = [
            {"outcome": "answered", "seconds": 4.0, "must_contain": ["1"], "missing_terms": [], "gold_pages": [("a", "1")],
             "cited_gold_pages": [("a", "1")], "judge": {"passed": True, "correct": True, "complete": True,
                                                       "harmful": False, "style_ok": True}},
            {"outcome": "abstain", "seconds": 10.0, "must_contain": ["2"], "missing_terms": ["2"], "gold_pages": [("a", "2")],
             "cited_gold_pages": [], "judge": {"passed": False, "correct": True, "complete": False,
                                               "harmful": False, "style_ok": False}},
            {"outcome": "unavailable", "seconds": 40.0, "must_contain": [], "missing_terms": [], "gold_pages": [],
             "cited_gold_pages": []},
            {"outcome": "not_run", "must_contain": [], "gold_pages": []},
        ]
        summary = ev.summarize(rows)
        self.assertEqual((summary["ran"], summary["unavailable"], summary["pass_rate"], summary["abstain_rate"]),
                         (3, 1, 0.5, 0.5))
        self.assertEqual((summary["must_contain_rate"], summary["seconds_max"]), (0.5, 10.0))

    def test_judge_sees_the_reference_and_the_owner_requirements(self):
        case = {"query": "q", "expected_answer": "ref", "answer_requirements": ["lead_in", "complete_list", "unknown"]}
        payload = json.loads(ev.judge_messages(case, "bot")[1]["content"])
        self.assertEqual(payload["reference_answer"], "ref")
        self.assertEqual(len(payload["requirements"]), 2)


class PinnedRun(unittest.TestCase):
    def test_one_pinned_model_answers_and_a_different_model_judges(self):
        answers = iter([SimpleNamespace(answer=ANSWER, source_type="knowledge_base", grade_reason="Some claims rejected: x",
                                        diagnostics=[{"stage": "kb", "status": "partial"}]),
                        SimpleNamespace(answer="ขณะนี้ระบบกำลังปรับปรุงชั่วคราว", source_type="degraded"),
                        SimpleNamespace(answer="ขณะนี้ระบบกำลังปรับปรุงชั่วคราว", source_type="degraded")])
        judge = MagicMock()
        judge.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"correct":true,"complete":true,"harmful":false,"style_ok":true,"critique":"ok"}'))])
        args = SimpleNamespace(model="model-a", prompt="concise", judge_model="model-b", skip_judge=False, split="dev",
                               no_answer_only=True, limit=4, ids=None, gold=ev.GOLD, attempt_timeout=25,
                               kb_budget=None, request_timeout=None, output="unit", reasoning_effort="low")
        seen_env = []

        def fake_pipeline(query):
            seen_env.append((os.environ["RAG_MODEL"], os.environ["RAG_PROMPT"], os.environ["LLM_FALLBACK_MODELS"],
                             os.environ.get("LLM_REASONING_EFFORT")))
            return next(answers)

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"API_KEY": "test"}), \
                patch.object(ev, "OUT_DIR", Path(folder)), patch("openai.OpenAI", return_value=judge), \
                patch("app.rag.crag_service.run_crag_pipeline", side_effect=fake_pipeline), \
                patch("app.rag.rag_service.FALLBACK_MODELS", []), \
                patch("app.rag.rag_service.secondary_enabled", return_value=False):
            status = ev.run(args)
            report = json.loads((Path(folder) / "unit.json").read_text(encoding="utf-8"))
            self.assertTrue((Path(folder) / "unit.csv").exists())
        self.assertEqual(status, 1)  # stopped after two unavailable answers in a row
        self.assertEqual(seen_env[0], ("model-a", "concise", "", "low"))
        self.assertEqual([row["outcome"] for row in report["rows"]], ["answered", "unavailable", "unavailable", "not_run"])
        self.assertEqual(report["rows"][0]["grade_reason"], "Some claims rejected: x")
        self.assertEqual(report["rows"][0]["diagnostics"], [{"stage": "kb", "status": "partial"}])
        self.assertEqual(judge.chat.completions.create.call_args.kwargs["model"], "model-b")
        self.assertEqual(report["summary"]["pass_rate"], 1.0)

    def test_a_run_whose_fallbacks_are_still_active_is_refused(self):
        args = SimpleNamespace(model="model-a", prompt="full", judge_model="model-b", skip_judge=True, split="dev",
                               no_answer_only=True, limit=1, ids=None, gold=ev.GOLD, attempt_timeout=None,
                               kb_budget=None, request_timeout=None, output="unit", reasoning_effort=None)
        with patch.dict(os.environ, {"API_KEY": "test"}), patch("app.rag.rag_service.FALLBACK_MODELS", ["other"]), \
                self.assertRaises(SystemExit):
            ev.run(args)


if __name__ == "__main__":
    unittest.main()
