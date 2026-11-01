"""R3 regressions: a real quote must not license another row/column's value."""
import unittest

from app.rag.evidence import Evidence, parse_grounded_result
from tests.helpers import result_json

NOZZLES = ("หัวฉีด | รอบ (rpm) | ปริมาณ (ml/หัวฉีด) | ปริมาณ 3 หัวฉีด (ml)\n"
           "พัดส้ม | 1600 | 500 | 1500\nพัดแดง | 1600 | 1150 | 3450\nพัดน้ำเงิน | 1600 | 950 | 2850")
WIDTHS = ("ความสูง (เมตร) | หน้ากว้าง (เมตรต่อหัว) | หน้ากว้างรวม (เมตรต่อ 3 หัว)\n"
          "0.5 | 1.4 | 3.1\n1.0 | 2.8 | 4.5\n1.5 | 4.3 | 6.0")


def test_cited_mixture_components_are_not_mistaken_for_the_single_substance_row():
    from app.rag.table_grounding import table_inconsistency
    table = ('สาร | อัตรา (กรัม/ไร่)\nเพนดิเมทาลิน | 320-480\n'
             'เพนดิเมทาลิน+อิมาซาปิก | 120-160+12')
    quote = table.splitlines()[-1]
    good = ('อัตราที่ใช้คือ 120-160+12 กรัม/ไร่ ตามลำดับชื่อสาร คือ '
            'เพนดิเมทาลิน 120-160 กรัม/ไร่ และอิมาซาปิก 12 กรัม/ไร่')
    swapped = good.replace('เพนดิเมทาลิน 120-160', 'เพนดิเมทาลิน 12').replace(
        'อิมาซาปิก 12 กรัม', 'อิมาซาปิก 120-160 กรัม')
    assert table_inconsistency(good, [quote], table) == ''
    assert table_inconsistency(swapped, [quote], table)
    assert table_inconsistency(good.replace('เพนดิเมทาลิน 120-160', 'เพนดิเมทาลิน 160-120'), [quote], table)
    assert table_inconsistency(good, [], table)  # No cited mixture row; do not infer.
    assert table_inconsistency(good.replace('กรัม/ไร่', 'มิลลิลิตร/ไร่'), [quote], table)


