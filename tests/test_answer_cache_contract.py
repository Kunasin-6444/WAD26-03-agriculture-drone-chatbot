import unittest
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
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

    def test_concurrent_identical_questions_share_generation_and_keep_citations(self):
        started, release, second_entered = threading.Event(), threading.Event(), threading.Event()
        def backend(_):
            started.set()
            if not release.wait(2):
                raise RuntimeError("test release missing")
            return _response("ข้อมูล [1]\n[1] UAV07.pdf, หน้า 12")
        def second():
            second_entered.set()
            return ai_service.ask_ai("หัวฉีดพัดส้ม")
        with patch("app.services.ai_service.run_crag_pipeline", side_effect=backend) as run, ThreadPoolExecutor(2) as pool:
            first = pool.submit(ai_service.ask_ai, "หัวฉีดพัดส้ม")
            self.assertTrue(started.wait(1))
            following = pool.submit(second)
            self.assertTrue(second_entered.wait(1))
            try:
                with self.assertRaises(FutureTimeout):
                    following.result(.05)
                self.assertEqual(run.call_count, 1)
            finally:
                release.set()
            self.assertEqual(first.result(2), following.result(2))
        self.assertIn("UAV07.pdf", first.result())
        self.assertEqual(run.call_count, 1)

    def test_failed_generation_releases_key_for_next_request(self):
        with patch("app.services.ai_service.run_crag_pipeline", side_effect=[RuntimeError("unavailable"), _response()]) as run:
            with self.assertRaises(RuntimeError):
                ai_service.ask_ai("หัวฉีดพัดส้ม")
            self.assertEqual(ai_service.ask_ai("หัวฉีดพัดส้ม"), "คำตอบ")
        self.assertEqual(run.call_count, 2)

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

    def test_caat_answers_are_not_cached_as_static_knowledge(self):
        with patch("app.services.ai_service.run_crag_pipeline", return_value=_response("กฎหมาย", "caat_portal")) as run:
            ai_service.ask_ai("ข้อกำหนดการขึ้นทะเบียนโดรน")
            ai_service.ask_ai("ข้อกำหนดการขึ้นทะเบียนโดรน")
        self.assertEqual(run.call_count, 2)

    def test_mode_switch_cannot_reuse_text_answer_for_direct_pdf(self):
        with patch("app.services.ai_service.run_crag_pipeline", side_effect=[_response("text"), _response("direct")]) as run:
            with patch.dict(os.environ, {"PDF_RETRIEVAL_MODE": "text"}):
                self.assertEqual(ai_service.ask_ai("หัวฉีด"), "text")
            with patch.dict(os.environ, {"PDF_RETRIEVAL_MODE": "direct"}):
                self.assertEqual(ai_service.ask_ai("หัวฉีด"), "direct")
        self.assertEqual(run.call_count, 2)

    def test_kb_revision_invalidation(self):
        with patch("app.services.ai_service.run_crag_pipeline", side_effect=[_response("old"), _response("new")]) as run:
            with patch.dict(os.environ, {"KB_REVISION": "one"}):
                self.assertEqual(ai_service.ask_ai("หัวฉีด"), "old")
            with patch.dict(os.environ, {"KB_REVISION": "two"}):
                self.assertEqual(ai_service.ask_ai("หัวฉีด"), "new")
        self.assertEqual(run.call_count, 2)

    def test_wal_update_invalidates_even_when_main_db_unchanged(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"CHROMA_PATH": folder}), \
             patch("app.services.ai_service.run_crag_pipeline", side_effect=[_response("old"), _response("new")]) as run:
            (Path(folder) / "chroma.sqlite3").write_bytes(b"unchanged-database")
            self.assertEqual(ai_service.ask_ai("หัวฉีด"), "old")
            (Path(folder) / "chroma.sqlite3-wal").write_bytes(b"new-commit")
            self.assertEqual(ai_service.ask_ai("หัวฉีด"), "new")
        self.assertEqual(run.call_count, 2)

    def test_answer_not_cached_if_index_changes_during_generation(self):
        with patch("app.services.ai_service._kb_fingerprint", side_effect=[("old",), ("new",), ("new",), ("new",)]), \
             patch("app.services.ai_service.run_crag_pipeline", side_effect=[_response("old"), _response("new")]) as run:
            self.assertEqual(ai_service.ask_ai("หัวฉีด"), "old")
            self.assertEqual(ai_service.ask_ai("หัวฉีด"), "new")
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
