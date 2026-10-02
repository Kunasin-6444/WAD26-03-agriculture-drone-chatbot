import unittest

from app.rag.crag_grader import is_caat_air_law_or_airspace_topic
from app.rag.crag_service import run_crag_pipeline
from app.rag.web_fallback import CAAT_PORTAL_INFOGRAPHIC_URL


class TestRealWorldEdgeCases(unittest.TestCase):
    """
    Realistic Edge Case Verification Suite.
    Ensures the system is flexible, generalizes without artificial hardcoding,
    and behaves reliably on real farmer / pilot queries.
    """

    def test_casual_farmer_agricultural_query_not_routed_to_caat(self):
        """
        Edge Case 1: A farmer asks a spraying question using casual flight words ("จะบินโดรน", "ในนาข้าว").
        The system must NOT trigger false-positive CAAT classification.
        It must route to Knowledge Base and answer nozzle/droplet recommendations from PDF documents.
        """
        query = "จะบินโดรนพ่นยาในนาข้าวต้องใช้หัวฉีดอะไร"

        # 1. Verify keyword gate does not falsely trigger
        self.assertFalse(
            is_caat_air_law_or_airspace_topic(query),
            "Casual agricultural query must not be falsely flagged as a CAAT legal topic.",
        )

        # 2. Run full CRAG pipeline
        response = run_crag_pipeline(query)
        self.assertEqual(
            response.source_type,
            "knowledge_base",
            f"Expected knowledge_base but got {response.source_type}. Reason: {response.grade_reason}",
        )
        self.assertEqual(response.grade, "CORRECT")

        # Must mention actual nozzle/droplet information from UAV06/UAV07
        answer_lower = response.answer.lower()
        self.assertTrue(
            any(k in answer_lower for k in ["หัวฉีด", "ละออง", "ไมครอน", "พัด"]),
            f"Expected answer to contain nozzle/droplet facts, got: {response.answer}",
        )

    def test_operational_altitude_vs_legal_altitude_separation(self):
        """
        Edge Case 2: Ensure proper semantic separation between:
        A) Operational spraying flight altitude (1.5 - 3 meters above crops, from KB)
        B) Legal maximum ceiling altitude (90 meters / 300 feet, from CAAT)
        """
        operational_query = "การฉีดพ่นสารเคมีด้วยโดรนควรบินที่ความสูงเท่าไรเหนือแปลงพืช"
        self.assertFalse(
            is_caat_air_law_or_airspace_topic(operational_query),
            "Operational spraying height query must not be flagged as CAAT legal ceiling.",
        )
        op_response = run_crag_pipeline(operational_query)
        self.assertEqual(op_response.source_type, "knowledge_base")
        self.assertTrue(
            any(num in op_response.answer for num in ["1.5", "2", "3", "เมตร"]),
            f"Expected operational altitude around 1.5-3 meters, got: {op_response.answer}",
        )

        legal_query = "กฎหมายการบินโดรนห้ามบินสูงเกินกี่เมตร"
        self.assertTrue(
            is_caat_air_law_or_airspace_topic(legal_query),
            "Legal ceiling query must be recognized as CAAT air law topic.",
        )
        legal_response = run_crag_pipeline(legal_query)
        self.assertEqual(legal_response.source_type, "caat_portal")
        self.assertIn("90", legal_response.answer)
        self.assertIn(CAAT_PORTAL_INFOGRAPHIC_URL, legal_response.answer)

    def test_dynamic_caat_penalty_outside_static_infographic(self):
        """
        Edge Case 3: Asking about penalties/fines for unauthorized drone flights.
        Tests that the system dynamically retrieves penalty details from live official sources
        instead of hitting a static dead-end.
        """
        query = "โทษของการบินโดรนโดยไม่ได้รับอนุญาตหรือผิดกฎหมายมีอะไรบ้าง ปรับเท่าไหร่"
        self.assertTrue(is_caat_air_law_or_airspace_topic(query))

        response = run_crag_pipeline(query)
        self.assertEqual(response.source_type, "caat_portal")

        # Must not return unhelpful "not found" message
        self.assertNotIn("ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือ", response.answer)

        # Must describe legal penalties (imprisonment or fines like 40,000 THB)
        self.assertTrue(
            any(w in response.answer for w in ["จำคุก", "ปรับ", "40,000", "โทษทางอาญา"]),
            f"Expected penalty details in answer, got: {response.answer}",
        )
        self.assertTrue(
            any(k in response.answer for k in [CAAT_PORTAL_INFOGRAPHIC_URL, "caat", "senate.go.th", "droneth.or.th", "แหล่งอ้างอิง"]),
            f"Expected reliable official citation, got: {response.answer}",
        )

    def test_compound_query_with_unsupported_future_elements(self):
        """
        Edge Case 4: Query mixes valid agricultural KB knowledge (sugarcane spraying)
        with out-of-scope real-time/future info (tomorrow's weather).
        The system must grade CORRECT or AMBIGUOUS (with valid KB grounding),
        answer the sugarcane spraying facts, and politely decline live weather.
        """
        query = "พรุ่งนี้จะไปพ่นอ้อย พ่นอะไรดี สภาพอากาศเป็นไง"
        response = run_crag_pipeline(query)

        self.assertIn(response.grade, ("CORRECT", "AMBIGUOUS"))
        self.assertEqual(response.source_type, "knowledge_base")

        # Must recommend sugarcane herbicides from UAV06/07
        self.assertTrue(
            any(herb in response.answer for herb in ["วัชพืช", "อ้อย", "อาลาคลอร์", "แอตทราซีน", "ไดยูรอน", "เพนดิเมทาลิน"]),
            f"Expected sugarcane herbicide recommendations, got: {response.answer}",
        )

        # Must politely address the weather limitation without hallucinating live forecast
        self.assertTrue(
            any(term in response.answer for term in ["สภาพอากาศ", "เรียลไทม์", "ลม", "ไม่มีข้อมูล"]),
            f"Expected note on weather in answer, got: {response.answer}",
        )

    def test_legitimate_self_farm_flight_permit_classified_caat(self):
        """
        Edge Case 5: Genuine legal question about flying over one's own farm.
        Must be classified as CAAT Rule R1, cite UAS Portal and describe self-farm permit requirements.
        """
        query = "บินโดรนในนาตัวเองต้องขออนุญาตไหม"
        self.assertTrue(is_caat_air_law_or_airspace_topic(query))

        response = run_crag_pipeline(query)
        self.assertEqual(response.source_type, "caat_portal")
        self.assertIn(CAAT_PORTAL_INFOGRAPHIC_URL, response.answer)

    def test_impossible_fantasy_query_strictly_abstains(self):
        """
        Edge Case 6: Impossible/fantasy query.
        The system must strictly abstain and never hallucinate fiction.
        """
        query = "โดรนการเกษตรสามารถดำน้ำลงไปจับปลาวาฬใต้ทะเลลึกได้หรือไม่"
        response = run_crag_pipeline(query)

        self.assertTrue(
            response.source_type in ("abstain", "web_fallback"),
            f"Fantasy query must not use local KB, got: {response.source_type}",
        )
        self.assertTrue(
            any(w in response.answer for w in ["ไม่พบข้อมูล", "ไม่มีข้อมูล"]),
            f"Expected abstain message, got: {response.answer}",
        )

    def test_colloquial_color_synonym_nozzle_comparison(self):
        """
        Edge Case 7: Colloquial color synonym comparison ("พัดส้มต่างจากพัดฟ้ายังไง").
        Farmer uses "พัดฟ้า" for "พัดน้ำเงิน".
        The system must not fail with AMBIGUOUS / abstain; it must compare both nozzles
        using Knowledge Base evidence (flow rate 500 vs 950 ml) with citations.
        """
        query = "พัดส้มต่างจากพัดฟ้ายังไง"
        response = run_crag_pipeline(query)

        self.assertEqual(response.source_type, "knowledge_base")
        self.assertNotIn("ไม่พบข้อมูลดังกล่าว", response.answer)
        self.assertTrue(
            any(w in response.answer for w in ["พัดส้ม", "500"]),
            f"Expected orange fan details in answer, got: {response.answer}",
        )
        self.assertTrue(
            any(w in response.answer for w in ["พัดฟ้า", "พัดน้ำเงิน", "950"]),
            f"Expected blue/cyan fan details in answer, got: {response.answer}",
        )
        self.assertIn("UAV", response.answer)


if __name__ == "__main__":
    unittest.main()