class TableGroundingContractTests(unittest.TestCase):
    def result(self, text, table=NOZZLES, quote=None):
        return parse_grounded_result(result_json(claims=[(text, "D1", quote or table)]), [Evidence("D1", table, "table.pdf", "12")])

    def test_full_table_quote_cannot_attach_red_value_to_orange(self):
        self.assertEqual(self.result("หัวฉีดพัดส้มมีปริมาณ 1150 ml ต่อหัวฉีด ที่ 1600 rpm").claims, [])

    def test_all_other_row_flow_mutations_are_rejected(self):
        for label, value in [("ส้ม", 500), ("แดง", 1150), ("น้ำเงิน", 950)]:
            for wrong in {500, 1150, 950} - {value}:
                with self.subTest(label=label, wrong=wrong):
                    self.assertEqual(self.result(f"พัด{label} มีปริมาณ {wrong} ml ต่อหัวฉีด").claims, [])

    def test_correct_full_table_quote_is_accepted(self):
        self.assertEqual(self.result("พัดส้มมีปริมาณ 500 ml ต่อหัวฉีด ที่ 1600 rpm").status, "sufficient")

    def test_correct_comparison_preserves_each_entity_value_pair(self):
        self.assertEqual(self.result("พัดส้มมีปริมาณ 500 ml ต่อหัวฉีด และพัดน้ำเงินมีปริมาณ 950 ml ต่อหัวฉีด").status, "sufficient")

    def test_swapped_comparison_not_accepted_by_union_of_rows(self):
        self.assertEqual(self.result("พัดส้มมีปริมาณ 950 ml ต่อหัวฉีด และพัดน้ำเงินมีปริมาณ 500 ml ต่อหัวฉีด").claims, [])

    def test_wrong_column_same_row_is_rejected(self):
        self.assertEqual(self.result("พัดส้มมีปริมาณ 1500 ml ต่อหัวฉีด").claims, [])

    def test_rpm_value_cannot_be_presented_as_volume(self):
        self.assertEqual(self.result("พัดส้มมีปริมาณ 1600 ml ต่อหัวฉีด").claims, [])

    def test_per_head_and_three_heads_values_both_supported(self):
        self.assertEqual(self.result("พัดส้มมีปริมาณ 500 ml ต่อหัวฉีด หรือ 1500 ml สำหรับ 3 หัวฉีด ที่ 1600 rpm").status, "sufficient")

    def test_numeric_selector_height_must_match_correct_width_row(self):
        self.assertEqual(self.result("ที่ความสูง 1 เมตร หน้ากว้าง 4.3 เมตรต่อหัว", WIDTHS).claims, [])

    def test_width_per_three_heads_cannot_be_called_per_head(self):
        self.assertEqual(self.result("ที่ความสูง 1 เมตร หน้ากว้าง 4.5 เมตรต่อหัว", WIDTHS).claims, [])

    def test_correct_height_width_and_three_head_total(self):
        self.assertEqual(self.result("ที่ความสูง 1 เมตร หน้ากว้าง 2.8 เมตรต่อหัว หรือ 4.5 เมตรต่อ 3 หัว", WIDTHS).status, "sufficient")

    def test_denominator_before_value_belongs_to_its_own_measurement(self):
        good = "ที่ความสูง 1 เมตร หน้ากว้างต่อหัวเท่ากับ 2.8 เมตร และหน้ากว้างรวม 3 หัวเท่ากับ 4.5 เมตร"
        bad = "ที่ความสูง 1 เมตร หน้ากว้างต่อหัวเท่ากับ 4.5 เมตร และหน้ากว้างรวม 3 หัวเท่ากับ 2.8 เมตร"
        self.assertEqual(self.result(good, WIDTHS).status, "sufficient")
        self.assertEqual(self.result(bad, WIDTHS).claims, [])

    def test_rpm_does_not_license_an_invented_volume_per_minute(self):
        for text in ["พัดส้มมีอัตราการไหล 500 ml/min", "พัดส้มมีอัตราการไหล 500 มิลลิลิตรต่อหัวฉีดต่อนาที"]:
            with self.subTest(text=text):
                self.assertEqual(self.result(text).claims, [])

    def test_rate_column_cannot_borrow_value_from_volume_column(self):
        table = "หัวฉีด | ปริมาณ (ml/หัวฉีด) | อัตราการไหล (ml/min/หัวฉีด)\nพัดส้ม | 500 | 250"
        self.assertEqual(self.result("พัดส้มมีอัตราการไหล 500 ml/min ต่อหัวฉีด", table).claims, [])
        self.assertEqual(self.result("พัดส้มมีอัตราการไหล 250 ml/min ต่อหัวฉีด", table).status, "sufficient")

    def test_row_labels_with_numbers_still_bind_their_own_values(self):
        table = "ช่วงเวลา | ผลผลิต (ตัน/ไร่)\nควบคุมวัชพืช 1 เดือน | 1.6\nควบคุมวัชพืช 3 เดือน | 9.7"
        self.assertEqual(self.result("ควบคุมวัชพืชเป็นเวลา 3 เดือน ได้ผลผลิต 1.6 ตัน/ไร่", table).claims, [])
        self.assertEqual(self.result("ควบคุมวัชพืชเป็นเวลา 3 เดือน ได้ผลผลิต 9.7 ตัน/ไร่", table).status, "sufficient")

    def test_leading_annotation_before_ordinal_cannot_disable_row_checks(self):
        table = ("ลำดับ | หัวฉีด | รอบ (rpm) | ปริมาณ (ml/หัวฉีด)\n"
                 "**นิยมใช้** | 1 | พัดส้ม | 1600 | 500\n2 | พัดแดง | 1600 | 1150")
        self.assertEqual(self.result("พัดส้มมีปริมาณ 1150 ml ต่อหัวฉีด", table).claims, [])
        self.assertEqual(self.result("พัดส้มมีปริมาณ 500 ml ต่อหัวฉีด", table).status, "sufficient")

    def test_generic_thai_row_labels_not_only_nozzle_colours(self):
        table = "สาร | อัตรา (กรัม/ไร่)\nอาลาคลอร์ | 200\nอะทราซีน | 300"
        self.assertEqual(self.result("อาลาคลอร์ใช้อัตรา 300 กรัม/ไร่", table).claims, [])
        self.assertEqual(self.result("อาลาคลอร์ใช้อัตรา 200 กรัม/ไร่", table).status, "sufficient")

    def test_numeric_fact_before_its_label_still_checked(self):
        self.assertEqual(self.result("ปริมาณ 1150 ml ต่อหัวฉีดเป็นค่าของพัดส้ม").claims, [])

    def test_equivalent_decimal_notation_retained(self):
        self.assertEqual(self.result("ความสูง 1.0 เมตร หน้ากว้าง 2.8 เมตรต่อหัว", WIDTHS).status, "sufficient")

    def test_multiple_axis_pairs_cannot_swap_values_between_rows(self):
        good = "ความสูง 1 เมตร หน้ากว้าง 2.8 เมตรต่อหัว และความสูง 1.5 เมตร หน้ากว้าง 4.3 เมตรต่อหัว"
        bad = "ความสูง 1 เมตร หน้ากว้าง 4.3 เมตรต่อหัว และความสูง 1.5 เมตร หน้ากว้าง 2.8 เมตรต่อหัว"
        self.assertEqual(self.result(good, WIDTHS).status, "sufficient")
        self.assertEqual(self.result(bad, WIDTHS).claims, [])

    def test_non_table_prose_not_affected(self):
        prose = "หัวฉีดพัดส้มมีปริมาณ 500 ml ต่อหัวฉีด ที่ 1600 rpm"
        self.assertEqual(self.result(prose, prose).status, "sufficient")

    def test_enumerating_all_height_keys_is_not_a_multi_row_mismatch(self):
        self.assertEqual(self.result("ความสูง 0.5 เมตร, 1.0 เมตร และ 1.5 เมตร", WIDTHS).status, "sufficient")

    def test_enumerated_axis_cannot_include_value_from_dependent_column(self):
        self.assertEqual(self.result("ความสูง 0.5 เมตร, 1.0 เมตร และ 3.1 เมตร", WIDTHS).claims, [])

    def test_transposed_table_preserves_dimensionless_metric_columns(self):
        table = "Nozzle | พัดส้ม | พัดเหลือง\nMDR | 1.20-1.40 | 1.26-1.40\nRS | 0.87-1.00 | 0.95-1.05"
        self.assertEqual(self.result("พัดส้ม MDR 1.20-1.40 และ RS 0.87-1.00", table).status, "sufficient")
        self.assertEqual(self.result("พัดส้ม MDR 1.26-1.40", table).claims, [])
        self.assertEqual(self.result("พัดส้ม RS 1.20-1.40", table).claims, [])

    def test_numbered_rows_are_not_transposed_when_claim_mentions_generic_header(self):
        table = "ลำดับ | หัวฉีด | รอบ (rpm) | ปริมาณ (ml/หัวฉีด) | ปริมาณ 3 หัวฉีด (ml)\n1 | พัดส้ม | 1600 | 500 | 1500\n2 | พัดแดง | 1600 | 1150 | 3450"
        self.assertEqual(self.result("หัวฉีดพัดส้มมีปริมาณ 500 ml ต่อหัวฉีด ที่รอบ 1600 rpm", table).status, "sufficient")
        self.assertEqual(self.result("หัวฉีดพัดส้มมีปริมาณ 1150 ml ต่อหัวฉีด", table).claims, [])


