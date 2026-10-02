import unittest

from app.ingestion.models import KnowledgeUnit
from app.rag.chunking import Chunk, split_text, chunk_knowledge_unit, chunk_knowledge_units


class TestChunkingUnit(unittest.TestCase):
    def test_split_text_normal(self):
        text = "ก" * 1500
        chunks = split_text(text, chunk_size=800, chunk_overlap=120)
        self.assertGreater(len(chunks), 1)
        # First chunk length should be 800
        self.assertEqual(len(chunks[0]), 800)

    def test_split_text_empty(self):
        self.assertEqual(split_text(""), [])
        self.assertEqual(split_text("   \n\t  "), [])

    def test_split_text_invalid_overlap(self):
        with self.assertRaises(ValueError):
            split_text("ข้อความทดสอบ", chunk_size=100, chunk_overlap=100)
        with self.assertRaises(ValueError):
            split_text("ข้อความทดสอบ", chunk_size=100, chunk_overlap=150)

    def test_chunk_knowledge_unit_preserves_metadata(self):
        unit = KnowledgeUnit(
            id="uav07-p12-table-1-test",
            document_id="uav07",
            source_file="UAV07 หัวฉีดกับคุณภาพการฉีดพ่นของโดรนเกษตร.pdf",
            page_number=12,
            source_type="table",
            content="อัตราการไหล 500 ml/หัวฉีด",
            metadata={"source": "test"},
        )
        chunks = chunk_knowledge_unit(unit, chunk_size=800, chunk_overlap=120)
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk.document_id, "uav07")
        self.assertEqual(chunk.source_file, "UAV07 หัวฉีดกับคุณภาพการฉีดพ่นของโดรนเกษตร.pdf")
        self.assertEqual(chunk.page_number, 12)
        self.assertEqual(chunk.source_type, "table")
        self.assertEqual(chunk.metadata["document_id"], "uav07")
        self.assertEqual(chunk.metadata["source_file"], "UAV07 หัวฉีดกับคุณภาพการฉีดพ่นของโดรนเกษตร.pdf")
        self.assertEqual(chunk.metadata["page_number"], "12")
        self.assertEqual(chunk.metadata["source_type"], "table")

    def test_chunk_knowledge_units_multiple(self):
        units = [
            KnowledgeUnit(
                id=f"unit-{i}",
                document_id="uav07",
                source_file="UAV07.pdf",
                page_number=i,
                source_type="text",
                content=f"ข้อความหน้าที่ {i}",
            )
            for i in range(1, 4)
        ]
        chunks = chunk_knowledge_units(units)
        self.assertEqual(len(chunks), 3)

    def test_legacy_chunking_example(self):
        text = """
โดรนเกษตรเป็นอากาศยานไร้คนขับที่สามารถนำมาใช้ในงานเกษตรได้
เช่น การสำรวจพื้นที่ การถ่ายภาพ และการฉีดพ่นสารทางการเกษตร

ก่อนใช้งาน ผู้ควบคุมโดรนควรตรวจสอบสภาพอากาศ
ตรวจสอบพื้นที่ปฏิบัติงาน และตรวจสอบอุปกรณ์ให้พร้อมใช้งาน
""".strip()
        chunks = split_text(text=text, chunk_size=100, chunk_overlap=30)
        self.assertGreater(len(chunks), 0)
        self.assertTrue(all(len(c) <= 100 for c in chunks))


if __name__ == "__main__":
    unittest.main()
