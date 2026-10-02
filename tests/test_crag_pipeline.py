import unittest
from unittest.mock import MagicMock, patch

from app.rag.crag_grader import GradeResult
from app.rag.crag_service import CragResponse, run_crag_pipeline
from app.rag.web_fallback import CAAT_PORTAL_INFOGRAPHIC_URL, WebSearchResult


class TestCragPipeline(unittest.TestCase):
    def test_empty_query_abstains(self):
        resp = run_crag_pipeline("")
        self.assertEqual(resp.source_type, "abstain")
        self.assertIn("กรุณาระบุคำถาม", resp.answer)

        resp2 = run_crag_pipeline("   ")
        self.assertEqual(resp2.source_type, "abstain")

    @patch("app.rag.crag_service.search_web_fallback")
    @patch("app.rag.crag_service.generate_web_grounded_answer")
    def test_caat_topic_routes_to_caat_portal(self, mock_web_answer, mock_search):
        mock_search.return_value = [
            WebSearchResult(
                title="CAAT UAS Portal",
                url=CAAT_PORTAL_INFOGRAPHIC_URL,
                content="กฎหมายโดรน",
            )
        ]
        mock_web_answer.return_value = (
            f"การขึ้นทะเบียนโดรนต้องดำเนินการตามข้อกำหนดของ CAAT (แหล่งอ้างอิง: {CAAT_PORTAL_INFOGRAPHIC_URL})"
        )

        resp = run_crag_pipeline("ต้องขึ้นทะเบียนโดรนเกษตรอย่างไร")

        self.assertEqual(resp.source_type, "caat_portal")
        self.assertIn(CAAT_PORTAL_INFOGRAPHIC_URL, resp.answer)
        mock_search.assert_called_once()

    @patch("app.rag.crag_service.retrieve_context")
    @patch("app.rag.crag_service.grade_retrieval")
    @patch("app.rag.crag_service.generate_grounded_answer")
    def test_in_scope_knowledge_base_hit(
        self, mock_gen_answer, mock_grade, mock_retrieve
    ):
        mock_retrieve.return_value = "[แหล่งข้อมูล 1] UAV07 หน้า 12 พัดส้ม 500 ml/หัวฉีด"
        mock_grade.return_value = GradeResult(
            grade="CORRECT",
            is_relevant=True,
            reason="มีข้อมูลอัตราการไหลชัดเจน",
            is_caat_topic=False,
        )
        mock_gen_answer.return_value = (
            "อัตราการไหล 500 ml/หัวฉีด (แหล่งอ้างอิง: UAV07, หน้า 12)"
        )

        resp = run_crag_pipeline("หัวฉีดพัดส้มมีอัตราการไหลเท่าไร")

        self.assertEqual(resp.source_type, "knowledge_base")
        self.assertEqual(resp.grade, "CORRECT")
        self.assertIn("500 ml", resp.answer)
        self.assertIn("UAV07", resp.answer)

    @patch("app.rag.crag_service.retrieve_context")
    @patch("app.rag.crag_service.grade_retrieval")
    @patch("app.rag.crag_service.generate_grounded_answer")
    @patch("app.rag.crag_service.search_web_fallback")
    @patch("app.rag.crag_service.generate_web_grounded_answer")
    def test_out_of_scope_falls_back_to_web(
        self, mock_gen_web, mock_search, mock_gen_kb, mock_grade, mock_retrieve
    ):
        # Context has no relevant info
        mock_retrieve.return_value = "[แหล่งข้อมูล 1] UAV07 หน้า 12 พัดส้ม"
        mock_grade.return_value = GradeResult(
            grade="INCORRECT",
            is_relevant=False,
            reason="ไม่มีข้อมูลเกี่ยวกับราคาน้ำมัน",
            is_caat_topic=False,
        )
        mock_search.return_value = [
            WebSearchResult(
                title="ราคาน้ำมันวันนี้",
                url="https://example.com/oil-price",
                content="ดีเซล B7 ราคา...",
            )
        ]
        mock_gen_web.return_value = (
            "ราคาน้ำมันดีเซล... (แหล่งอ้างอิง: https://example.com/oil-price)"
        )

        resp = run_crag_pipeline("ราคาน้ำมันดีเซลวันนี้เท่าไร")

        self.assertEqual(resp.source_type, "web_fallback")
        self.assertIn("https://example.com/oil-price", resp.answer)

    @patch("app.rag.crag_service.retrieve_context")
    @patch("app.rag.crag_service.grade_retrieval")
    @patch("app.rag.crag_service.search_web_fallback")
    def test_unsupported_question_abstains_cleanly(
        self, mock_search, mock_grade, mock_retrieve
    ):
        mock_retrieve.return_value = ""
        mock_grade.return_value = GradeResult(
            grade="INCORRECT",
            is_relevant=False,
            reason="ไม่มีข้อมูล",
            is_caat_topic=False,
        )
        # Web search returns nothing
        mock_search.return_value = []

        resp = run_crag_pipeline("โดรนบินไปดาวอังคารได้ไหม")

        self.assertEqual(resp.source_type, "abstain")
        self.assertIn("ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้", resp.answer)
        self.assertIn("ไม่สามารถยืนยันความถูกต้อง", resp.answer)


if __name__ == "__main__":
    unittest.main()
