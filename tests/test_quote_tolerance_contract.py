import unittest

from app.rag.evidence import _quote_supported

TABLE = "ลำดับ | รายการ | ปัญหา\n1 | หัวฉีดอุดตัน | จากภายใน\nความสูง | หน้ากว้าง\n1.0 | 2.8 | 4.5"
TIMELINE = "ช่วงการทำงาน ยาคุุมวัชพืช ยากำจัดวัชพืชและยาคุมวัชพืช 120 วัน"


class QuoteToleranceContract(unittest.TestCase):
    def test_layout_only_differences_are_tolerated(self):
        self.assertTrue(_quote_supported("1.0 2.8 4.5", TABLE))          # table separators dropped
        self.assertTrue(_quote_supported("1 หัวฉีดอุดตัน จากภายใน", TABLE))
        self.assertTrue(_quote_supported("ยาคุมวัชพืช", TIMELINE))        # doubled vowel in source
        self.assertTrue(_quote_supported("ทํางาน", "การทำงาน".replace("ำ", "ํา")))

    def test_ellipsis_fragments_must_each_appear_in_order(self):
        self.assertTrue(_quote_supported("หัวฉีดอุดตัน ... จากภายใน", TABLE))
        self.assertFalse(_quote_supported("จากภายใน ... หัวฉีดอุดตัน", TABLE))   # wrong order
        self.assertFalse(_quote_supported("หัวฉีดอุดตัน ... ไม่มีในเอกสาร", TABLE))

    def test_changed_words_or_numbers_are_still_rejected(self):
        self.assertFalse(_quote_supported("1.0 | 2.9 | 4.5", TABLE))
        self.assertFalse(_quote_supported("หัวฉีดรั่วจากภายใน", TABLE))
        self.assertFalse(_quote_supported("...", TABLE))
        self.assertFalse(_quote_supported("ab", "ab"))                    # fragment shorter than 3 chars


if __name__ == "__main__":
    unittest.main()
