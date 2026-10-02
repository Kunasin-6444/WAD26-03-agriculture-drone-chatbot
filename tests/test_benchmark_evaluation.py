import unittest

from app.rag.crag_service import run_crag_pipeline
from app.rag.web_fallback import CAAT_PORTAL_INFOGRAPHIC_URL


class TestBenchmarkEvaluation(unittest.TestCase):
    """
    Automated regression benchmark verifying the 5 core behavioral dimensions:
    1. In-scope grounded retrieval and citation
    2. Rule R1 CAAT UAS Portal routing
    3. Out-of-scope question handling (web fallback / polite abstain)
    4. Ambiguous question handling
    5. Nonsense / Unsupported zero-hallucination abstain
    """

    def test_dim1_in_scope_orange_fan_nozzle(self):
        resp = run_crag_pipeline("หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด?")
        self.assertEqual(resp.source_type, "knowledge_base")
        self.assertIn("500", resp.answer)
        self.assertTrue("UAV07" in resp.answer or "UAV06" in resp.answer)
        self.assertTrue("อ้างอิง" in resp.answer)

    def test_dim2_caat_air_law_routing(self):
        resp = run_crag_pipeline("การขึ้นทะเบียนโดรนเกษตรต้องทำอย่างไร?")
        self.assertEqual(resp.source_type, "caat_portal")
        self.assertIn(CAAT_PORTAL_INFOGRAPHIC_URL, resp.answer)

    def test_dim3_out_of_scope_oil_price(self):
        resp = run_crag_pipeline("ราคาน้ำมันดีเซลวันนี้กี่บาท?")
        self.assertIn(resp.source_type, ("web_fallback", "abstain"))
        # Must not hallucinate from agricultural drone PDFs
        self.assertNotIn("UAV07", resp.answer)

    def test_dim4_ambiguous_flow_rate(self):
        resp = run_crag_pipeline("อัตราการไหลเท่าไร?")
        # Should either retrieve broad flow rates or abstain, with citations
        if resp.source_type == "knowledge_base":
            self.assertTrue("อ้างอิง" in resp.answer)

    def test_dim5_nonsense_mars_drone_abstains(self):
        resp = run_crag_pipeline("โดรนเกษตรบินไปฉีดปุ๋ยบนดาวอังคารได้ไหม?")
        self.assertEqual(resp.source_type, "abstain")
        self.assertIn("ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้", resp.answer)

    def test_dim5_empty_query_abstains(self):
        resp = run_crag_pipeline("   ")
        self.assertEqual(resp.source_type, "abstain")
        self.assertIn("กรุณาระบุคำถาม", resp.answer)


if __name__ == "__main__":
    unittest.main()
