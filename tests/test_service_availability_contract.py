"""Failure reporting and known-quota short circuits, using fakes only."""
import os
import time
import unittest
from unittest.mock import MagicMock, patch
from concurrent.futures import TimeoutError as FutureTimeout

from fastapi.testclient import TestClient

from app.playground import app, ask_live
from app.rag import rag_service
from app.rag.crag_service import run_crag_pipeline
from app.rag.evidence import ABSTAIN_MESSAGE, document_evidence
from app.rag.web_fallback import WebSearchResult, search_web_fallback
from app.service_status import ERROR_MESSAGES, classify_service_error, service_error_code
from app.services import ai_service
from scripts.evaluate_answers import outcome
from tests.helpers import DOCUMENT_CONTEXT, llm_client, result_json

MODEL = "offline-only-model"
QUESTION = "พัดส้มมีอัตราการไหลเท่าไร"


class HttpError(Exception):
    def __init__(self, status_code, body="private-provider-detail"):
        super().__init__(body)
        self.status_code = status_code
        self.body = body


class ServiceFailureClassification(unittest.TestCase):
    def test_failure_codes_distinguish_daily_quota_from_auth_and_temporary_throttling(self):
        cases = [
            (HttpError(401, {"error": "This model reached daily limit."}), "quota_exhausted"),
            (HttpError(429, {"error": "daily limit"}), "quota_exhausted"),
            (HttpError(401), "provider_auth"),
            (HttpError(403), "provider_auth"),
            (HttpError(429), "rate_limited"),
            (HttpError(503), "provider_unavailable"),
            (HttpError(504), "timeout"),
            (TimeoutError("private-provider-detail"), "timeout"),
        ]
        for error, expected in cases:
            with self.subTest(code=expected, error=type(error).__name__):
                self.assertEqual(classify_service_error(error), expected)
                self.assertNotIn("private-provider-detail", ERROR_MESSAGES[expected])

    def test_wrapped_embedding_failure_preserves_the_underlying_cause(self):
        error = RuntimeError("Embedding request failed")
        error.__cause__ = HttpError(429)
        self.assertEqual(classify_service_error(error), "rate_limited")

    def test_evaluator_and_message_recognition_do_not_count_service_failures_as_answers(self):
        for code, message in ERROR_MESSAGES.items():
            with self.subTest(code=code):
                self.assertEqual(service_error_code(message), code)
                self.assertEqual(outcome(message), "unavailable")
                self.assertEqual(service_error_code("คำตอบที่มีหลักฐาน\nหมายเหตุ: " + message), "")


