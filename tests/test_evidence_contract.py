import json
import unittest

from app.rag.evidence import ABSTAIN_MESSAGE, Evidence, document_evidence, pack_evidence, parse_grounded_result, render_grounded_answer
from tests.helpers import DOCUMENT_CONTEXT, result_json


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.sources = document_evidence(DOCUMENT_CONTEXT)

    def test_file_page_content_preserved(self):
        self.assertEqual((self.sources[0].source_file, self.sources[0].page_number), ("UAV07.pdf", "12"))
        self.assertIn("1600 rpm", self.sources[0].content)

    def test_excluded_sources_and_missing_metadata_not_citable(self):
        for context in [DOCUMENT_CONTEXT.replace("UAV07.pdf", "UAV01 Air Law.pdf"), DOCUMENT_CONTEXT.replace("หน้า: 12", "หน้า: unknown"), "no metadata"]:
            with self.subTest(context=context[:60]):
                self.assertEqual(document_evidence(context), [])

    def test_citations_built_from_metadata_and_mapped_to_claims(self):
        result = parse_grounded_result(result_json(), self.sources)
        answer = render_grounded_answer(result, self.sources)
        self.assertIn("500 ml/หัวฉีด", answer)
        self.assertIn("1600 rpm", answer)
        self.assertIn("[1] UAV07.pdf, หน้า 12", answer)
        self.assertEqual(answer.count("แหล่งอ้างอิง:"), 1)

    def test_unknown_source_id_rejected(self):
        raw = result_json(claims=[("คำตอบ", "invented.pdf", "อัตราการไหล")])
        self.assertEqual(parse_grounded_result(raw, self.sources).status, "insufficient")

    def test_quote_must_exist_in_source(self):
        raw = result_json(claims=[("คำตอบ", "D1", "ไม่มีข้อความนี้ในหลักฐาน")])
        self.assertEqual(parse_grounded_result(raw, self.sources).claims, [])

    def test_unsupported_number_rejected(self):
        raw = result_json(claims=[("อัตราการไหล 999 ml", "D1", "อัตราการไหล 500 ml/หัวฉีด")])
        self.assertEqual(parse_grounded_result(raw, self.sources).claims, [])

    def test_equal_numeric_notation_not_rejected(self):
        raw = result_json(claims=[("ที่ความสูง 1 m หน้ากว้าง 2.8 m", "D1", "ความสูง 1.0 m หน้ากว้างพ่น 2.8 m ต่อหัวฉีด")])
        self.assertEqual(parse_grounded_result(raw, self.sources).status, "sufficient")

    def test_quote_whitespace_can_differ_without_changing_facts(self):
        raw = result_json(claims=[("อัตราการไหล 500 ml/หัวฉีด", "D1", "อัตราการไหล\n500 ml/หัวฉีด")])
        self.assertEqual(parse_grounded_result(raw, self.sources).status, "sufficient")

    def test_fabricated_inline_reference_rejected(self):
        for text in ["อ้างอิง invented.pdf", "ดู https://fake.example", "แหล่งอ้างอิง: test"]:
            self.assertEqual(parse_grounded_result(result_json(claims=[(text, "D1", "อัตราการไหล")]), self.sources).claims, [])

    def test_json_and_status_validation(self):
        for raw in ["{", "[]", "คิดว่า CORRECT", '{"status":"unknown"}', result_json("sufficient", claims=[]), result_json("partial", missing=[]), result_json("sufficient", missing=["ราคา"])]:
            with self.subTest(raw=raw[:80]):
                self.assertEqual(parse_grounded_result(raw, self.sources).status, "insufficient")

    def test_boolean_strings_not_accepted(self):
        data = json.loads(result_json())
        data["is_caat_topic"] = "false"
        self.assertEqual(parse_grounded_result(json.dumps(data), self.sources).claims, [])

    def test_partial_answer_identifies_missing_aspects(self):
        result = parse_grounded_result(result_json("partial", missing=["ราคาหัวฉีดปัจจุบัน"]), self.sources)
        answer = render_grounded_answer(result, self.sources)
        self.assertIn("ยังยืนยันไม่ได้: ราคาหัวฉีดปัจจุบัน", answer)
        self.assertIn("UAV07.pdf", answer)

    def test_overlong_answer_rejected_without_cutting_citations(self):
        raw = result_json(claims=[("ก" * 401, "D1", "อัตราการไหล")])
        self.assertEqual(render_grounded_answer(parse_grounded_result(raw, self.sources), self.sources), ABSTAIN_MESSAGE)

    def test_packing_preserves_whole_blocks_and_balances_web(self):
        sources = [Evidence("D1", "ก" * 600, "doc.pdf", "1"), Evidence("D2", "ข" * 600, "doc.pdf", "2"), Evidence("W1", "ค" * 600, url="https://doa.go.th/test")]
        packed = pack_evidence(sources, budget=2000)
        self.assertEqual([e.id for e in packed], ["D1", "W1"])
        self.assertEqual(packed[0].content, sources[0].content)
        self.assertLessEqual(sum(len(json.dumps(e.__dict__, ensure_ascii=False)) for e in packed), 2000)

    def test_only_used_sources_appear_in_answer(self):
        sources = self.sources + [Evidence("W1", "irrelevant", url="https://unused.example")]
        answer = render_grounded_answer(parse_grounded_result(result_json(), sources), sources)
        self.assertNotIn("unused.example", answer)