# Row-wise pest table whose first column repeats a category, as in the disease feature document.
PESTS = ("โรคหรือแมลง | ชื่อศัตรูพืช | ชื่อสาร | รหัส | อัตราส่วน | คำแนะนำการใช้\n"
         "แมลง | หนอนเอ | สารอัลฟา 5% | SC | 20 มล./น้ำ 20 ลิตร | พ่น 2-3 ครั้ง ห่างกัน 14 วัน\n"
         "แมลง | หนอนบี | สารเบตา 10% | WP | 80 กรัม/น้ำ 20 ลิตร | พ่นทุก 7 วัน")


class RowWiseAttributeHeaders(unittest.TestCase):
    """2026-10-20 live screening: a correct rate claim naming the 'รหัส'/'อัตราส่วน' headers was rejected
    because the table was read column-wise; and the repeated category column hid the pest names."""

    def check(self, claim):
        from app.rag.table_grounding import table_inconsistency
        return table_inconsistency(claim, [], PESTS)

    def test_naming_attribute_headers_keeps_a_row_wise_table_row_wise(self):
        self.assertEqual(self.check("หนอนเอใช้สารอัลฟา 5% รหัส SC อัตราส่วน 20 มล./น้ำ 20 ลิตร"), "")

    def test_a_value_from_another_pest_row_is_caught_behind_a_category_column(self):
        self.assertIn("row", self.check("หนอนเอใช้สารอัลฟา 5% อัตราส่วน 80 กรัม/น้ำ 20 ลิตร"))


WEATHER = ("ชื่อศัตรูพืช | อุณหภูมิ (°C ) | ร้อนติดต่อ (วัน ) | ฝนทิ้งช่วง (วัน ) | ระยะฟักตัว (วัน) | ข้อความแจ้งเตือน\n"
           "แมลงซี | >= 38 | >= 4 | >= 9 | 2-5 | ร้อนจัดติดต่อกัน และฝนทิ้งช่วง 1-2 สัปดาห์")


