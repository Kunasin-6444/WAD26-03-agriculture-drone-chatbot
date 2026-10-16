import time
import unittest
from unittest.mock import patch

from app.rag import rag_service
from app.rag.crag_service import DEGRADED_MESSAGE, run_crag_pipeline


KB_CONTEXT = "[แหล่งข้อมูล 1]\nไฟล์: a.pdf\nหน้า: 1\nเนื้อหา: โดรนพ่นยาต้องตรวจสอบหัวฉีดก่อนใช้งาน"


class _QuotaError(Exception):
    status_code = 401

    def __init__(self, body):
        super().__init__(body)
        self.body = body


class _Client:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                raise _QuotaError({"error": "This model reached daily limit."})


class DegradedModeContract(unittest.TestCase):
    def setUp(self):
        rag_service._EXHAUSTED_MODELS.clear()
        self.addCleanup(rag_service._EXHAUSTED_MODELS.clear)
        # A developer's .env secondary provider must never be reached from a unit test.
        for name, value in (("SECONDARY_BASE_URL", ""), ("SECONDARY_API_KEY", "")):
            patcher = patch.object(rag_service, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_daily_limit_gets_long_cooldown_and_unavailable_error(self):
        with self.assertRaises(rag_service.LLMUnavailableError):
            rag_service.call_llm([{"role": "user", "content": "x"}], client=_Client(), max_attempts=1)
        wait = rag_service._EXHAUSTED_MODELS["gemini-3.5-flash-lite"] - time.monotonic()
        self.assertGreater(wait, 600)

    def test_pipeline_reports_degraded_not_insufficient_evidence(self):
        with patch("app.rag.crag_service.retrieve_context", return_value=KB_CONTEXT), \
             patch("app.rag.crag_service.search_web_fallback", return_value=[]), \
             patch("app.rag.crag_service.evaluate_evidence",
                   return_value=rag_service.GroundedResult(reason="x", llm_unavailable=True)):
            response = run_crag_pipeline("โดรนพ่นยาใช้ยังไง", client=_Client())
        self.assertEqual(response.source_type, "abstain")
        self.assertEqual(response.answer, DEGRADED_MESSAGE)


if __name__ == "__main__":
    unittest.main()
