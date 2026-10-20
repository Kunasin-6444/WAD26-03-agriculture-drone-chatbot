"""ANSWER_MODE=natural: a plain answer with [Dn] markers, checked line by line, web only when needed."""
import os
import unittest
from unittest.mock import MagicMock, patch

from app.rag import natural_answer as na
from app.rag.crag_service import run_crag_pipeline
from app.rag.evidence import CHEMICAL_NOTE, Evidence, document_evidence
from app.rag.web_fallback import WebSearchResult
from tests.helpers import DOCUMENT_CONTEXT, llm_client

NOZZLE = Evidence("D1", "หัวฉีดพัดส้ม อัตราการไหล 500 ml/หัวฉีด ที่รอบ 1600 rpm\nความสูง 1.0 m หน้ากว้างพ่น 2.8 m ต่อหัวฉีด",
                  "UAV07.pdf", "12")
PESTS = Evidence("D2", "ชื่อศัตรูพืช | ชื่อสาร | อัตราส่วน | วัชพืชที่ควบคุมได้\n"
                       "หนอนเอ | สารอัลฟา 5% | 20 มล./น้ำ 20 ลิตร | ใบแคบ\n"
                       "หนอนบี | สารเบตา 10% | 80 กรัม/น้ำ 20 ลิตร | ใบแคบและกว้าง", "ฟีเจอร์ผสมสาร.pdf", "7")


class Rendering(unittest.TestCase):
    def test_markers_become_numbered_references_built_from_metadata(self):
        answer = na.render("หัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]\n• ที่รอบ 1600 rpm [D1]", [NOZZLE])
        self.assertIn("หัวฉีดพัดส้มไหล 500 ml/หัวฉีด [1]", answer.text)
        self.assertIn("[1] UAV07.pdf, หน้า 12", answer.text)
        self.assertNotIn("D1", answer.text)
        self.assertEqual(answer.used_ids, ["D1"])

    def test_a_line_with_an_unsupported_number_or_unknown_source_is_dropped_and_said(self):
        answer = na.render("หัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]\nหัวฉีดพัดส้มไหล 900 ml/หัวฉีด [D1]\nราคา 120 บาท [D9]", [NOZZLE])
        self.assertIn("500 ml", answer.text)
        self.assertNotIn("900", answer.text)
        self.assertNotIn("120 บาท", answer.text)
        self.assertEqual(len(answer.dropped), 2)
        self.assertIn(na.GAP_LABEL + na.DROPPED_GAP, answer.text)

    def test_the_table_row_checks_apply_to_each_line(self):
        answer = na.render("หนอนเอใช้สารอัลฟา 5% อัตราส่วน 80 กรัม/น้ำ 20 ลิตร [D2]\n"
                           "หนอนบีใช้สารเบตา 10% อัตราส่วน 80 กรัม/น้ำ 20 ลิตร [D2]", [PESTS])
        self.assertNotIn("หนอนเอ", answer.text)
        self.assertIn("หนอนบี", answer.text)
        self.assertIn(CHEMICAL_NOTE, answer.text)

    def test_not_found_gap_lines_list_numbers_and_model_footers(self):
        self.assertTrue(na.render("NOT_FOUND", [NOZZLE]).not_found)
        answer = na.render("หัวฉีดพัดส้มมีข้อมูลดังนี้\n1. ไหล 500 ml/หัวฉีด [D1]\nยังไม่พบข้อมูล: ราคา\nแหล่งอ้างอิง:", [NOZZLE])
        self.assertIn("หัวฉีดพัดส้มมีข้อมูลดังนี้", answer.text)   # a lead-in without numbers needs no source
        self.assertIn(na.GAP_LABEL + "ราคา", answer.text)
        self.assertEqual(answer.text.count("แหล่งอ้างอิง:"), 1)
        self.assertEqual(answer.dropped, [])

    def test_list_items_under_a_marked_heading_are_checked_against_its_source(self):
        answer = na.render("สารที่ใช้กับหนอน มีดังนี้ [D2]\n• หนอนบีใช้สารเบตา 10% อัตราส่วน 80 กรัม/น้ำ 20 ลิตร\n"
                           "• หนอนเอใช้สารอัลฟา 5% อัตราส่วน 80 กรัม/น้ำ 20 ลิตร", [PESTS])
        self.assertIn("หนอนบีใช้สารเบตา 10%", answer.text)     # inherited [D2] and passed
        self.assertNotIn("หนอนเอ", answer.text)                  # inherited [D2] and failed the row check
        self.assertEqual(answer.text.split("แหล่งอ้างอิง:")[0].count("[1]"), 1)  # only the heading shows it

    def test_markdown_the_chat_cannot_show_is_removed(self):
        answer = na.render("### อัตราการไหล\n**หัวฉีดพัดส้ม** ไหล 500 ml/หัวฉีด [D1]", [NOZZLE])
        self.assertNotIn("**", answer.text)
        self.assertNotIn("#", answer.text)
        self.assertIn("หัวฉีดพัดส้ม ไหล 500 ml/หัวฉีด [1]", answer.text)

    def test_an_answer_whose_every_fact_failed_shows_nothing(self):
        answer = na.render("หัวฉีดพัดส้มไหล 900 ml/หัวฉีด [D1]", [NOZZLE])
        self.assertEqual(answer.text, "")
        self.assertFalse(answer.not_found)


