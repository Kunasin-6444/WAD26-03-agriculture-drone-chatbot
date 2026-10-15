import unittest

from app.rag.crag_service import CragResponse
from scripts.evaluate_acceptance import CASES, assess


class AcceptanceHarnessTests(unittest.TestCase):
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
