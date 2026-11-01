import unittest

from app.rag.candidate.verifier import (
    clean_chat_formatting,
    extract_markers,
    verify_and_render_candidate,
)
from app.rag.evidence import CHEMICAL_NOTE, Evidence


class TestCandidateVerifier(unittest.TestCase):
    def setUp(self):
        self.evidence_d1 = Evidence(
            id="D1",
            content="เตรียมอุปกรณ์โดรนก่อนลงพื้นที่: แบตเตอรี่เต็ม 25.2 V ไม่ควรให้ต่ำกว่า 25.0 V",
            source_file="UAV11 โดรนสำรวจ.pdf",
            page_number="6",
        )
        self.evidence_d2 = Evidence(
            id="D2",
            content="การใช้งานโดรนเกษตร: ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% ขณะบิน",
            source_file="ฟีเจอร์โดรนของฉัน.pdf",
            page_number="3",
        )
        self.evidence_w1 = Evidence(
            id="W1",
            content="ข้อบังคับการบินโดรน กพท. ต้องมีประกันบุคคลภายนอกวงเงิน 1,000,000 บาท",
            url="https://uasportal.caat.or.th/insurance",
            title="CAAT UAS Portal",
        )
        self.evidence_chem = Evidence(
            id="D3",
            content="การพ่นสารกำจัดวัชพืช อัตรา 250 ซีซี ต่อไร่ ฉีดพ่นให้ทั่วถึง",
            source_file="UAV08 การใช้สาร.pdf",
            page_number="5",
        )

    def test_positive_verification_and_numbered_rendering(self):
        raw = (
            "• ก่อนลงพื้นที่ (โดรนสำรวจ): ตรวจเช็คแบตเตอรี่เต็ม 25.2 V และไม่ควรต่ำกว่า 25.0 V [D1]\n"
            "• ขณะบิน: ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% [D2]"
        )
        result = verify_and_render_candidate(raw, [self.evidence_d1, self.evidence_d2])

        self.assertTrue(result.passed_citations)
        self.assertFalse(result.is_not_found)
        self.assertEqual(len(result.dropped_reasons), 0)
        self.assertEqual(len(result.unverified_numbers), 0)

        # Citations are renumbered into [1] and [2]
        self.assertIn("[1]", result.rendered_text)
        self.assertIn("[2]", result.rendered_text)
        self.assertIn("แหล่งอ้างอิง:\n[1] UAV11 โดรนสำรวจ.pdf, หน้า 6\n[2] ฟีเจอร์โดรนของฉัน.pdf, หน้า 3", result.rendered_text)

    def test_negative_unknown_source_id_rejected(self):
        raw = "ข้อความที่อ้างแหล่งที่ไม่มีอยู่จริง [D99]"
        result = verify_and_render_candidate(raw, [self.evidence_d1])

        self.assertFalse(result.passed_citations)
        self.assertTrue(any("unknown source ids" in reason.lower() for reason in result.dropped_reasons))
        self.assertTrue(result.is_not_found)  # no valid lines survived

    def test_negative_unsupported_numbers_rejected(self):
        # 99.9 V is not in D1
        raw = "ตรวจเช็คแบตเตอรี่ไม่ควรต่ำกว่า 99.9 V [D1]"
        result = verify_and_render_candidate(raw, [self.evidence_d1])

        self.assertFalse(result.passed_citations)
        self.assertTrue(len(result.unverified_numbers) > 0)
        self.assertTrue(any("unsupported numbers" in r.lower() for r in result.dropped_reasons))

    def test_negative_numbers_without_citations_rejected(self):
        raw = "เกณฑ์ทั่วไปคือ 500 V โดยไม่มีแหล่งอ้างอิง"
        result = verify_and_render_candidate(raw, [self.evidence_d1])

        self.assertFalse(result.passed_citations)
        self.assertTrue(any("has no source" in r.lower() or "ungrounded" in r.lower() for r in result.dropped_reasons))

    def test_money_notation_equivalence_passes(self):
        raw = "วงเงินประกันต้องไม่น้อยกว่า 1 ล้านบาท [W1]"
        result = verify_and_render_candidate(raw, [self.evidence_w1])

        self.assertTrue(result.passed_citations)
        self.assertIn("1 ล้านบาท [1]", result.rendered_text)
        self.assertIn("https://uasportal.caat.or.th/insurance", result.rendered_text)

    def test_non_numeric_warnings_and_lists_preserved(self):
        raw = (
            "• ก่อนลงพื้นที่: ตรวจเช็คแบตเตอรี่เต็ม 25.2 V [D1]\n"
            "• คำเตือน: ตรวจสอบความสมบูรณ์ของใบพัดและตัวเครื่องก่อนเริ่มภารกิจ [D1]"
        )
        result = verify_and_render_candidate(raw, [self.evidence_d1])
        self.assertTrue(result.passed_citations)
        self.assertIn("คำเตือน: ตรวจสอบความสมบูรณ์ของใบพัด", result.rendered_text)

    def test_not_found_handling(self):
        result = verify_and_render_candidate("NOT_FOUND", [self.evidence_d1])
        self.assertTrue(result.is_not_found)

    def test_gap_missing_aspect_extracted(self):
        raw = (
            "• ขณะบิน: ห้ามใช้แบตเตอรี่จนต่ำกว่า 30% [D2]\n"
            "ยังไม่พบข้อมูล: อัตราการคายประจุสูงสุดในสภาพอากาศร้อนจัด"
        )
        result = verify_and_render_candidate(raw, [self.evidence_d2])
        self.assertTrue(result.passed_citations)
        self.assertEqual(result.missing_aspect, "อัตราการคายประจุสูงสุดในสภาพอากาศร้อนจัด")
        self.assertIn("ยังไม่พบข้อมูล: อัตราการคายประจุสูงสุดในสภาพอากาศร้อนจัด", result.rendered_text)

    def test_chemical_and_caat_notes_attached(self):
        chem_raw = "• พ่นสารอัตรา 250 ซีซี ต่อไร่ [D3]"
        chem_res = verify_and_render_candidate(chem_raw, [self.evidence_chem])
        self.assertIn(CHEMICAL_NOTE, chem_res.rendered_text)

        caat_raw = "• ต้องมีประกัน 1,000,000 บาท [W1]"
        caat_res = verify_and_render_candidate(caat_raw, [self.evidence_w1])
        self.assertIn("https://uasportal.caat.or.th", caat_res.rendered_text)

    def test_wrong_unit_cannot_use_a_matching_number(self):
        evidence = [Evidence('D1', 'ปั๊มเอมีปริมาณ 500 ml', 'pumps.pdf', '1')]
        result = verify_and_render_candidate('ปั๊มเอมีปริมาณ 500 ลิตร [D1]', evidence)
        self.assertNotIn('500 ลิตร', result.rendered_text, 'A numeric match does not support a different unit')

    def test_wrong_table_row_cannot_use_another_rows_number(self):
        evidence = [Evidence('D1', 'ปั๊ม | ปริมาณ (ml)\nปั๊มอัลฟา | 250\nปั๊มเบตา | 500', 'pumps.pdf', '1')]
        result = verify_and_render_candidate('ปั๊มอัลฟามีปริมาณ 500 ml [D1]', evidence)
        self.assertNotIn('ปั๊มอัลฟามีปริมาณ 500 ml', result.rendered_text, 'A real table cell is attached to the wrong row')

    def test_fact_with_no_source_must_not_be_a_citation_pass(self):
        result = verify_and_render_candidate('ใช้สารชนิดนี้ได้กับพืชทุกระยะ', [])
        self.assertFalse(result.passed_citations and not result.is_not_found,
                         'The renderer returned an answer and citation pass without any source')

    def test_valid_list_under_cited_heading_does_not_disappear(self):
        evidence = [Evidence('D1', 'ปั๊ม | ปริมาณ (ml)\nปั๊มอัลฟา | 250\nปั๊มเบตา | 500', 'pumps.pdf', '1')]
        raw = 'ปริมาณของปั๊มแต่ละรุ่นมีดังนี้ [D1]\n• ปั๊มอัลฟา 250 ml\n• ปั๊มเบตา 500 ml'
        result = verify_and_render_candidate(raw, evidence)
        self.assertIn('250 ml', result.rendered_text, 'Correct list items were silently removed')
        self.assertIn('500 ml', result.rendered_text)

    def test_caat_rules_cannot_be_supported_by_an_arbitrary_kb_page(self):
        evidence = [Evidence('D1', 'ต้องทำประกันภัยโดรนวงเงิน 123 บาท', 'old-slide.pdf', '1')]
        result = verify_and_render_candidate('ต้องทำประกันภัยโดรนวงเงิน 123 บาท [D1]', evidence)
        self.assertNotIn('ต้องทำประกันภัยโดรนวงเงิน 123 บาท', result.rendered_text,
                         'Project source policy requires actual CAAT evidence for drone rules')


if __name__ == "__main__":
    unittest.main()
