import unittest

from app.rag.chunking import split_text


class TestChunkingLegacy(unittest.TestCase):
    def test_legacy_chunking_example(self):
        text = """
โดรนเกษตรเป็นอากาศยานไร้คนขับที่สามารถนำมาใช้ในงานเกษตรได้
เช่น การสำรวจพื้นที่ การถ่ายภาพ และการฉีดพ่นสารทางการเกษตร

ก่อนใช้งาน ผู้ควบคุมโดรนควรตรวจสอบสภาพอากาศ
ตรวจสอบพื้นที่ปฏิบัติงาน และตรวจสอบอุปกรณ์ให้พร้อมใช้งาน

การฉีดพ่นสารควรปฏิบัติตามคำแนะนำบนฉลากของผลิตภัณฑ์
และต้องปฏิบัติตามกฎหมายและข้อกำหนดของหน่วยงานที่เกี่ยวข้อง
""".strip()

        chunks = split_text(
            text=text,
            chunk_size=100,
            chunk_overlap=30,
        )

        self.assertGreater(len(chunks), 0)
        self.assertTrue(all(len(c) <= 100 for c in chunks))


if __name__ == "__main__":
    unittest.main()


