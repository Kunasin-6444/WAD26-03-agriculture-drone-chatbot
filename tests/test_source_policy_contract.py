import unittest

from app.rag.source_policy import canonical_document_id, is_excluded_document, requested_document_ids


class SourcePolicyContract(unittest.TestCase):
    def test_permit_procedure_pdf_is_excluded_like_air_law(self):
        self.assertTrue(is_excluded_document("ขั้นตอนการยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเอง.pdf"))
        self.assertTrue(is_excluded_document("UAV01 Air Law.pdf"))
        self.assertFalse(is_excluded_document("UAV07 หัวฉีดกับคุณภาพการฉีดพ่นของโดรนเกษตร.pdf"))

    def test_canonical_document_id_is_stable(self):
        self.assertEqual(canonical_document_id("UAV07 หัวฉีด.pdf"), "UAV07")
        self.assertEqual(canonical_document_id("uav6_x.pdf"), "UAV06")
        self.assertEqual(canonical_document_id("other doc.pdf"), "other_doc")

    def test_explicit_document_identifiers_are_general_user_scope(self):
        self.assertEqual(requested_document_ids("เปรียบเทียบเอกสารUAV07 กับ uav12"), {"UAV07", "UAV12"})
        self.assertEqual(requested_document_ids("รถรุ่น XUAV07A"), set())

    def test_named_excluded_document_routes_to_caat_without_law_keyword(self):
        from app.rag.crag_grader import is_caat_air_law_or_airspace_topic
        self.assertTrue(is_caat_air_law_or_airspace_topic("สรุปข้อมูลจาก UAV01"))


if __name__ == "__main__":
    unittest.main()
