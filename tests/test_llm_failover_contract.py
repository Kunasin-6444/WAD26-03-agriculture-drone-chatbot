import time
import unittest
from unittest.mock import MagicMock, patch

from app.rag import rag_service
from tests.helpers import llm_client


class _HttpError(Exception):
    def __init__(self, status_code, body=None):
        super().__init__(f"http {status_code}")
        self.status_code = status_code
        self.body = body or {"error": "This model reached daily limit."}


def _failing_client(error):
    client = MagicMock()
    client.chat.completions.create.side_effect = error
    return client


class CrossProviderFailoverContract(unittest.TestCase):
    def setUp(self):
        rag_service._EXHAUSTED_MODELS.clear()
        self.addCleanup(rag_service._EXHAUSTED_MODELS.clear)
        for name, value in [("FALLBACK_MODELS", ["primary-b"]), ("SECONDARY_BASE_URL", "https://second.example/v1"),
                            ("SECONDARY_API_KEY", "k"), ("SECONDARY_MODELS", ["second-a"]),
                            ("SECONDARY_REASONING_EFFORT", "")]:
            patcher = patch.object(rag_service, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.secondary = llm_client("from-secondary")
        patcher = patch.object(rag_service, "get_secondary_client", return_value=self.secondary)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_quota_exhausted_primary_fails_over_to_secondary_provider(self):
        primary = _failing_client(_HttpError(401))
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a"), "from-secondary")
        self.assertEqual(self.secondary.chat.completions.create.call_args.kwargs["model"], "second-a")
        # Both primary models were tried and cooled for a long time; the secondary was not.
        self.assertGreater(rag_service._EXHAUSTED_MODELS["primary-a"] - time.monotonic(), 600)
        self.assertGreater(rag_service._EXHAUSTED_MODELS["primary-b"] - time.monotonic(), 600)
        self.assertNotIn("secondary:second-a", rag_service._EXHAUSTED_MODELS)

    def test_failover_works_even_when_the_caller_allows_one_attempt(self):
        # KB generation uses max_attempts=1; instant quota errors must not block failover.
        primary = _failing_client(_HttpError(429, {"error": "quota"}))
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a", max_attempts=1), "from-secondary")

    def test_cooled_primary_is_skipped_without_calling_it(self):
        rag_service._EXHAUSTED_MODELS["primary-a"] = time.monotonic() + rag_service.DAILY_LIMIT_COOLDOWN_SECONDS
        rag_service._EXHAUSTED_MODELS["primary-b"] = time.monotonic() + rag_service.DAILY_LIMIT_COOLDOWN_SECONDS
        primary = llm_client("never")
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a"), "from-secondary")
        primary.chat.completions.create.assert_not_called()

    def test_timeouts_do_not_fail_over_or_exceed_the_attempt_cap(self):
        primary = _failing_client(TimeoutError("slow"))
        with self.assertRaises(RuntimeError):
            rag_service.call_llm([], primary, preferred_model="primary-a", max_attempts=1)
        self.assertEqual(primary.chat.completions.create.call_count, 1)
        self.secondary.chat.completions.create.assert_not_called()

    def test_same_model_name_on_both_providers_has_independent_cooldowns(self):
        with patch.object(rag_service, "SECONDARY_MODELS", ["primary-a"]):
            primary = _failing_client(_HttpError(401))
            rag_service.call_llm([], primary, preferred_model="primary-a")
            self.assertIn("primary-a", rag_service._EXHAUSTED_MODELS)
            self.assertNotIn("secondary:primary-a", rag_service._EXHAUSTED_MODELS)

    def test_both_providers_exhausted_is_reported_as_llm_unavailable(self):
        self.secondary.chat.completions.create.side_effect = _HttpError(429, {"error": "daily limit"})
        with self.assertRaises(rag_service.LLMUnavailableError):
            rag_service.call_llm([], _failing_client(_HttpError(401)), preferred_model="primary-a")

    def test_secondary_reasoning_effort_is_independent_of_primary(self):
        with patch.object(rag_service, "REASONING_EFFORT", "low"), \
             patch.object(rag_service, "SECONDARY_REASONING_EFFORT", ""):
            rag_service.call_llm([], _failing_client(_HttpError(401)), preferred_model="primary-a")
        self.assertNotIn("extra_body", self.secondary.chat.completions.create.call_args.kwargs)


class FailoverDisabledContract(unittest.TestCase):
    def setUp(self):
        rag_service._EXHAUSTED_MODELS.clear()
        self.addCleanup(rag_service._EXHAUSTED_MODELS.clear)
        for name, value in [("FALLBACK_MODELS", []), ("SECONDARY_BASE_URL", ""), ("SECONDARY_API_KEY", "")]:
            patcher = patch.object(rag_service, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_without_secondary_config_behaviour_is_unchanged(self):
        with patch.object(rag_service, "get_secondary_client") as get_client:
            with self.assertRaises(rag_service.LLMUnavailableError):
                rag_service.call_llm([], _failing_client(_HttpError(401)), preferred_model="primary-a")
        get_client.assert_not_called()

    def test_half_configured_secondary_stays_disabled(self):
        with patch.object(rag_service, "SECONDARY_BASE_URL", "https://second.example/v1"):
            self.assertFalse(rag_service.secondary_enabled())


if __name__ == "__main__":
    unittest.main()