class ColumnNameLabelsTheNextNumber(unittest.TestCase):
    def check(self, claim):
        from app.rag.table_grounding import table_inconsistency
        return table_inconsistency(claim, [], WEATHER)

    def test_a_later_number_is_not_read_as_the_earlier_column(self):
        self.assertEqual(self.check("แมลงซีระบาดเมื่ออุณหภูมิ >=38°C ติดต่อกัน 4 วัน และฝนทิ้งช่วง >=9 วัน"), "")
        self.assertEqual(self.check("แมลงซีมีระยะฟักตัว 2-5 วัน"), "")
        # words copied from a text cell of the row are not the day-count column of the same name
        self.assertEqual(self.check("แมลงซีระบาดเมื่อร้อนจัด และฝนทิ้งช่วง 1-2 สัปดาห์"), "")

    def test_a_value_put_under_the_wrong_named_column_is_still_caught(self):
        self.assertTrue(self.check("แมลงซีร้อนติดต่อ >=9 วัน"))
        self.assertTrue(self.check("แมลงซีฝนทิ้งช่วง 2 วัน"))
        self.assertTrue(self.check("แมลงซีมีระยะฟักตัว 4-5 วัน"))

    def test_nozzle_prose_after_three_head_volume_does_not_override_denominator(self):
        from app.rag.table_grounding import table_inconsistency
        table = ("ลำดับ | หัวฉีด | รอบ (rpm) | ปริมาณ (ml) / หัวฉีด | ปริมาณ (ml) 3 หัวฉีด\n"
                 "**นิยมใช้** | 1 | พัดส้ม | 1600 | 500 | 1500\n4 | พัดน้ำเงิน | 1600 | 950 | 2850")
        good = "หัวฉีดพัดส้ม: อัตราการไหล 500 ml/หัวฉีด (ปริมาณสำหรับ 3 หัวฉีด 1500 ml) และระบุว่าเป็นหัวฉีดที่นิยมใช้"
        bad = "หัวฉีดพัดส้ม: อัตราการไหล 1500 ml/หัวฉีด (ปริมาณสำหรับ 3 หัวฉีด 500 ml) และระบุว่าเป็นหัวฉีดที่นิยมใช้"
        self.assertEqual(table_inconsistency(good, [], table), "")
        self.assertIn("mismatch", table_inconsistency(bad, [], table))

    def test_multi_row_comparison_clause_binds_values_in_row_order(self):
        from app.rag.table_grounding import table_inconsistency
        table = ("ลำดับ | หัวฉีด | รอบ (rpm) | ปริมาณ (ml) / หัวฉีด | ปริมาณ (ml) 3 หัวฉีด\n"
                 "**นิยมใช้** | 1 | พัดส้ม | 1600 | 500 | 1500\n4 | พัดน้ำเงิน | 1600 | 950 | 2850")
        good = "ตามตารางอัตราการไหล พัดส้มปล่อยน้ำน้อยกว่าพัดน้ำเงิน คือ 500 ml/หัวฉีด เทียบกับ 950 ml/หัวฉีด"
        swapped = "ตามตารางอัตราการไหล พัดส้มปล่อยน้ำมากกว่าพัดน้ำเงิน คือ 950 ml/หัวฉีด เทียบกับ 500 ml/หัวฉีด"
        self.assertEqual(table_inconsistency(good, [], table), "")
        self.assertIn("mismatch", table_inconsistency(swapped, [], table))

    def test_model_column_preferred_over_single_row_brand_column(self):
        from app.rag.table_grounding import table_inconsistency
        table = ("ยี่ห้อ | รุ่น | ราคา (บาท) | ความจุ (ลิตร)\nDJI AGRAS | T25 | 330,000 | 20\nDJI AGRAS | T40 | 408,500 | 40\n\n"
                 "ยี่ห้อ | รุ่น | ราคา (บาท) | ความจุ (ลิตร)\nDJI AGRAS | T50 | 427,500 | 40\nXAG | P100 | 500,000 | 50")
        good = "DJI AGRAS T25 ราคา 330,000 บาท ความจุ 20 ลิตร ขณะที่ DJI AGRAS T50 ราคา 427,500 บาท ความจุ 40 ลิตร"
        bad = "DJI AGRAS T25 ราคา 427,500 บาท ความจุ 20 ลิตร ขณะที่ DJI AGRAS T50 ราคา 330,000 บาท ความจุ 40 ลิตร"
        self.assertEqual(table_inconsistency(good, [], table), "")
        self.assertIn("mismatch", table_inconsistency(bad, [], table))
