import unittest
from unittest.mock import patch

from app.rag.query_rewriter import HELP_MESSAGE, fix_keyboard_layout, rewrite_query
from app.services import conversation_memory
from app.services.ai_service import ask_ai


class TestKeyboardLayoutFix(unittest.TestCase):
    def test_thai_typed_in_english_layout_is_converted(self):
        self.assertEqual(fix_keyboard_layout("ฉีดวัชพืชในอ้อยตอน 2 gfnvo"), "ฉีดวัชพืชในอ้อยตอน 2 เดือน")

    def test_real_english_terms_are_kept(self):
        self.assertEqual(fix_keyboard_layout("ใช้โดรน dji agras ดีไหม"), "ใช้โดรน dji agras ดีไหม")
        self.assertEqual(fix_keyboard_layout("drone spraying"), "drone spraying")


class TestRewriteQuery(unittest.TestCase):
    @patch("app.rag.query_rewriter.call_llm", return_value="ช่วงอ้อยอายุ 2 เดือนฉีดพ่นด้วยโดรนแบบไหนได้บ้าง")
    def test_followup_uses_history(self, mock_llm):
        history = [("ฉีดวัชพืชในอ้อยตอน 2 เดือน ต้องใช้ยาอะไร", "สารกำจัดวัชพืชในอ้อย...")]
        result = rewrite_query("ช่วงเวลานี้ฉีดพ่นด้วยโดรนอะไรได้บ้าง", history)
        self.assertEqual(result, "ช่วงอ้อยอายุ 2 เดือนฉีดพ่นด้วยโดรนแบบไหนได้บ้าง")
        self.assertIn("ฉีดวัชพืชในอ้อยตอน 2 เดือน", mock_llm.call_args.kwargs["messages"][1]["content"])

    @patch("app.rag.query_rewriter.call_llm", side_effect=RuntimeError("down"))
    def test_falls_back_to_layout_fixed_query_on_error(self, _):
        self.assertEqual(rewrite_query("อ้อย 2 gfnvo"), "อ้อย 2 เดือน")


class TestAskAi(unittest.TestCase):
    def setUp(self):
        conversation_memory._store.clear()

    @patch("app.services.ai_service.run_crag_pipeline")
    def test_help_request_returns_static_guide(self, mock_pipeline):
        self.assertEqual(ask_ai("แนะนำวิธีพิมพ์คำถามเพื่อขอข้อมูลโดรนเกษตร", "U1"), HELP_MESSAGE)
        mock_pipeline.assert_not_called()

    @patch("app.services.ai_service.rewrite_query", side_effect=lambda q, h: q)
    @patch("app.services.ai_service.run_crag_pipeline")
    def test_turns_are_remembered_per_user(self, mock_pipeline, _):
        mock_pipeline.return_value.answer = "คำตอบ"
        ask_ai("คำถามแรก", "U1")
        self.assertEqual(conversation_memory.get_history("U1"), [("คำถามแรก", "คำตอบ")])
        self.assertEqual(conversation_memory.get_history("U2"), [])


if __name__ == "__main__":
    unittest.main()
