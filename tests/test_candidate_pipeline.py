import unittest
from unittest.mock import MagicMock, patch

from app.rag.candidate.models import CandidateResponse
from app.rag.candidate.pipeline import run_candidate_pipeline
from app.rag.evidence import Evidence


class TestCandidatePipeline(unittest.TestCase):
    def setUp(self):
        self.kb_chunk = Evidence(
            id="D1",
            content="การใช้งานโดรนเกษตร: ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% ขณะบิน",
            source_file="ฟีเจอร์โดรนของฉัน.pdf",
            page_number="3",
        )
        self.web_chunk = Evidence(
            id="W1",
            content="ข้อบังคับ กพท. การบินโดรนต้องจัดทำประกันภัยบุคคลภายนอก วงเงิน 1,000,000 บาท",
            url="https://uasportal.caat.or.th/insurance",
            title="CAAT UAS Portal",
        )

    def test_candidate_response_contract_fields_present(self):
        with patch("app.rag.candidate.pipeline.llm_pool_error", return_value=""), \
             patch("app.rag.candidate.pipeline.retrieve_evidence", return_value=[self.kb_chunk]), \
             patch("app.rag.candidate.pipeline.call_llm", return_value="ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% ขณะบิน [D1]"):

            resp = run_candidate_pipeline("แบตเตอรี่ขณะบิน", mode="kb_only")

            self.assertIsInstance(resp, CandidateResponse)
            # Contract fields
            self.assertEqual(resp.source_type, "knowledge_base")
            self.assertEqual(resp.grade, "CANDIDATE")
            self.assertEqual(resp.semantic_quality, "not_assessed")  # honest quality attribution!
            self.assertTrue(resp.generation_succeeded)
            self.assertTrue(resp.citation_checks_passed)

            # Rich metadata
            self.assertTrue(len(resp.pre_selection_evidence) > 0)
            self.assertTrue(len(resp.post_selection_evidence) > 0)
            self.assertIn("30%", resp.answer)
            self.assertIn("[1]", resp.answer)
            self.assertIn("แหล่งอ้างอิง:\n[1] ฟีเจอร์โดรนของฉัน.pdf, หน้า 3", resp.answer)

    def test_mixed_mode_gap_filling_preserves_kb_facts(self):
        kb_gen = (
            "• ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% ขณะบิน [D1]\n"
            "ยังไม่พบข้อมูล: วงเงินประกันภัยโดรน กพท."
        )
        web_gen = "• ประกันภัยบุคคลภายนอกต้องมีวงเงิน 1,000,000 บาท [W1]"

        with patch("app.rag.candidate.pipeline.llm_pool_error", return_value=""), \
             patch("app.rag.candidate.pipeline.retrieve_evidence", return_value=[self.kb_chunk]), \
             patch("app.rag.candidate.pipeline.search_web_fallback", return_value=[{"url": "https://uasportal.caat.or.th/insurance", "title": "CAAT", "snippet": "ประกัน 1,000,000 บาท"}]), \
             patch("app.rag.candidate.pipeline.web_evidence", return_value=[self.web_chunk]), \
             patch("app.rag.candidate.pipeline.call_llm", side_effect=[kb_gen, web_gen]):

            resp = run_candidate_pipeline("แบตเตอรี่และประกันภัย", mode="mixed")

            self.assertEqual(resp.source_type, "hybrid")
            self.assertTrue(resp.generation_succeeded)
            self.assertTrue(resp.citation_checks_passed)

            # Both KB fact and Web fact are present
            self.assertIn("ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% ขณะบิน", resp.answer)
            self.assertIn("1,000,000 บาท", resp.answer)

            # Both references exist
            self.assertIn("ฟีเจอร์โดรนของฉัน.pdf, หน้า 3", resp.answer)
            self.assertIn("https://uasportal.caat.or.th/insurance", resp.answer)

    def test_mixed_mode_web_failure_does_not_lose_kb_facts(self):
        kb_gen = (
            "• ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% ขณะบิน [D1]\n"
            "ยังไม่พบข้อมูล: ข้อกำหนดประกันภัย"
        )

        with patch("app.rag.candidate.pipeline.llm_pool_error", return_value=""), \
             patch("app.rag.candidate.pipeline.retrieve_evidence", return_value=[self.kb_chunk]), \
             patch("app.rag.candidate.pipeline.search_web_fallback", side_effect=TimeoutError("web search timeout")), \
             patch("app.rag.candidate.pipeline.call_llm", return_value=kb_gen):

            resp = run_candidate_pipeline("แบตเตอรี่และประกันภัย", mode="mixed")

            # KB facts must remain completely intact!
            self.assertEqual(resp.source_type, "knowledge_base")
            self.assertIn("ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% ขณะบิน", resp.answer)
            self.assertIn("ยังไม่พบข้อมูล: ข้อกำหนดประกันภัย", resp.answer)
            self.assertTrue(resp.generation_succeeded)

    def test_llm_pool_unavailable_returns_degraded_without_inventing_facts(self):
        with patch("app.rag.candidate.pipeline.llm_pool_error", return_value="quota_exhausted"):
            resp = run_candidate_pipeline("แบตเตอรี่ขณะบิน")

            self.assertEqual(resp.source_type, "abstain")
            self.assertEqual(resp.error_code, "quota_exhausted")
            self.assertFalse(resp.generation_succeeded)
            self.assertFalse(resp.citation_checks_passed)
            self.assertEqual(resp.semantic_quality, "not_assessed")

    def test_empty_query_returns_abstain(self):
        resp = run_candidate_pipeline("")
        self.assertEqual(resp.source_type, "abstain")
        self.assertEqual(resp.error_code, "empty_query")
        self.assertIn("กรุณาระบุคำถาม", resp.answer)

    def test_bot_usage_intent_returns_fast_path(self):
        resp = run_candidate_pipeline("ใช้งานยังไง")
        self.assertEqual(resp.source_type, "bot_usage")
        self.assertTrue(resp.generation_succeeded)

    def test_mixed_mode_can_use_web_when_kb_has_no_answer(self):
        with patch("app.rag.candidate.pipeline.llm_pool_error", return_value=""), \
             patch("app.rag.candidate.pipeline.retrieve_evidence", return_value=[]), \
             patch("app.rag.candidate.pipeline.search_web_fallback", return_value=[]) as search:
            run_candidate_pipeline("ปั๊มรุ่นแกมมามีข้อมูลอะไรบ้าง", mode="mixed")
        self.assertTrue(search.called, "Mixed mode abstained without trying web when KB was empty")

    def test_web_generation_failure_preserves_kb_and_reports_error(self):
        kb = Evidence("D1", "ปั๊มอัลฟามีปริมาณ 250 ml", "pumps.pdf", "1")
        web = Evidence("W1", "ปั๊มอัลฟาราคา 900 บาท", url="https://example.org/pumps/alpha", title="Pump price")
        with patch("app.rag.candidate.pipeline.llm_pool_error", return_value=""), \
             patch("app.rag.candidate.pipeline.retrieve_evidence", return_value=[kb]), \
             patch("app.rag.candidate.pipeline.search_web_fallback", return_value=[]), \
             patch("app.rag.candidate.pipeline.web_evidence", return_value=[web]), \
             patch("app.rag.candidate.pipeline.call_llm", side_effect=[
                 "ปั๊มอัลฟามีปริมาณ 250 ml [D1]\nยังไม่พบข้อมูล: ราคาปั๊มอัลฟา", TimeoutError("test timeout")]):
            result = run_candidate_pipeline("ปั๊มอัลฟามีปริมาณและราคาเท่าไร", mode="mixed")
        self.assertIn("250 ml", result.answer)
        self.assertEqual(result.error_code, "timeout", "Provider failure is hidden from evaluator stop logic")


if __name__ == "__main__":
    unittest.main()
