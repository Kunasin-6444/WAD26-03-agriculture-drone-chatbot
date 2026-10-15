import unittest

from app.rag.claim_consistency import claim_inconsistency
from app.rag.evidence import Evidence, parse_grounded_result
from tests.helpers import result_json

NOZZLE_TABLE = ("อัตราการไหลของหัวฉีด (ml/หัวฉีด) ที่รอบ 1600 rpm\n"
                "1 | พัดส้ม | 1600 | 500 | 1500\n2 | พัดน้ำเงิน | 1600 | 950 | 2850")
WEED_PAGE = "สารกำจัดวัชพืชในอ้อย อัตรา 200 กรัม/ไร่\nอาลาคลอร์ | ใบแคบและกว้าง | ก่อนงอก\nอะทราซีน | ใบกว้าง | หลังงอก"


class ClaimConsistencyTests(unittest.TestCase):
    def check(self, claim, quote, content):
        return claim_inconsistency(claim, [quote], content)

    def test_matching_claim_is_accepted(self):
        self.assertEqual(self.check("หัวฉีดพัดส้มมีอัตราการไหล 500 ml/หัวฉีด ที่ 1600 rpm",
                                    "1 | พัดส้ม | 1600 | 500 | 1500", NOZZLE_TABLE), "")

    def test_unit_conflicting_with_evidence_rejected_but_aliases_accepted(self):
        self.assertIn("unit", self.check("อัตราการไหล 500 ลิตร", "1 | พัดส้ม | 1600 | 500 | 1500", NOZZLE_TABLE))
        self.assertEqual(self.check("อัตราการไหล 500 มิลลิลิตร", "1 | พัดส้ม | 1600 | 500 | 1500", NOZZLE_TABLE), "")

    def test_implicit_unit_in_unitless_table_is_not_rejected(self):
        self.assertEqual(self.check("ที่ความสูง 1 เมตร หน้ากว้าง 2.8 เมตร", "1.0 | 2.8 | 4.5",
                                    "ความสูง | หน้ากว้าง\n1.0 | 2.8 | 4.5"), "")

    def test_latin_term_missing_from_evidence_rejected(self):
        self.assertIn("term", self.check("ใช้ glyphosate 200 กรัม/ไร่", "อัตรา 200 กรัม/ไร่", WEED_PAGE))
        self.assertEqual(self.check("ใช้ GSD 2 ซม.", "ค่า gsd 2 ซม.", "gsd 2 ซม./พิกเซล"), "")

    def test_nozzle_colour_swapped_onto_another_row_rejected(self):
        problem = self.check("หัวฉีดพัดส้มมีอัตราการไหล 950 ml", "2 | พัดน้ำเงิน | 1600 | 950 | 2850", NOZZLE_TABLE)
        self.assertIn("nozzle", problem)

    def test_nozzle_absent_from_evidence_rejected(self):
        self.assertIn("nozzle", self.check("หัวฉีดพัดแดงมีอัตราการไหล 500 ml", "500 | 1500", NOZZLE_TABLE))

    def test_nozzle_name_only_in_header_outside_quote_is_accepted(self):
        content = "พัดส้ม | พัดน้ำเงิน\nความสูง 1.0 m | 2.8 | 2.9"
        self.assertEqual(self.check("พัดส้มพ่นกว้าง 2.8 m ที่ความสูง 1.0 m", "ความสูง 1.0 m | 2.8 | 2.9", content), "")

    def test_crop_mismatch_rejected_and_longer_crop_not_confused_with_shorter(self):
        self.assertIn("crop", self.check("ในข้าวโพดใช้ 200 กรัม/ไร่", "อัตรา 200 กรัม/ไร่", WEED_PAGE))
        corn = "การกำจัดวัชพืชในข้าวโพด อัตรา 200 กรัม/ไร่"
        self.assertIn("crop", self.check("ในข้าวใช้ 200 กรัม/ไร่", "อัตรา 200 กรัม/ไร่", corn))
        self.assertEqual(self.check("ในข้าวโพดใช้ 200 กรัม/ไร่", "อัตรา 200 กรัม/ไร่", corn), "")

    def test_narrow_leaf_only_claim_on_combined_class_row_rejected(self):
        quote = "อาลาคลอร์ | ใบแคบและกว้าง | ก่อนงอก"
        self.assertIn("weed class", self.check("อาลาคลอร์ใช้ควบคุมวัชพืชใบแคบก่อนงอก", quote, WEED_PAGE))
        self.assertEqual(self.check("อาลาคลอร์ใช้ควบคุมวัชพืชใบแคบและใบกว้างก่อนงอก", quote, WEED_PAGE), "")

    def test_broadleaf_claim_on_other_class_quote_rejected(self):
        self.assertIn("weed class", self.check("อะทราซีนใช้กับวัชพืชใบแคบ", "อะทราซีน | ใบกว้าง | หลังงอก", WEED_PAGE))

    def test_class_name_with_category_word_and_trimmed_quote_is_accepted(self):
        # Two classes in separate cells, quote trimmed after the first one.
        content = "เพนดิเมทาลิน | วัชพืชที่งอกจากเมล็ดทั้งประเภทใบแคบ | ประเภทใบกว้าง"
        claim = "ควบคุมวัชพืชทั้งประเภทใบแคบและประเภทใบกว้าง"
        self.assertEqual(self.check(claim, "วัชพืชที่งอกจากเมล็ดทั้งประเภทใบแคบ", content), "")
        # ...but a class the evidence never names is still rejected.
        only_narrow = "เพนดิเมทาลิน | วัชพืชที่งอกจากเมล็ดทั้งประเภทใบแคบ"
        self.assertIn("weed class", self.check(claim, "วัชพืชที่งอกจากเมล็ดทั้งประเภทใบแคบ", only_narrow))

    def test_english_colour_code_supports_thai_nozzle_name(self):
        content = "รุ่น | สี | อัตรา (L/min)\n01 | Orange | 0.4\n02 | Green | 0.8"
        self.assertEqual(self.check("หัวฉีดพัดส้มมีอัตราการไหล 0.4 L/min", "01 | Orange | 0.4", content), "")
        self.assertIn("nozzle", self.check("หัวฉีดพัดเขียวมีอัตราการไหล 0.4 L/min", "01 | Orange | 0.4", content))

    def test_generic_page_without_any_crop_does_not_contradict_asked_crop(self):
        page = "การควบคุมวัชพืช 1. ทางกายภาพ 2. การเขตกรรม 3. ทางชีวภาพ"
        self.assertEqual(self.check("การควบคุมวัชพืชในข้าวโพดมี 3 วิธี", "การเขตกรรม", page), "")

    def test_spray_width_is_not_mistaken_for_weed_class(self):
        self.assertEqual(self.check("หน้ากว้างพ่น 2.8 m", "หน้ากว้างพ่น 2.8 m", "หน้ากว้างพ่น 2.8 m"), "")

    def test_claim_without_labels_is_unaffected(self):
        self.assertEqual(self.check("ควรบินให้ภาพซ้อนกันเพียงพอ", "ภาพซ้อนกัน", "ภาพซ้อนกันเพียงพอ"), "")


class ParseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.sources = [Evidence("D1", NOZZLE_TABLE, "UAV06.pdf", "5")]

    def test_wrong_label_makes_validation_fail_with_retryable_reason(self):
        raw = result_json(claims=[("หัวฉีดพัดส้มมีอัตราการไหล 950 ml", "D1", "2 | พัดน้ำเงิน | 1600 | 950 | 2850")])
        result = parse_grounded_result(raw, self.sources)
        self.assertEqual(result.claims, [])
        # evaluate_evidence retries once on this exact prefix.
        self.assertTrue(result.reason.startswith("Evidence validation failed"))
        self.assertIn("nozzle", result.reason)

    def test_acronym_present_only_in_source_url_is_accepted(self):
        web = [Evidence("W1", "โครงสร้างราคาน้ำมัน ณ วันที่ 15 ตุลาคม กำลังโหลดข้อมูล", url="https://www.eppo.go.th/page", title="ราคาน้ำมัน")]
        raw = result_json(claims=[("ข้อมูลจากสำนักงานนโยบายและแผนพลังงาน (EPPO) ณ วันที่ 15 ตุลาคม ยังกำลังโหลดข้อมูล", "W1", "ณ วันที่ 15 ตุลาคม กำลังโหลดข้อมูล")])
        self.assertEqual(parse_grounded_result(raw, web).status, "sufficient")

    def test_correct_label_passes(self):
        raw = result_json(claims=[("หัวฉีดพัดน้ำเงินมีอัตราการไหล 950 ml", "D1", "2 | พัดน้ำเงิน | 1600 | 950 | 2850")])
        self.assertEqual(parse_grounded_result(raw, self.sources).status, "sufficient")


if __name__ == "__main__":
    unittest.main()
