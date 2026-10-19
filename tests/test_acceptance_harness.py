import unittest
import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.rag.crag_service import CragResponse
from scripts.evaluate_acceptance import CASES, assess
from scripts import evaluate_acceptance as harness


class AcceptanceHarnessTests(unittest.TestCase):
    def test_preemergence_case_checks_chemical_and_actual_weed_timing_not_generic_word(self):
        case = CASES[9]
        body = "อาลาคลอร์ใช้พ่นก่อนวัชพืชงอก"
        response = CragResponse(body + " UAV06 หน้า 18", "knowledge_base", "CORRECT", "",
                                evidence_trace=[{"text": body}])
        self.assertTrue(assess(case, response, 3)["contract_pass"])
        response.answer = "สาร UAV06 หน้า 18"
        response.evidence_trace = [{"text": "สาร"}]
        self.assertFalse(assess(case, response, 3)["contract_pass"])
    def _run_cli_case(self, response, target_seconds=8):
        with tempfile.TemporaryDirectory() as folder:
            output = str(Path(folder) / "report.json")
            case = {**CASES[0], "target_seconds": target_seconds}
            with patch("sys.argv", ["evaluate_acceptance", "--limit", "1", "--output", output]), \
                 patch.object(harness, "CASES", [case]), patch.object(harness, "run_crag_pipeline", return_value=response), \
                 patch.object(harness.time, "monotonic", side_effect=[0, 1]), redirect_stdout(io.StringIO()):
                return harness.main()

    def test_cli_returns_failure_when_contract_fails(self):
        self.assertEqual(self._run_cli_case(CragResponse("ไม่พบ", "abstain", "INCORRECT", "")), 1)

    def test_cli_returns_failure_when_latency_alone_fails(self):
        response = CragResponse("500 1600 UAV07 หน้า 12", "knowledge_base", "CORRECT", "", evidence_trace=[{"text": "500"}])
        self.assertEqual(self._run_cli_case(response, target_seconds=0.5), 1)

    def test_cli_rejects_empty_evaluation(self):
        with patch("sys.argv", ["evaluate_acceptance", "--limit", "0"]), self.assertRaises(SystemExit) as status:
            harness.main()
        self.assertEqual(status.exception.code, 2)

    def test_missing_aspect_is_failure_even_with_correct_routing_and_citation(self):
        response = CragResponse("500 ml [1] UAV07 หน้า 12", "knowledge_base", "CORRECT", "", evidence_trace=[{"text": "500 ml"}])
        result = assess(CASES[2], response, 1)
        self.assertFalse(result["contract_pass"])
        self.assertIn("missing_expected_answer_aspect", result["reasons"])

    def test_latency_report_cannot_hide_contract_failure(self):
        response = CragResponse("ไม่พบข้อมูล", "abstain", "INCORRECT", "")
        result = assess(CASES[0], response, 0.1)
        self.assertTrue(result["latency_pass"])
        self.assertFalse(result["contract_pass"])

    def test_answer_without_evidence_trace_fails(self):
        response = CragResponse("500 1600 UAV07 หน้า 12", "knowledge_base", "CORRECT", "")
        self.assertFalse(assess(CASES[0], response, 1)["contract_pass"])

    def test_28_cases_cover_documents_web_caat_hybrid_abstain_and_usage(self):
        self.assertEqual(len(CASES), 28)
        routes = {source for case in CASES for source in case["sources"]}
        self.assertEqual(routes, {"knowledge_base", "web_fallback", "caat_portal", "hybrid", "abstain", "bot_usage"})
        self.assertTrue(all(case["target_seconds"] > 0 for case in CASES))

    def test_numeric_expectations_cannot_be_satisfied_by_citation_page_number(self):
        response = CragResponse("source page 500", "knowledge_base", "CORRECT", "", evidence_trace=[{"text": "no value"}])
        case = {"sources": ["knowledge_base"], "terms": [], "citations": [], "target_seconds": 8,
                "required_numbers": "500"}
        self.assertIn("missing_verified_numeric_fact", assess(case, response, 1)["reasons"])

    def test_multi_aspect_source_gold_requires_both_source_groups(self):
        case = {"sources": ["knowledge_base"], "terms": [], "citations": [], "target_seconds": 8,
                "evidence_groups": [{"pages": [{"source_file": "a.pdf", "page_number": 1}]},
                                    {"pages": [{"source_file": "b.pdf", "page_number": 2}]}]}
        response = CragResponse("fact", "knowledge_base", "CORRECT", "", evidence_trace=[
            {"text": "fact", "evidence": [{"source_file": "a.pdf", "page_number": "1"}]}])
        self.assertIn("missing_verified_source_aspect", assess(case, response, 1)["reasons"])

    def test_provider_failures_remain_in_denominator(self):
        rows = [{"seconds": 1, "contract_pass": True, "latency_pass": True, "diagnostics": []},
                {"seconds": 8, "contract_pass": False, "latency_pass": False,
                 "diagnostics": [{"stage": "kb", "llm_unavailable": True}]}]
        result = harness.summarize(rows)
        self.assertEqual((result["total"], result["contract_passed"], result["provider_error_requests"]), (2, 1, 1))

    def test_repeat_records_every_request_and_bypasses_answer_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "report.json"
            case = {"query": "test", "sources": ["abstain"], "terms": [], "citations": [], "target_seconds": 8}
            with patch("sys.argv", ["evaluate_acceptance", "--repeat", "2", "--output", str(output)]), \
                 patch.object(harness, "CASES", [case]), \
                 patch.object(harness, "run_crag_pipeline", return_value=CragResponse("no", "abstain", "INCORRECT", "")) as run, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(harness.main(), 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(run.call_count, 2)
            self.assertEqual(report["total"], 2)
            self.assertEqual([r["iteration"] for r in report["results"]], [1, 2])
            self.assertTrue(report["complete_run"])
            self.assertEqual(report["answer_cache"], "bypassed")
