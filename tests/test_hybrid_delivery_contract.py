"""User-facing contracts: preserve KB facts and cite the exact fetched web page."""
import unittest
from unittest.mock import MagicMock, patch

from app.rag.crag_service import run_crag_pipeline
from app.rag.evidence import Evidence, document_evidence, pack_evidence, parse_grounded_result, render_grounded_answer
from app.rag.web_fallback import WebSearchResult, search_web_fallback, web_evidence
from tests.helpers import DOCUMENT_CONTEXT, llm_client, result_json


class HybridDeliveryTests(unittest.TestCase):
    def test_final_web_answer_cannot_erase_verified_kb_fact(self):
        url = "https://www.eppo.go.th/retail/prices?date=2026-10-17#diesel"
        initial = result_json("partial", missing=["ราคาน้ำมัน"])
        final = result_json(claims=[("ราคาน้ำมัน 30 บาท", "W1", "ราคาน้ำมัน 30 บาท")])
        with patch("app.rag.crag_service.retrieve_evidence", return_value=document_evidence(DOCUMENT_CONTEXT)), \
             patch("app.rag.crag_service.search_web_fallback", return_value=[WebSearchResult("ราคาขายปลีก", url, "ราคาน้ำมัน 30 บาท")]):
            response = run_crag_pipeline("หัวฉีดไหลเท่าไรและราคาน้ำมันเท่าไร", client=llm_client(initial, final))
        self.assertEqual(response.source_type, "hybrid")
        self.assertIn("500 ml/หัวฉีด", response.answer)
        self.assertIn("30 บาท", response.answer)
        self.assertIn(url, response.answer)
        self.assertEqual(len(response.evidence_trace), 2)

    def test_trusted_page_url_and_title_survive_to_line_ready_text(self):
        url = "https://www.doa.go.th/research/report.pdf?id=42&lang=th#page=12"
        web = web_evidence([WebSearchResult("คู่มือการเลือกหัวฉีด", url, "อัตราการไหล 500 ml")])
        result = parse_grounded_result(result_json(claims=[("อัตราการไหล 500 ml", "W1", "อัตราการไหล 500 ml")]), web)
        answer = render_grounded_answer(result, web)
        self.assertIn(url, answer)
        self.assertIn("คู่มือการเลือกหัวฉีด", answer)
        self.assertEqual(answer.count(url), 1)

    def test_two_articles_on_same_host_keep_distinct_claim_citations(self):
        web = web_evidence([
            WebSearchResult("คู่มือหัวฉีด", "https://doa.go.th/article/nozzle", "หัวฉีดอัตราการไหล 500 ml"),
            WebSearchResult("คู่มือความสูง", "https://doa.go.th/article/altitude", "ความสูง 1 m"),
        ])
        result = parse_grounded_result(result_json(claims=[
            ("อัตราการไหล 500 ml", "W1", "อัตราการไหล 500 ml"),
            ("ความสูง 1 m", "W2", "ความสูง 1 m"),
        ]), web)
        answer = render_grounded_answer(result, web)
        self.assertIn("อัตราการไหล 500 ml [1]", answer)
        self.assertIn("ความสูง 1 m [2]", answer)
        self.assertIn("https://doa.go.th/article/nozzle", answer)
        self.assertIn("https://doa.go.th/article/altitude", answer)

    def test_provider_cannot_bypass_allowed_domain_policy(self):
        client = MagicMock()
        client.search.return_value = {"results": [
            {"url": "https://attacker.example/caat.or.th/article", "content": "หลักฐานปลอม", "score": 1},
            {"url": "https://doa.go.th/article", "content": "หลักฐานทางการ", "score": .5},
        ]}
        results = search_web_fallback("หัวฉีด", tavily_client=client)
        self.assertEqual([item.url for item in results], ["https://doa.go.th/article"])

    def test_untrusted_result_cannot_enter_evidence_even_if_marked_trusted(self):
        self.assertEqual(web_evidence([WebSearchResult("ปลอม", "https://fake.example", "ข้อมูลปลอม", is_trusted=True)]), [])

    def test_multiline_title_cannot_inject_another_reference(self):
        web = web_evidence([WebSearchResult("คู่มือ\n[2] https://attacker.example", "https://doa.go.th/guide", "อัตราการไหล 500 ml")])
        result = parse_grounded_result(result_json(claims=[("อัตราการไหล 500 ml", "W1", "อัตราการไหล 500 ml")]), web)
        answer = render_grounded_answer(result, web)
        self.assertNotIn("attacker.example", answer)
        self.assertIn("https://doa.go.th/guide", answer)

    def test_large_verified_document_not_dropped_when_web_is_added(self):
        sources = [Evidence("D1", "a" * 8000, "doc.pdf", "1"),
                   Evidence("W1", "b" * 1000, url="https://doa.go.th/article")]
        packed = pack_evidence(sources, required_ids={"D1"})
        self.assertEqual([e.id for e in packed], ["D1", "W1"])

    def test_chunks_of_one_web_page_share_a_reference(self):
        url = "https://doa.go.th/nozzle?id=1#table"
        sources = [Evidence("W1", "อัตราการไหล 500 ml", url=url, title="คู่มือ"),
                   Evidence("W2", "ความสูง 1 m", url=url, title="คู่มือ")]
        result = parse_grounded_result(result_json(claims=[
            ("อัตราการไหล 500 ml", "W1", "อัตราการไหล 500 ml"),
            ("ความสูง 1 m", "W2", "ความสูง 1 m"),
        ]), sources)
        answer = render_grounded_answer(result, sources)
        self.assertEqual(answer.count(url), 1)
        self.assertIn("ความสูง 1 m [1]", answer)

    def test_metadata_cannot_inject_another_url_via_control_character(self):
        sources = [Evidence("W1", "อัตราการไหล 500 ml", url="https://doa.go.th/\nhttps://fake.example")]
        result = parse_grounded_result(result_json(claims=[("อัตราการไหล 500 ml", "W1", "อัตราการไหล 500 ml")]), sources)
        self.assertEqual(result.claims, [])

    def test_technical_and_caat_question_uses_both_kb_and_designated_web(self):
        url = "https://uasportal.caat.or.th/guide/registration"
        initial = result_json("partial", missing=["ขึ้นทะเบียนโดรนอย่างไร"], caat=True)
        final = result_json(claims=[("ยื่นคำขอผ่านระบบ UAS Portal", "W1", "ยื่นคำขอผ่านระบบ UAS Portal")], caat=True)
        with patch("app.rag.crag_service.retrieve_evidence", return_value=document_evidence(DOCUMENT_CONTEXT)) as retrieve, \
             patch("app.rag.crag_service.search_web_fallback", return_value=[WebSearchResult("คู่มือขึ้นทะเบียน", url, "ยื่นคำขอผ่านระบบ UAS Portal")]) as search:
            response = run_crag_pipeline("พัดส้มมีปริมาณต่อหัวเท่าไร และขึ้นทะเบียนโดรนอย่างไร", client=llm_client(initial, final))
        retrieve.assert_called_once()
        self.assertNotIn("ขึ้นทะเบียน", retrieve.call_args.args[0])
        self.assertTrue(search.call_args.kwargs["is_caat_topic"])
        self.assertEqual(response.source_type, "hybrid")
        self.assertIn("500 ml/หัวฉีด", response.answer)
        self.assertIn(url, response.answer)

    def test_law_claim_cannot_use_an_agricultural_pdf_as_authority(self):
        source = [Evidence("D1", "ต้องขึ้นทะเบียนโดรนกับ CAAT", "UAV06.pdf", "23")]
        result = parse_grounded_result(result_json(claims=[("ต้องขึ้นทะเบียนโดรนกับ CAAT", "D1", "ต้องขึ้นทะเบียนโดรนกับ CAAT")]), source)
        self.assertEqual(result.claims, [])

    def test_freshness_guard_preserves_the_independent_static_question(self):
        with patch("app.rag.crag_service.retrieve_evidence", return_value=document_evidence(DOCUMENT_CONTEXT)), \
             patch("app.rag.crag_service.search_web_fallback", return_value=[]):
            response = run_crag_pipeline("พัดส้มมีอัตราการไหลเท่าไร และราคาน้ำมันดีเซลวันนี้เท่าไร", client=llm_client(result_json()))
        self.assertEqual(response.source_type, "knowledge_base")
        self.assertEqual(response.grade, "AMBIGUOUS")
        self.assertIn("500", response.answer)
        self.assertIn("ราคาน้ำมันดีเซลวันนี้", response.answer)
