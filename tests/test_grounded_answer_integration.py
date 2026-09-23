import unittest

from app.services.ai_service import ask_ai


class TestGroundedAnswerIntegration(unittest.TestCase):
    """
    End-to-end integration tests for RAG grounded answering via ask_ai.
    """

    def test_ask_ai_q1_flow_rate_orange_fan(self):
        answer = ask_ai("หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด?")
        print("\nQ1 Answer:\n", answer)
        self.assertIn("500", answer)
        self.assertIn("12", answer)
        self.assertIn("UAV07", answer)

    def test_ask_ai_q2_spray_width_at_1m(self):
        answer = ask_ai("ที่ความสูง 1 เมตร หน้ากว้างการฉีดพ่นต่อหัวเท่าไร?")
        print("\nQ2 Answer:\n", answer)
        self.assertIn("2.8", answer)
        self.assertIn("12", answer)
        self.assertIn("UAV07", answer)


if __name__ == "__main__":
    unittest.main()
