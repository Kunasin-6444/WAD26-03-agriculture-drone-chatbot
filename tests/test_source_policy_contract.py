import unittest

from app.rag.source_policy import canonical_document_id, is_excluded_document


class SourcePolicyContract(unittest.TestCase):
    def test_permit_procedure_pdf_is_excluded_like_air_law(self):
        self.assertTrue(is_excluded_document("ขั้นตอนการยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเอง.pdf"))
        self.assertTrue(is_excluded_document("UAV01 Air Law.pdf"))
        self.assertFalse(is_excluded_document("UAV07 หัวฉีดกับคุณภาพการฉีดพ่นของโดรนเกษตร.pdf"))

    def test_canonical_document_id_is_stable(self):
        self.assertEqual(canonical_document_id("UAV07 หัวฉีด.pdf"), "UAV07")
        self.assertEqual(canonical_document_id("uav6_x.pdf"), "UAV06")
        self.assertEqual(canonical_document_id("other doc.pdf"), "other_doc")


if __name__ == "__main__":
    unittest.main()
