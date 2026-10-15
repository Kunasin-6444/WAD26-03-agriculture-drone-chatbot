import time
import unittest
from unittest.mock import patch

from app.rag import rag_service
from tests.helpers import llm_client

MODEL = "only-model"


class CooldownPolicyContract(unittest.TestCase):
    def setUp(self):
        rag_service._EXHAUSTED_MODELS.clear()
        self.addCleanup(rag_service._EXHAUSTED_MODELS.clear)
        patcher = patch.object(rag_service, "FALLBACK_MODELS", [])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_single_model_in_transient_cooldown_is_still_tried(self):
        rag_service._EXHAUSTED_MODELS[MODEL] = time.monotonic() + rag_service.TRANSIENT_COOLDOWN_SECONDS - 5
        client = llm_client("answer")
        self.assertEqual(rag_service.call_llm([], client, preferred_model=MODEL), "answer")
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_successful_call_clears_the_cooldown(self):
        rag_service._EXHAUSTED_MODELS[MODEL] = time.monotonic() + 30
        rag_service.call_llm([], llm_client("answer"), preferred_model=MODEL)
        self.assertNotIn(MODEL, rag_service._EXHAUSTED_MODELS)

    def test_daily_limit_cooldown_still_fails_fast_without_calling_provider(self):
        rag_service._EXHAUSTED_MODELS[MODEL] = time.monotonic() + rag_service.DAILY_LIMIT_COOLDOWN_SECONDS
        client = llm_client("answer")
        with self.assertRaises(rag_service.LLMUnavailableError):
            rag_service.call_llm([], client, preferred_model=MODEL)
        client.chat.completions.create.assert_not_called()

    def test_available_model_is_preferred_over_cooling_one(self):
        with patch.object(rag_service, "FALLBACK_MODELS", ["other-model"]):
            rag_service._EXHAUSTED_MODELS[MODEL] = time.monotonic() + 30
            client = llm_client("answer")
            rag_service.call_llm([], client, preferred_model=MODEL)
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "other-model")


if __name__ == "__main__":
    unittest.main()
