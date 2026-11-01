import unittest

from app.rag.candidate.context_filter import (
    detect_operational_scope,
    extract_keywords,
    score_evidence,
    scope_and_filter_context,
)
from app.rag.evidence import Evidence


class TestCandidateContextFilter(unittest.TestCase):
    def setUp(self):
        self.battery_survey_chunk = Evidence(
            id="D1",
            content="เตรียมอุปกรณ์โดรน ก่อนลงพื้นที่ภาคสนาม 2. Battery เช็คว่าเต็มไหม (25.2 V) ไม่ควรให้ต่ำกว่า 25.0 V",
            source_file="UAV11 การสาธิตการใช้โดรนสำรวจ.pdf",
            page_number="6",
        )
        self.battery_flight_chunk = Evidence(
            id="D2",
            content="การดูแลรักษาโดรน หมายเหตุ: ห้ามใช้แบตจนต่ำกว่า 30% ขณะบิน",
            source_file="ฟีเจอร์โดรนของฉัน.pdf",
            page_number="3",
        )
        self.rtf_pricing_chunk = Evidence(
            id="D3",
            content="ตารางที่ 4 ข้อมูลรายการโดรนเกษตรทุกรุ่นในไทยพร้อมราคาแพ็กเกจพร้อมบิน DJI AGRAS T10 ราคา RTF โดยประมาณ 220,250 บาท ตัวลำ, รีโมท, แบตเตอรี่ x1ชุด",
            source_file="ฟีเจอร์การลงทุน.pdf",
            page_number="10",
        )
        self.bonsucro_chunk = Evidence(
            id="D4",
            content="มาตรฐาน Bonsucro ในบราซิล สัดส่วนยอดขายน้ำตาล Tangible Benefits 31% Commercial benefits",
            source_file="UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf",
            page_number="12",
        )

    def test_battery_query_prioritizes_relevant_and_filters_unrequested_tables(self):
        query = "แบตเท่าไหร่ห้ามบิน"
        all_chunks = [
            self.bonsucro_chunk,
            self.rtf_pricing_chunk,
            self.battery_flight_chunk,
            self.battery_survey_chunk,
        ]

        selected, pre_sel, post_sel, drop_notes = scope_and_filter_context(
            query, all_chunks, max_chunks=3, min_score=0.5
        )

        # Pre selection records all 4
        self.assertEqual(len(pre_sel), 4)

        # Selected should keep the two battery chunks
        selected_files = [e.source_file for e in selected]
        self.assertIn("ฟีเจอร์โดรนของฉัน.pdf", selected_files)
        self.assertIn("UAV11 การสาธิตการใช้โดรนสำรวจ.pdf", selected_files)

        # Bonsucro and RTF pricing tables should be deprioritized/dropped
        self.assertNotIn("UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf", selected_files)

        # Post selection contains operational scopes and scores
        self.assertTrue(len(post_sel) >= 2)
        survey_post = next(p for p in post_sel if p["source_file"] == "UAV11 การสาธิตการใช้โดรนสำรวจ.pdf")
        self.assertIn("โดรนสำรวจ", survey_post["operational_scope"])
        self.assertIn("ก่อนขึ้นบิน/ก่อนลงพื้นที่", survey_post["operational_scope"])

    def test_deduplicates_exact_same_page(self):
        duplicate_chunk = Evidence(
            id="D2_dup",
            content="การดูแลรักษาโดรน หมายเหตุ: ห้ามใช้แบตจนต่ำกว่า 30% ขณะบิน (ซ้ำ)",
            source_file="ฟีเจอร์โดรนของฉัน.pdf",
            page_number="3",
        )
        selected, _, _, drop_notes = scope_and_filter_context(
            "แบตขณะบิน", [self.battery_flight_chunk, duplicate_chunk], max_chunks=5
        )
        self.assertEqual(len(selected), 1)
        self.assertTrue(any("Deduplicated duplicate page" in note for note in drop_notes))

    def test_detect_operational_scope_identifies_contexts(self):
        scope1 = detect_operational_scope("ก่อนลงพื้นที่ ตรวจเช็คสายไฟ", "UAV11 โดรนสำรวจ.pdf")
        self.assertIn("โดรนสำรวจ", scope1)
        self.assertIn("ก่อนขึ้นบิน/ก่อนลงพื้นที่", scope1)

        scope2 = detect_operational_scope("ฉีดพ่น ห้ามใช้แบตเตอรี่ต่ำกว่า 30% ขณะบิน", "ฟีเจอร์โดรนของฉัน.pdf")
        self.assertIn("ขณะบิน", scope2)

    def test_thai_question_keeps_the_only_answering_page(self):
        evidence = [
            Evidence('D1', 'ตรวจใบพัดว่ามีรอยร้าวหรือไม่', 'propellers.pdf', '1'),
            Evidence('D2', 'ควรเก็บอุปกรณ์ในที่แห้ง', 'storage.pdf', '2'),
            Evidence('D3', 'ปั๊มรุ่นแกมมามีอัตราการไหล 250 ml/min', 'pumps.pdf', '3'),
        ]
        selected, _, _, _ = scope_and_filter_context('ปั๊มรุ่นแกมมาใช้อัตราการไหลเท่าไร', evidence)
        self.assertIn('pumps.pdf', [item.source_file for item in selected],
                      'The only answering evidence was discarded for a normal unspaced Thai query')

    def test_empty_evidence_handled_gracefully(self):
        selected, pre, post, notes = scope_and_filter_context("คำถาม", [])
        self.assertEqual(selected, [])
        self.assertEqual(pre, [])
        self.assertEqual(post, [])


if __name__ == "__main__":
    unittest.main()
