import unittest

from app.rag.rag_service import retrieve_context


class TestRetrievalBenchmark(unittest.TestCase):
    """
    Verification of retrieval quality on representative Thai questions
    from Level 3 of docs/TEST_PLAN.md.
    """

    def test_q1_flow_rate_orange_fan(self):
        query = "หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด?"
        context = retrieve_context(query, n_results=10)

        # Expected evidence: UAV07 page 12 table containing 500 (ml)
        self.assertIn("หน้า: 12", context)
        self.assertIn("พัดส้ม", context)
        self.assertIn("500", context)

    def test_q2_spray_width_at_1m(self):
        query = "ที่ความสูง 1 เมตร หน้ากว้างการฉีดพ่นต่อหัวเท่าไร?"
        context = retrieve_context(query, n_results=10)

        # Expected evidence: UAV07 page 12 table containing 1.0 m and 2.8 m
        self.assertIn("หน้า: 12", context)
        self.assertIn("2.8", context)

    def test_q3_max_flow_rate_table(self):
        query = "หัวฉีดแบบใดมีอัตราการไหลสูงที่สุด?"
        context = retrieve_context(query, n_results=12)

        # Expected evidence: UAV07 flow rate comparison (page 12 or page 8)
        has_page12 = "หน้า: 12" in context
        has_page8 = "หน้า: 8" in context
        self.assertTrue(has_page12 or has_page8)


if __name__ == "__main__":
    unittest.main()
