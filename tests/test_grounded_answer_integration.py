import unittest

from app.services.ai_service import ask_ai


class TestGroundedAnswerIntegration(unittest.TestCase):
    """
    End-to-end integration tests for RAG grounded answering via ask_ai.
    """

    def test_ask_ai_q1_flow_rate_orange_fan(self):
        answer = ask_ai("หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด?")
        self.assertIn("500", answer)
        self.assertTrue("UAV07" in answer or "UAV06" in answer)
        self.assertTrue("หน้า 12" in answer or "หน้า 5" in answer or "5" in answer)

    def test_ask_ai_q2_spray_width_at_1m(self):
        answer = ask_ai("ที่ความสูง 1 เมตร หน้ากว้างการฉีดพ่นต่อหัวเท่าไร?")
        self.assertIn("2.8", answer)
        self.assertIn("12", answer)
        self.assertIn("UAV07", answer)

    def test_ask_ai_caat_air_law_topic(self):
        answer = ask_ai("การขึ้นทะเบียนโดรนต้องทำอย่างไร?")
        self.assertIn("https://uasportal.caat.or.th/infographic", answer)
        self.assertIn("CAAT", answer)

    def test_ask_ai_out_of_scope_abstains(self):
        answer = ask_ai("โดรนรุ่นไหนบินไปดาวอังคารได้เร็วที่สุด?")
        self.assertIn("ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้", answer)


if __name__ == "__main__":
    unittest.main()
