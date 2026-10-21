import unittest
from unittest.mock import MagicMock, patch

from app.rag import rag_service, web_fallback
from app.rag.crag_service import run_crag_pipeline
from app.rag.evidence import document_evidence

KB_CONTEXT = "[แหล่งข้อมูล 1]\nไฟล์: a.pdf\nหน้า: 1\nเนื้อหา: อ้อย 2 เดือน"


class QueryAndWebPolicyContract(unittest.TestCase):
    def test_llm_sees_normalized_query_not_raw_typos(self):
        seen = {}

        def fake_eval(query, *args, **kwargs):
            seen["query"] = query
            return rag_service.GroundedResult(reason="x")

        with patch("app.rag.crag_service.retrieve_evidence", return_value=document_evidence(KB_CONTEXT)), \
             patch("app.rag.crag_service.search_web_fallback", return_value=[]), \
             patch("app.rag.crag_service.evaluate_evidence", side_effect=fake_eval):
            run_crag_pipeline("ฉีดวัชพืชในอ้อยตอน 2 gfnvo")
        self.assertNotIn("gfnvo", seen["query"])

    def test_non_caat_web_search_is_restricted_to_allowed_domains(self):
        client = MagicMock()
        client.search.return_value = {"results": []}
        web_fallback.search_web_fallback("ราคาน้ำมันดีเซล", tavily_client=client)
        kwargs = client.search.call_args.kwargs
        self.assertEqual(kwargs["include_domains_mode"], "restrict")
        self.assertEqual(set(kwargs["include_domains"]), set(web_fallback.WEB_ALLOWED_DOMAINS))
        self.assertNotIn("it24hrs.com", kwargs["include_domains"])
        self.assertEqual(kwargs["search_depth"], "basic")   # 1 credit; only CAAT needs passages

    def test_dead_fallback_model_removed(self):
        self.assertNotIn("llama-4-scout", rag_service.FALLBACK_MODELS)


if __name__ == "__main__":
    unittest.main()


class BotScopeQuestions(unittest.TestCase):
    def test_questions_about_what_the_bot_covers_get_the_help_text(self):
        from app.rag.intent_router import route_intent
        for question in ("สามารถให้ข้อมูลการใช้โดรนกับพืชชนิดใดได้บ้าง", "บอทมีข้อมูลพืชอะไรบ้าง", "ครอบคลุมเรื่องอะไรบ้าง"):
            result = route_intent(question)
            self.assertEqual(result.intent, "bot_usage", question)
            self.assertIn("อ้อย ข้าว ข้าวโพด และมันสำปะหลัง", result.handled_response)
        for question in ("ไกลโฟเซตใช้กับพืชชนิดใดได้บ้าง", "มีข้อมูลเรื่องราคาโดรนรุ่นไหนบ้าง", "สารนี้ใช้กับพืชอะไรได้บ้าง"):
            self.assertEqual(route_intent(question).intent, "document_qa", question)
