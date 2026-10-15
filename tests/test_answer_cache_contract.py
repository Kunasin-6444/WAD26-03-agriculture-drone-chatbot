import unittest
from unittest.mock import patch

from app.rag.crag_service import CragResponse
from app.services import ai_service


def _response(answer="คำตอบ", source="knowledge_base", grade="CORRECT"):
    return CragResponse(answer, source, grade, "", {}, [])


class AnswerCacheContract(unittest.TestCase):
    def setUp(self):
        ai_service.clear_answer_cache()
        self.addCleanup(ai_service.clear_answer_cache)

    def test_grounded_answer_is_served_from_cache_on_repeat(self):
        with patch("app.services.ai_service.run_crag_pipeline", return_value=_response()) as run:
            first = ai_service.ask_ai("พัดส้ม  อัตราการไหล")
            second = ai_service.ask_ai("พัดส้ม อัตราการไหล ")
        self.assertEqual(first, second)
        run.assert_called_once()

    def test_abstain_degraded_and_web_answers_are_never_cached(self):
        for response in (_response("ไม่พบ", "abstain", "INCORRECT"), _response("เว็บ", "web_fallback", "CORRECT"),
                         _response("ผสม", "hybrid", "CORRECT"), _response("บางส่วน", "knowledge_base", "AMBIGUOUS")):
            with self.subTest(source=response.source_type, grade=response.grade):
                ai_service.clear_answer_cache()
                with patch("app.services.ai_service.run_crag_pipeline", return_value=response) as run:
                    ai_service.ask_ai("คำถามหนึ่ง")
                    ai_service.ask_ai("คำถามหนึ่ง")
                self.assertEqual(run.call_count, 2)

    def test_freshness_questions_are_never_cached(self):
        with patch("app.services.ai_service.run_crag_pipeline", return_value=_response()) as run:
            ai_service.ask_ai("ราคาน้ำมันวันนี้")
            ai_service.ask_ai("ราคาน้ำมันวันนี้")
        self.assertEqual(run.call_count, 2)

    def test_ttl_zero_disables_cache(self):
        with patch.dict("os.environ", {"ANSWER_CACHE_TTL_SECONDS": "0"}), \
             patch("app.services.ai_service.run_crag_pipeline", return_value=_response()) as run:
            ai_service.ask_ai("คำถามสอง")
            ai_service.ask_ai("คำถามสอง")
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
