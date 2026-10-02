import unittest
from unittest.mock import MagicMock

from app.rag.rag_service import generate_grounded_answer, retrieve_context


class TestRagPipeline(unittest.TestCase):
    def test_generate_grounded_answer_empty_context(self):
        answer = generate_grounded_answer(
            query="คำถามทดสอบ",
            context="",
        )
        self.assertIn("ไม่พบข้อมูล", answer)

    def test_generate_grounded_answer_with_mocked_llm(self):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "คำตอบทดสอบ (แหล่งอ้างอิง: UAV07.pdf, หน้า 12)"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        context = "[แหล่งข้อมูล 1]\nไฟล์: UAV07.pdf\nหน้า: 12\nประเภท: table\nเนื้อหา: ข้อมูล"
        query = "หัวฉีดพัดส้ม"

        answer = generate_grounded_answer(
            query=query,
            context=context,
            client=mock_client,
        )

        self.assertEqual(answer, "คำตอบทดสอบ (แหล่งอ้างอิง: UAV07.pdf, หน้า 12)")
        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertTrue("Strict" in messages[0]["content"])
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn(query, messages[1]["content"])
        self.assertIn(context, messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
