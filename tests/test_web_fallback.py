import unittest
from unittest.mock import MagicMock, patch

from app.rag.web_fallback import (
    CAAT_PORTAL_INFOGRAPHIC_URL,
    WebSearchResult,
    format_web_context,
    generate_web_grounded_answer,
    search_web_fallback,
)


class TestWebFallback(unittest.TestCase):
    def test_format_web_context_empty(self):
        self.assertEqual(format_web_context([]), "")

    def test_format_web_context_content(self):
        results = [
            WebSearchResult(
                title="ทดสอบหัวข้อ",
                url="https://example.com/test",
                content="เนื้อหาทดสอบ",
                score=0.9,
            )
        ]
        context = format_web_context(results)
        self.assertIn("[เว็บแหล่งข้อมูล 1]", context)
        self.assertIn("https://example.com/test", context)
        self.assertIn("เนื้อหาทดสอบ", context)

    @patch("app.rag.web_fallback.get_tavily_client", return_value=None)
    def test_caat_topic_always_includes_infographic_url(self, mock_client):
        # Even without tavily client, CAAT topic must inject CAAT portal url
        results = search_web_fallback(
            query="การขึ้นทะเบียนโดรน",
            is_caat_topic=True,
            tavily_client=None,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, CAAT_PORTAL_INFOGRAPHIC_URL)
        self.assertIn("CAAT UAS Portal", results[0].title)

    def test_tavily_search_mock(self):
        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {
            "results": [
                {
                    "title": "ข่าวโดรนเกษตร",
                    "url": "https://doa.go.th/drone-news",
                    "content": "กรมวิชาการเกษตรรับรองโดรน...",
                    "score": 0.95,
                }
            ]
        }

        results = search_web_fallback(
            query="ข่าวโดรนเกษตร กรมวิชาการเกษตร",
            is_caat_topic=False,
            tavily_client=mock_tavily,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "ข่าวโดรนเกษตร")
        self.assertEqual(results[0].url, "https://doa.go.th/drone-news")

    def test_generate_web_grounded_answer_empty_abstains(self):
        answer = generate_web_grounded_answer(
            query="โดรนราคาเท่าไร",
            web_results=[],
            is_caat_topic=False,
        )
        self.assertIn("ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้", answer)

    def test_generate_web_grounded_answer_caat_empty_provides_portal(self):
        answer = generate_web_grounded_answer(
            query="กฎหมายโดรน",
            web_results=[],
            is_caat_topic=True,
        )
        self.assertIn(CAAT_PORTAL_INFOGRAPHIC_URL, answer)

    def test_generate_web_grounded_answer_success(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="การขึ้นทะเบียนโดรนต้องดำเนินการผ่านระบบ CAAT (แหล่งอ้างอิง: https://uasportal.caat.or.th/infographic)"
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response

        results = [
            WebSearchResult(
                title="CAAT UAS Portal",
                url=CAAT_PORTAL_INFOGRAPHIC_URL,
                content="การขึ้นทะเบียนผู้บังคับโดรน",
            )
        ]

        answer = generate_web_grounded_answer(
            query="ขึ้นทะเบียนโดรนที่ไหน",
            web_results=results,
            is_caat_topic=True,
            client=mock_client,
        )

        self.assertIn("CAAT", answer)
        self.assertIn(CAAT_PORTAL_INFOGRAPHIC_URL, answer)


if __name__ == "__main__":
    unittest.main()
