import unittest
from unittest.mock import MagicMock

from app.rag.crag_grader import (
    GradeResult,
    grade_retrieval,
    is_caat_air_law_or_airspace_topic,
)


class TestCragGrader(unittest.TestCase):
    def test_caat_keyword_detection(self):
        # Law / Air Space questions must be recognized
        self.assertTrue(is_caat_air_law_or_airspace_topic("ต้องขึ้นทะเบียนโดรนที่ไหน"))
        self.assertTrue(is_caat_air_law_or_airspace_topic("ข้อกำหนดเขตห้ามบินโดรน"))
        self.assertTrue(is_caat_air_law_or_airspace_topic("กฎหมายการบินโดรนมีอะไรบ้าง"))
        self.assertTrue(is_caat_air_law_or_airspace_topic("ห้ามบินสูงเกินกี่เมตร"))

        # Drone operation / nozzle questions should not trigger CAAT exception
        self.assertFalse(is_caat_air_law_or_airspace_topic("หัวฉีดพัดส้มมีอัตราการไหลเท่าไร"))
        self.assertFalse(is_caat_air_law_or_airspace_topic("โดรนฉีดพ่นทำงานอย่างไร"))

    def test_empty_context_returns_incorrect(self):
        result = grade_retrieval(query="อัตราการไหลหัวฉีด", context="")
        self.assertEqual(result.grade, "INCORRECT")
        self.assertFalse(result.is_relevant)

        result_spaces = grade_retrieval(query="อัตราการไหลหัวฉีด", context="   \n\t ")
        self.assertEqual(result_spaces.grade, "INCORRECT")
        self.assertFalse(result_spaces.is_relevant)

    def test_caat_topic_routes_away_from_pdf(self):
        # R1 rule: CAAT air law/space must not use local PDF
        result = grade_retrieval(
            query="ขึ้นทะเบียนโดรนต้องทำอย่างไร",
            context="[แหล่งข้อมูล 1] UAV01 Air Law.pdf หน้า 1 เนื้อหา: กฎหมายโดรน",
        )
        self.assertTrue(result.is_caat_topic)
        self.assertEqual(result.grade, "INCORRECT")
        self.assertFalse(result.is_relevant)

    def test_grade_retrieval_correct(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"grade": "CORRECT", "reason": "มีข้อมูลอัตราการไหลของหัวฉีดพัดส้มชัดเจน"}'
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response

        result = grade_retrieval(
            query="หัวฉีดพัดส้มมีอัตราการไหลเท่าไร",
            context="[แหล่งข้อมูล 1] UAV07 หน้า 12 พัดส้ม 500 ml/หัวฉีด",
            client=mock_client,
        )

        self.assertEqual(result.grade, "CORRECT")
        self.assertTrue(result.is_relevant)
        self.assertIn("หัวฉีดพัดส้ม", result.reason)

    def test_grade_retrieval_incorrect(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"grade": "INCORRECT", "reason": "เนื้อหาไม่เกี่ยวข้องกับคำถาม"}'
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response

        result = grade_retrieval(
            query="ราคาโดรนเกษตรเท่าไร",
            context="[แหล่งข้อมูล 1] UAV07 หน้า 12 พัดส้ม 500 ml/หัวฉีด",
            client=mock_client,
        )

        self.assertEqual(result.grade, "INCORRECT")
        self.assertFalse(result.is_relevant)

    def test_grade_retrieval_json_parse_error_graceful(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        # Invalid JSON returned
        mock_response.choices = [MagicMock(message=MagicMock(content="ไม่ใช่ JSON"))]
        mock_client.chat.completions.create.return_value = mock_response

        result = grade_retrieval(
            query="ทดสอบคำถาม",
            context="[แหล่งข้อมูล 1] เนื้อหา",
            client=mock_client,
        )

        self.assertEqual(result.grade, "INCORRECT")
        self.assertFalse(result.is_relevant)


    def test_grade_retrieval_semantic_caat_topic(self):
        # Even without fast keywords, LLM semantic classification can flag CAAT topic
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"is_caat_topic": true, "grade": "INCORRECT", "reason": "ถามเกี่ยวกับขั้นตอนการขออนุญาตบินโดรน"}'
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response

        result = grade_retrieval(
            query="อยากบินพ่นยาในสวน ต้องไปบอกใครก่อน",
            context="[แหล่งข้อมูล 1] UAV07 หัวฉีด",
            client=mock_client,
        )

        self.assertTrue(result.is_caat_topic)
        self.assertEqual(result.grade, "INCORRECT")
        self.assertFalse(result.is_relevant)


if __name__ == "__main__":
    unittest.main()