class AvailabilityPipelineContract(unittest.TestCase):
    def setUp(self):
        patches = [
            patch.dict(os.environ, {"RAG_MODEL": MODEL, "ANSWER_CACHE_TTL_SECONDS": "3600"}),
            patch.dict(rag_service._EXHAUSTED_MODELS, {}, clear=True),
            patch.dict(rag_service._MODEL_FAILURES, {}, clear=True),
            patch.object(rag_service, "FALLBACK_MODELS", []),
            patch.object(rag_service, "SECONDARY_BASE_URL", ""),
            patch.object(rag_service, "SECONDARY_API_KEY", ""),
            patch("app.rag.crag_service.retrieve_evidence", return_value=document_evidence(DOCUMENT_CONTEXT)),
            patch("app.rag.crag_service.search_web_fallback", return_value=[]),
        ]
        mocks = []
        for patcher in patches:
            mocks.append(patcher.start())
            self.addCleanup(patcher.stop)
        self.retrieve, self.web = mocks[-2:]
        ai_service.clear_answer_cache()
        self.addCleanup(ai_service.clear_answer_cache)

    def quota(self, *keys):
        for key in keys or (MODEL,):
            rag_service._EXHAUSTED_MODELS[key] = time.monotonic() + 1200
            rag_service._MODEL_FAILURES[key] = "quota_exhausted"

    def test_known_exhausted_pool_does_no_retrieval_web_or_llm_work(self):
        self.quota()
        client = llm_client()
        response = run_crag_pipeline(QUESTION, client=client)
        self.assertEqual(response.answer, ERROR_MESSAGES["quota_exhausted"])
        self.assertEqual(response.error_code, "quota_exhausted")
        self.retrieve.assert_not_called()
        self.web.assert_not_called()
        client.chat.completions.create.assert_not_called()

    def test_exhausting_last_model_stops_web_and_next_question_also_skips_retrieval(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = HttpError(401, "This model reached daily limit.")
        first = run_crag_pipeline(QUESTION, client=client)
        second = run_crag_pipeline("เลือกหัวฉีดสำหรับงานฉีดพ่นอย่างไร", client=client)
        self.assertEqual(first.error_code, "quota_exhausted")
        self.assertEqual(second.answer, first.answer)
        self.assertEqual(self.retrieve.call_count, 1)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.web.assert_not_called()

    def test_available_primary_fallback_prevents_premature_short_circuit(self):
        self.quota()
        client = llm_client(result_json())
        with patch.object(rag_service, "FALLBACK_MODELS", ["available-fallback"]):
            response = run_crag_pipeline(QUESTION, client=client)
        self.assertEqual(response.source_type, "knowledge_base")
        self.assertEqual(response.error_code, "")
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "available-fallback")

    def test_available_secondary_prevents_premature_short_circuit(self):
        self.quota()
        primary = llm_client()
        secondary = llm_client(result_json())
        with patch.object(rag_service, "SECONDARY_BASE_URL", "https://secondary.example/v1"), \
             patch.object(rag_service, "SECONDARY_API_KEY", "offline"), \
             patch.object(rag_service, "SECONDARY_MODELS", [MODEL]), \
             patch.object(rag_service, "get_secondary_client", return_value=secondary):
            response = run_crag_pipeline(QUESTION, client=primary)
        self.assertEqual(response.source_type, "knowledge_base")
        primary.chat.completions.create.assert_not_called()
        secondary.chat.completions.create.assert_called_once()

    def test_quota_block_expires_and_does_not_retry_early_in_its_last_minute(self):
        self.quota()
        rag_service._EXHAUSTED_MODELS[MODEL] = time.monotonic() + 20
        self.assertEqual(rag_service.llm_pool_error(), "quota_exhausted")
        rag_service._EXHAUSTED_MODELS[MODEL] = time.monotonic() - 1
        response = run_crag_pipeline(QUESTION, client=llm_client(result_json()))
        self.assertEqual(response.grade, "CORRECT")
        self.assertNotIn(MODEL, rag_service._MODEL_FAILURES)

    def test_mixed_known_model_failures_are_not_claimed_to_be_all_quota(self):
        self.quota(MODEL, "other-model")
        rag_service._MODEL_FAILURES["other-model"] = "provider_auth"
        with patch.object(rag_service, "FALLBACK_MODELS", ["other-model"]):
            response = run_crag_pipeline(QUESTION)
        self.assertEqual(response.error_code, "provider_unavailable")
        self.retrieve.assert_not_called()

    def test_cached_grounded_answer_and_bot_usage_still_work_during_quota_outage(self):
        client = llm_client(result_json())
        with patch.object(rag_service, "get_llm_client", return_value=client):
            first = ai_service.ask_ai(QUESTION)
            self.quota()
            self.assertEqual(ai_service.ask_ai(QUESTION), first)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        self.retrieve.reset_mock()
        response = run_crag_pipeline("บอททำอะไรได้บ้าง")
        self.assertEqual(response.source_type, "bot_usage")
        self.retrieve.assert_not_called()
        self.web.assert_not_called()

    def test_waiting_on_an_identical_question_reports_timeout_without_an_extra_pipeline_call(self):
        pending = MagicMock()
        pending.result.side_effect = FutureTimeout()
        key = ai_service._key(QUESTION)
        with patch.dict(ai_service._inflight, {key: pending}, clear=True), \
             patch("app.services.ai_service.run_crag_pipeline") as run:
            self.assertEqual(ai_service.ask_ai(QUESTION), ERROR_MESSAGES["timeout"])
        run.assert_not_called()

    def test_retrieval_failure_is_not_reported_as_absent_evidence(self):
        self.retrieve.side_effect = TimeoutError("private-provider-detail")
        response = run_crag_pipeline(QUESTION, client=llm_client())
        self.assertEqual(response.answer, ERROR_MESSAGES["timeout"])
        self.assertNotEqual(response.answer, ABSTAIN_MESSAGE)
        self.assertNotIn("private-provider-detail", response.answer)

    def test_successful_fallback_answer_is_not_marked_unavailable(self):
        self.retrieve.side_effect = TimeoutError()
        self.web.return_value = [WebSearchResult("คู่มือ", "https://doa.go.th/example", "อัตราการไหล 500 ml")]
        response = run_crag_pipeline(QUESTION, client=llm_client(result_json(
            claims=[("อัตราการไหล 500 ml", "W1", "อัตราการไหล 500 ml")])))
        self.assertEqual(response.source_type, "web_fallback")
        self.assertEqual(response.error_code, "")
        self.assertNotIn(ERROR_MESSAGES["timeout"], response.answer)

    def test_genuinely_empty_results_remain_an_evidence_abstain(self):
        self.retrieve.return_value = []
        response = run_crag_pipeline(QUESTION, client=llm_client())
        self.assertEqual(response.answer, ABSTAIN_MESSAGE)
        self.assertEqual(response.error_code, "")

    def test_web_errors_preserve_confirmed_kb_claims_and_citations(self):
        self.web.side_effect = TimeoutError("private-provider-detail")
        response = run_crag_pipeline(QUESTION, client=llm_client(result_json("partial", missing=["ราคาหัวฉีด"])))
        self.assertEqual(response.source_type, "knowledge_base")
        self.assertEqual(response.grade, "AMBIGUOUS")
        self.assertEqual(response.error_code, "timeout")
        self.assertIn("500 ml/หัวฉีด", response.answer)
        self.assertIn("UAV07.pdf, หน้า 12", response.answer)
        self.assertIn(ERROR_MESSAGES["timeout"], response.answer)
        # The note sits right under the gap it explains, before the references (owner review 2026-10-20).
        gap, note, refs = (response.answer.index(s) for s in ("ยังยืนยันไม่ได้: ราคาหัวฉีด", ERROR_MESSAGES["timeout"], "แหล่งอ้างอิง:"))
        self.assertLess(gap, note)
        self.assertLess(note, refs)
        self.assertNotIn("private-provider-detail", response.answer)
        with patch("app.services.ai_service.ask_ai", return_value=response.answer):
            self.assertEqual(ask_live(QUESTION), (response.answer, False))

    def test_final_generation_quota_preserves_initial_verified_partial(self):
        self.web.return_value = [WebSearchResult("คู่มือ", "https://doa.go.th/example", "ราคาหัวฉีด 120 บาท")]
        client = llm_client(result_json("partial", missing=["ราคาหัวฉีด"]))
        complete = client.chat.completions.create.side_effect
        first = next(complete)
        client.chat.completions.create.side_effect = [first, HttpError(401, "This model reached daily limit.")]
        response = run_crag_pipeline(QUESTION, client=client)
        self.assertIn("500 ml/หัวฉีด", response.answer)
        self.assertIn("UAV07.pdf, หน้า 12", response.answer)
        self.assertEqual(response.grade, "AMBIGUOUS")
        self.assertEqual(response.error_code, "quota_exhausted")

    def test_web_internal_diagnostics_reach_user_error_code(self):
        self.retrieve.return_value = []
        web_client = MagicMock()
        web_client.search.side_effect = HttpError(401, "private-provider-detail")
        self.web.side_effect = lambda *a, **kw: search_web_fallback(*a, tavily_client=web_client, **kw)
        response = run_crag_pipeline(QUESTION, client=llm_client())
        self.assertEqual(response.answer, ERROR_MESSAGES["provider_auth"])
        self.assertTrue(any(d.get("error_code") == "provider_auth" for d in response.diagnostics))

    def test_unconfigured_web_is_not_reported_as_successful_search_without_evidence(self):
        self.retrieve.return_value = []
        self.web.side_effect = search_web_fallback
        with patch("app.rag.web_fallback.get_tavily_client", return_value=None):
            response = run_crag_pipeline(QUESTION, client=llm_client())
        self.assertEqual(response.error_code, "configuration")


class PlaygroundFailureReporting(unittest.TestCase):
    def test_live_ui_keeps_precise_pipeline_failure_codes_and_messages(self):
        with TestClient(app, base_url="http://127.0.0.1:8080", headers={"origin": "http://127.0.0.1:8080"}) as client:
            for code, message in ERROR_MESSAGES.items():
                with self.subTest(code=code), patch("app.services.ai_service.ask_ai", return_value=message):
                    response = client.post("/api/ask", json={"question": QUESTION, "mode": "live"})
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["error_code"], code)
                    self.assertEqual(response.json()["answer"], message)

    def test_daily_limit_401_is_quota_and_not_bad_key_in_ui(self):
        with TestClient(app, base_url="http://127.0.0.1:8080", headers={"origin": "http://127.0.0.1:8080"}) as client, \
             patch("app.playground.ask_live", side_effect=HttpError(401, "This model reached daily limit.")):
            response = client.post("/api/ask", json={"question": QUESTION, "mode": "live"})
        self.assertEqual(response.json()["error_code"], "quota_exhausted")
