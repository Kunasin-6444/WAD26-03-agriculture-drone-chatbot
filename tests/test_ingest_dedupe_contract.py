import unittest

from app.ingestion.dedupe import drop_covered_native_units
from app.ingestion.models import KnowledgeUnit


def _unit(uid, source, content, source_type="text"):
    return KnowledgeUnit(id=uid, document_id="UAV99", source_file="UAV99.pdf", page_number=5,
                         source_type=source_type, content=content, extracted_text=content,
                         title=None, metadata={"source": source})


class IngestDedupeContract(unittest.TestCase):
    def test_native_unit_covered_by_vision_is_dropped_but_vision_is_kept(self):
        units = [_unit("n", "pdf_text", "การท ากิจกรรมใส่ยาก าจัดวัชพืช 120 วัน"),
                 _unit("v", "vision", "การทำกิจกรรมใส่ยากำจัดวัชพืช 120 วัน และคำอธิบายภาพ", "image")]
        self.assertEqual([u.id for u in drop_covered_native_units(units, 5)], ["v"])

    def test_native_unit_with_content_vision_lacks_is_kept(self):
        units = [_unit("n", "pdf_text", "ขั้นตอนการทดลองภาคสนามอัตราบิน 5 เมตรต่อวินาที"),
                 _unit("v", "vision", "ภาพถ่ายแปลงอ้อย", "image")]
        self.assertEqual({u.id for u in drop_covered_native_units(units, 5)}, {"n", "v"})

    def test_native_page_without_vision_is_never_dropped(self):
        units = [_unit("n", "pdf_text", "ข้อความล้วนที่ไม่มี vision")]
        self.assertEqual([u.id for u in drop_covered_native_units(units, 5)], ["n"])

    def test_number_missing_from_vision_keeps_native_table(self):
        units = [_unit("n", "pdf_native_table", "อัตรา | 480 | กรัมต่อไร่ ของสารกำจัดวัชพืช", "table"),
                 _unit("v", "vision", "อัตรา | 400 | กรัมต่อไร่ ของสารกำจัดวัชพืช", "table")]
        self.assertIn("n", {u.id for u in drop_covered_native_units(units, 5)})


if __name__ == "__main__":
    unittest.main()
