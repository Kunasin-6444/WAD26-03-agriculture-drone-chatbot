import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.rag import rag_service, slide_retriever
from app.rag.evidence import Claim, Evidence
from tests.helpers import llm_client, result_json


class PayloadContract(unittest.TestCase):
    def test_verified_claim_text_and_normalizer_alias_are_explicit_in_payload(self):
        text = "พัดส้มมีปริมาณ 500 ml"
        client = llm_client(result_json(claims=[(text, "D1", text)]))
        rag_service.evaluate_evidence("พัดฟ้า (พัดน้ำเงิน) และพัดส้ม", [Evidence("D1", text, "a.pdf", "1")],
            client, verified_claims=[Claim(text, ("D1",), (("D1", text),))])
        payload = json.loads(client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(payload["verified_claims"], [{"text": text, "source_ids": ["D1"]}])
        self.assertEqual(payload["query_aliases"], {"พัดฟ้า": "พัดน้ำเงิน"})
    def test_independent_question_parts_are_explicit_in_the_model_payload(self):
        client = llm_client(result_json())
        rag_service.evaluate_evidence("พัดส้มมีปริมาณต่อหัวเท่าไร และขึ้นทะเบียนโดรนอย่างไร",
                                      [Evidence("D1", "หัวฉีดพัดส้ม 500 ml", "UAV06.pdf", "5")], client)
        payload = json.loads(client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(len(payload["question_parts"]), 2)
        self.assertNotIn("ขึ้นทะเบียน", payload["question_parts"][0])

    def test_empty_fields_are_omitted_but_all_evidence_content_is_kept(self):
        evidence = [Evidence("D1", "หัวฉีดพัดส้ม 500 ml", "UAV06.pdf", "5"),
                    Evidence("W1", "ราคาน้ำมัน", url="https://www.eppo.go.th/p", title="ราคา")]
        client = llm_client(result_json(claims=[("หัวฉีดพัดส้ม 500 ml", "D1", "หัวฉีดพัดส้ม 500 ml")]))
        rag_service.evaluate_evidence("พัดส้ม", evidence, client)
        sources = json.loads(client.chat.completions.create.call_args.kwargs["messages"][1]["content"])["sources"]
        self.assertEqual(sources[0], {"id": "D1", "content": "หัวฉีดพัดส้ม 500 ml", "source_file": "UAV06.pdf", "page_number": "5"})
        self.assertEqual(sources[1], {"id": "W1", "content": "ราคาน้ำมัน", "url": "https://www.eppo.go.th/p", "title": "ราคา"})


class WarmupContract(unittest.TestCase):
    def setUp(self):
        # Entering the lifespan opens the LINE inbox; keep it out of the production cache/ dir.
        folder = tempfile.mkdtemp(prefix="warmup-inbox-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        env = patch.dict(os.environ, {"LINE_INBOX_DB_PATH": os.path.join(folder, "inbox.sqlite3")})
        env.start()
        self.addCleanup(env.stop)

    def test_startup_runs_warmup_once_before_serving(self):
        with patch("app.main.warm_up_retrieval") as warm:
            with TestClient(app) as client:
                self.assertEqual(client.get("/").status_code, 200)
        warm.assert_called_once()

    def test_failed_warmup_never_blocks_startup(self):
        with patch("app.main.warm_up_retrieval", side_effect=RuntimeError("chroma down")):
            with TestClient(app) as client:
                self.assertEqual(client.get("/").status_code, 200)

    def test_warmup_can_be_disabled(self):
        with patch.dict(os.environ, {"WARMUP_ON_STARTUP": "false"}), patch("app.main.warm_up_retrieval") as warm:
            with TestClient(app):
                pass
        warm.assert_not_called()

    def test_retriever_warmup_builds_index_and_swallows_errors(self):
        with patch.object(slide_retriever, "_bm25_index") as build:
            slide_retriever.warm_up()
        build.assert_called_once()
        with patch.object(slide_retriever, "_bm25_index", side_effect=RuntimeError("boom")):
            slide_retriever.warm_up()  # must not raise

    def test_rag_service_warmup_delegates_to_retriever(self):
        with patch.object(slide_retriever, "warm_up") as warm:
            rag_service.warm_up_retrieval()
        warm.assert_called_once()


if __name__ == "__main__":
    unittest.main()
