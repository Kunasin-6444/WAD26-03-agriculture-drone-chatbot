import unittest

from app.rag.format_utils import format_response_layout


class TestFormatUtils(unittest.TestCase):
    def test_run_on_citation_separated_with_double_newline(self):
        sample = (
            "พัดส้มมีอัตราการไหล 500 มล./หัวฉีด ในขณะที่พัดฟ้ามีอัตราการไหล 950 มล./หัวฉีด "
            "(แหล่งอ้างอิง: UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf, หน้า 5-6)"
        )
        formatted = format_response_layout(sample)
        self.assertIn("\n\n(แหล่งอ้างอิง: UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf, หน้า 5-6)", formatted)
        self.assertTrue(formatted.endswith("(แหล่งอ้างอิง: UAV06 โดรนฉีดพ่นเพื่อการเกษตร.pdf, หน้า 5-6)"))

    def test_inline_bullets_separated_to_newlines(self):
        sample = (
            "ความแตกต่างของหัวฉีด: • พัดส้ม: 500 ml • พัดฟ้า: 950 ml\n\n"
            "(แหล่งอ้างอิง: UAV06.pdf, หน้า 5)"
        )
        formatted = format_response_layout(sample)
        self.assertIn("\n• พัดส้ม: 500 ml", formatted)
        self.assertIn("\n• พัดฟ้า: 950 ml", formatted)
        self.assertTrue(formatted.endswith("\n\n(แหล่งอ้างอิง: UAV06.pdf, หน้า 5)"))

    def test_markdown_removal(self):
        sample = (
            "### หัวข้อหลัก\n"
            "ข้อมูลของ **พัดส้ม** และ *พัดฟ้า* มีดังนี้:\n"
            "* พัดส้ม: 500 ml\n"
            "* พัดฟ้า: 950 ml\n\n"
            "(แหล่งอ้างอิง: UAV06.pdf, หน้า 5)"
        )
        formatted = format_response_layout(sample)
        self.assertNotIn("###", formatted)
        self.assertNotIn("**", formatted)
        self.assertNotIn("* พัดส้ม", formatted)
        self.assertIn("• พัดส้ม: 500 ml", formatted)
        self.assertIn("• พัดฟ้า: 950 ml", formatted)
        self.assertTrue(formatted.endswith("\n\n(แหล่งอ้างอิง: UAV06.pdf, หน้า 5)"))

    def test_unparenthesized_citation_wrapped(self):
        sample = (
            "ข้อมูลราคาน้ำมันดีเซลวันนี้\n"
            "แหล่งอ้างอิง: https://uasportal.caat.or.th/infographic"
        )
        formatted = format_response_layout(sample)
        self.assertIn("\n\n(แหล่งอ้างอิง: https://uasportal.caat.or.th/infographic)", formatted)

    def test_inline_and_duplicate_citations_merged_into_one_line(self):
        sample = (
            "- ลมแรง: บินต่ำ (แหล่งอ้างอิง: UAV08 a.pdf, หน้า 35)\n"
            "- ไม่มีลม: บินปกติ\n\n"
            "(แหล่งข้อมูล: UAV07 b.pdf, หน้า 23)\n\n"
            "(แหล่งอ้างอิง: UAV08 a.pdf, หน้า 35)"
        )
        formatted = format_response_layout(sample)
        self.assertNotIn("แหล่งข้อมูล", formatted)
        self.assertEqual(formatted.count("แหล่งอ้างอิง"), 1)
        self.assertIn("- ลมแรง: บินต่ำ\n", formatted)
        self.assertTrue(
            formatted.endswith("\n\n(แหล่งอ้างอิง: UAV08 a.pdf, หน้า 35 / UAV07 b.pdf, หน้า 23)")
        )

    def test_abstain_message_remains_clean(self):
        msg = "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้"
        self.assertEqual(format_response_layout(msg), msg)


if __name__ == "__main__":
    unittest.main()
