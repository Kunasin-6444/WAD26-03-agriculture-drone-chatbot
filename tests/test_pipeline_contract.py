import unittest
from unittest.mock import patch

from app.rag.crag_service import run_crag_pipeline
from app.rag.source_policy import CAAT_PORTAL_INFOGRAPHIC_URL
from app.rag.web_fallback import WebSearchResult
from tests.helpers import DOCUMENT_CONTEXT, llm_client, result_json


class PipelineContractTests(unittest.TestCase):
    def setUp(self):
        retrieval_patch = patch("app.rag.crag_service.retrieve_context", return_value=DOCUMENT_CONTEXT)
        search_patch = patch("app.rag.crag_service.search_web_fallback", return_value=[])
        self.retrieve = retrieval_patch.start()
        self.search = search_patch.start()
        self.addCleanup(retrieval_patch.stop)
        self.addCleanup(search_patch.stop)

    def test_document_hit_one_llm_call_no_web(self):
        client = llm_client(result_json())
        answer = run_crag_pipeline("พัดส้มมีอัตราการไหลเท่าไร", client=client)
        self.assertEqual(answer.source_type, "knowledge_base")
        self.assertIn("500", answer.answer)
        self.search.assert_not_called()
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertIn("total_ms", answer.timings)

    def test_partial_evidence_searches_and_combines_both_sources(self):
        self.search.return_value = [WebSearchResult("ราคาหัวฉีด", "https://supplier.example/nozzle", "หัวฉีดราคา 120 บาท", 0.9)]
        initial = result_json("partial", missing=["ราคาหัวฉีดพัดส้ม"])
        final = result_json(claims=[("หัวฉีดพัดส้มมีอัตราการไหล 500 ml/หัวฉีด", "D1", "อัตราการไหล 500 ml/หัวฉีด"),
                                    ("หัวฉีดราคา 120 บาท", "W1", "หัวฉีดราคา 120 บาท")])
        client = llm_client(initial, final)
        response = run_crag_pipeline("พัดส้มราคาเท่าไรและไหลเท่าไร", client=client)
        self.assertEqual(response.source_type, "hybrid")
        self.assertIn("500", response.answer)
        self.assertIn("120 บาท", response.answer)
        self.assertIn("UAV07.pdf", response.answer)
        self.assertIn("https://supplier.example/nozzle", response.answer)
        self.assertIn("ราคาหัวฉีดพัดส้ม", self.search.call_args.args[0])
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_web_failure_retains_partial_document_answer(self):
        self.search.side_effect = TimeoutError()
        response = run_crag_pipeline("หัวฉีดราคาและอัตราการไหล", client=llm_client(result_json("partial", missing=["ราคา"])))
        self.assertEqual(response.source_type, "knowledge_base")
        self.assertEqual(response.grade, "AMBIGUOUS")
        self.assertIn("500", response.answer)
        self.assertIn("ยังยืนยันไม่ได้: ราคา", response.answer)

    def test_no_evidence_abstains_without_generation(self):
        self.retrieve.return_value = ""
        client = llm_client()
        response = run_crag_pipeline("โดรนดาวอังคาร", client=client)
        self.assertEqual(response.source_type, "abstain")
        self.assertIn("ไม่สามารถยืนยัน", response.answer)
        self.assertNotIn("แหล่งอ้างอิง:", response.answer)
        client.chat.completions.create.assert_not_called()
        self.search.assert_called_once()

    def test_embedding_failure_continues_to_web(self):
        self.retrieve.side_effect = RuntimeError("Embedding unavailable")
        self.search.return_value = [WebSearchResult("ความรู้", "https://doa.go.th/nozzle", "หัวฉีดอัตราการไหล 500 ml", 0.9)]
        response = run_crag_pipeline("หัวฉีดไหลเท่าไร", client=llm_client(result_json(claims=[("อัตราการไหล 500 ml", "W1", "อัตราการไหล 500 ml")])))
        self.assertEqual(response.source_type, "web_fallback")
        self.assertIn("doa.go.th", response.answer)

    def test_caat_bypasses_pdf_and_answers_only_fetched_content(self):
        self.search.return_value = [WebSearchResult("CAAT", CAAT_PORTAL_INFOGRAPHIC_URL, "ยื่นคำขอผ่านระบบ UAS Portal", 1.0)]
        response = run_crag_pipeline("ขึ้นทะเบียนโดรนอย่างไร", client=llm_client(result_json(claims=[("ยื่นคำขอผ่านระบบ UAS Portal", "W1", "ยื่นคำขอผ่านระบบ UAS Portal")])))
        self.assertEqual(response.source_type, "caat_portal")
        self.retrieve.assert_not_called()
        self.assertTrue(self.search.call_args.kwargs["is_caat_topic"])
        self.assertNotIn("1,000,000", response.answer)

    def test_caat_unavailable_does_not_invent_law(self):
        response = run_crag_pipeline("ขึ้นทะเบียนโดรนอย่างไร", client=llm_client())
        self.assertEqual(response.source_type, "abstain")
        self.assertIn(CAAT_PORTAL_INFOGRAPHIC_URL, response.answer)
        self.assertIn("ยังไม่พบหลักฐาน", response.answer)

    def test_usage_and_empty_queries_make_no_external_calls(self):
        for query in ["", "   ", "แนะนำวิธีพิมพ์คำถามเพื่อขอข้อมูลโดรน"]:
            response = run_crag_pipeline(query)
            self.assertIn(response.source_type, {"abstain", "bot_usage"})
        self.retrieve.assert_not_called()
        self.search.assert_not_called()

    def test_final_generation_failure_preserves_document_evidence(self):
        self.search.return_value = [WebSearchResult("ราคา", "https://supplier.example", "ราคา 120 บาท", 0.9)]
        response = run_crag_pipeline("หัวฉีดราคาและไหลเท่าไร", client=llm_client(result_json("partial", missing=["ราคา"]), "{invalid"))
        self.assertEqual(response.grade, "AMBIGUOUS")
        self.assertIn("500", response.answer)

    def test_today_query_cannot_be_answered_from_pdf_alone(self):
        response = run_crag_pipeline("หัวฉีดพัดส้มราคาเท่าไรวันนี้", client=llm_client(result_json()))
        self.search.assert_called_once()
        self.assertEqual(response.source_type, "abstain")
        self.assertNotIn("500", response.answer)

    def test_operational_altitude_stays_document_topic(self):
        response = run_crag_pipeline("ความสูงการพ่น 1.0 m มีหน้ากว้างเท่าไร", client=llm_client(result_json(claims=[("ความสูง 1.0 m หน้ากว้าง 2.8 m", "D1", "ความสูง 1.0 m หน้ากว้างพ่น 2.8 m ต่อหัวฉีด")])))
        self.assertEqual(response.source_type, "knowledge_base")
        self.search.assert_not_called()

    def test_fabricated_answer_uses_fallback_instead_of_fake_citation(self):
        response = run_crag_pipeline("พัดส้ม", client=llm_client(result_json(claims=[("อัตราการไหล 999", "D999", "อัตราการไหล 999")])))
        self.assertEqual(response.source_type, "abstain")
        self.assertNotIn("999", response.answer)
        self.search.assert_called_once()