class NaturalPipeline(unittest.TestCase):
    def setUp(self):
        patches = [patch.dict(os.environ, {"ANSWER_MODE": "natural"}),
                   patch("app.rag.crag_service.retrieve_evidence", return_value=document_evidence(DOCUMENT_CONTEXT)),
                   patch("app.rag.crag_service.search_web_fallback", return_value=[])]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        from app.rag import crag_service
        self.search = crag_service.search_web_fallback

    def test_a_document_answer_takes_one_call_and_no_web(self):
        client = llm_client("หัวฉีดพัดส้มมีอัตราการไหล 500 ml/หัวฉีด ที่ 1600 rpm [D1]")
        response = run_crag_pipeline("พัดส้มมีอัตราการไหลเท่าไร", client=client)
        self.assertEqual((response.source_type, response.grade), ("knowledge_base", "CORRECT"))
        self.assertIn("UAV07.pdf, หน้า 12", response.answer)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.search.assert_not_called()
        self.assertNotIn("response_format", client.chat.completions.create.call_args.kwargs)

    def test_documents_without_the_answer_send_it_to_the_web_once(self):
        self.search.return_value = [WebSearchResult("ราคาหัวฉีด", "https://doa.go.th/nozzle", "หัวฉีดราคา 120 บาท", 0.9)]
        client = llm_client("NOT_FOUND", "หัวฉีดราคา 120 บาท [W1]")
        response = run_crag_pipeline("หัวฉีดพัดส้มราคาเท่าไร", client=client)
        self.search.assert_called_once()
        self.assertEqual(response.source_type, "web_fallback")
        self.assertIn("https://doa.go.th/nozzle", response.answer)

    def test_a_current_information_question_searches_the_web_up_front_in_one_call(self):
        self.search.return_value = [WebSearchResult("ราคาน้ำมัน", "https://www.pttor.com/price", "ดีเซลวันนี้ 32.94 บาท", 0.9)]
        client = llm_client("หัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]\nดีเซลวันนี้ 32.94 บาท [W1]")
        response = run_crag_pipeline("พัดส้มไหลเท่าไร และราคาดีเซลวันนี้", client=client)
        self.search.assert_called_once()
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertEqual(response.source_type, "hybrid")

    def test_a_model_failure_reports_the_outage_and_skips_the_web(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = TimeoutError("slow")
        response = run_crag_pipeline("พัดส้มมีอัตราการไหลเท่าไร", client=client)
        self.search.assert_not_called()
        self.assertTrue(response.error_code)
        self.assertNotIn("ยังไม่พบหลักฐานเพียงพอ", response.answer)

    def test_the_default_mode_is_still_the_json_claims_path(self):
        with patch.dict(os.environ, {"ANSWER_MODE": ""}):
            from app.rag.crag_service import answer_mode
            self.assertEqual(answer_mode(), "grounded")


class InsuranceCover(unittest.TestCase):
    def test_required_cover_is_drone_regulation_but_a_cost_table_premium_is_not(self):
        from app.rag.evidence import _is_aviation_regulation
        self.assertTrue(_is_aviation_regulation("ประกันภัยโดรนต้องมีวงเงินคุ้มครองไม่น้อยกว่า 1 ล้านบาท"))
        self.assertFalse(_is_aviation_regulation("ค่าประกันภัยโดรน 20,000 บาทต่อลำต่อปี"))
        news = Evidence("W1", "ประกันภัยโดรนต้องมีวงเงินคุ้มครองไม่น้อยกว่า 1 ล้านบาท", url="https://www.thaipbs.or.th/news/1",
                        title="ข่าว")
        answer = na.render("ประกันภัยโดรนต้องมีวงเงินคุ้มครองไม่น้อยกว่า 1 ล้านบาท [W1]", [news])
        self.assertEqual(answer.text, "")   # only an official CAAT page may state the requirement

    def test_a_web_page_mentioning_hazardous_goods_does_not_add_the_chemical_note(self):
        caat = Evidence("W1", "ประกันภัยวงเงินไม่ต่ำกว่า 1 ล้านบาท ห้ามบรรทุกวัตถุอันตราย",
                        url="https://uasportal.caat.or.th/guide.pdf", title="คู่มือ")
        answer = na.render("ประกันภัยโดรนต้องมีวงเงินไม่ต่ำกว่า 1 ล้านบาท [W1]", [caat])
        self.assertIn("1 ล้านบาท", answer.text)
        self.assertNotIn(CHEMICAL_NOTE, answer.text)


class IdLeak(unittest.TestCase):
    def test_a_source_id_written_into_the_prose_never_reaches_the_user(self):
        answer = na.render("ส่วน D1 ระบุว่าหัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]", [NOZZLE])
        self.assertNotIn("D1", answer.text)
        self.assertIn("ส่วน เอกสาร [1] ระบุว่า", answer.text)
        coded = Evidence("D1", "หัวฉีดรุ่น W2 ไหล 500 ml/หัวฉีด", "UAV07.pdf", "12")
        self.assertIn("รุ่น W2", na.render("หัวฉีดรุ่น W2 ไหล 500 ml/หัวฉีด [D1]", [coded]).text)  # not a source id


if __name__ == "__main__":
    unittest.main()


class InsuranceRouting(unittest.TestCase):
    def setUp(self):
        patches = [patch.dict(os.environ, {"ANSWER_MODE": "natural"}),
                   patch("app.rag.crag_service.retrieve_evidence", return_value=document_evidence(DOCUMENT_CONTEXT)),
                   patch("app.rag.crag_service.search_web_fallback", return_value=[
                       WebSearchResult("คู่มือ", "https://uasportal.caat.or.th/guide.pdf",
                                       "ประกันภัยโดรนต้องมีวงเงินคุ้มครองไม่ต่ำกว่า 1 ล้านบาท", 0.9)])]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        from app.rag import crag_service
        self.search, self.retrieve = crag_service.search_web_fallback, crag_service.retrieve_evidence

    def test_a_general_insurance_question_reads_documents_and_the_caat_page_up_front(self):
        client = llm_client("ประกันภัยโดรนต้องมีวงเงินคุ้มครองไม่ต่ำกว่า 1 ล้านบาท [W1]")
        response = run_crag_pipeline("อยากทราบประกันของโดรน", client=client)
        self.retrieve.assert_called_once()
        self.assertTrue(self.search.call_args.kwargs["is_caat_topic"])
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.assertIn("1 ล้านบาท", response.answer)

    def test_a_rule_stated_from_a_document_fetches_the_caat_page_and_answers_again(self):
        client = llm_client("หัวฉีดพัดส้มต้องบินโดรนสูงไม่เกิน 90 เมตรตามกฎ กพท. [D1]",
                            "ประกันภัยโดรนต้องมีวงเงินคุ้มครองไม่ต่ำกว่า 1 ล้านบาท [W1]")
        response = run_crag_pipeline("พัดส้มมีอัตราการไหลเท่าไร", client=client)
        self.search.assert_called_once()
        self.assertTrue(self.search.call_args.kwargs["is_caat_topic"])
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertIn("uasportal.caat.or.th", response.answer)
