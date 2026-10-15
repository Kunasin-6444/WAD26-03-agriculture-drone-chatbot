import unittest

from app.ingestion.thai_text import repair_sara_am
from scripts.repair_kb import plan


class ThaiTextRepairContract(unittest.TestCase):
    def test_lost_sara_am_is_restored(self):
        self.assertEqual(repair_sara_am("การท ากิจกรรมใส่ยาก าจัดวัชพืช"), "การทำกิจกรรมใส่ยากำจัดวัชพืช")
        self.assertEqual(repair_sara_am("พัดน ้าตาลอัดอากาศ"), "พัดน้ำตาลอัดอากาศ")

    def test_sara_aa_mapped_to_sara_am_font_convention(self):
        self.assertEqual(repair_sara_am("ส ำรวจ แผนที่ภำพถ่ำยโดรน เข้ำไม่ถึง"), "สำรวจ แผนที่ภาพถ่ายโดรน เข้าไม่ถึง")

    def test_correct_text_is_unchanged_and_repair_is_idempotent(self):
        text = "น้ำตาล คำถาม ทำงาน กำจัด ภาพถ่าย การบิน 1.0 | 2.8"
        self.assertEqual(repair_sara_am(text), text)
        broken = "ก าจัด ส ำรวจ ภำพ"
        self.assertEqual(repair_sara_am(repair_sara_am(broken)), repair_sara_am(broken))


class RepairPlanContract(unittest.TestCase):
    def _plan(self, native, vision):
        ids = [f"UAV99-p1-text-native-1-aaaaaa-chunk-1", f"UAV99-p1-image-vision-1-bbbbbb-chunk-1"]
        meta = [{"source_file": "UAV99.pdf", "page_number": "1"}] * 2
        return plan(ids, [native, vision], meta)

    def test_native_chunk_covered_by_vision_is_deleted(self):
        result = self._plan("การท ากิจกรรมใส่ยาก าจัดวัชพืช 120 วัน", "การทำกิจกรรมใส่ยากำจัดวัชพืช 120 วัน และอื่นๆ")
        self.assertEqual([r["reason"].split()[0] for r in result["delete"]], ["covered"])

    def test_native_chunk_with_unique_content_or_numbers_is_kept(self):
        unique = self._plan("รายละเอียดการทดลองภาคสนามเพิ่มเติมที่ไม่มีในภาพ", "ภาพถ่ายแปลงอ้อย")
        self.assertEqual(len(unique["keep_native"]), 1)
        numbers = self._plan("อัตราการใช้ 480 กรัมต่อไร่ ของสารกำจัดวัชพืช", "อัตราการใช้ 400 กรัมต่อไร่ ของสารกำจัดวัชพืช")
        self.assertEqual(numbers["keep_native"][0]["missing_numbers"], ["480"])

    def test_page_number_noise_is_deleted(self):
        self.assertEqual(self._plan("53", "ภาพถ่ายแปลงอ้อย")["delete"][0]["reason"], "noise")


if __name__ == "__main__":
    unittest.main()
