import time
import os
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
        # Fail over before spending budget on other models on the same gateway.
        self.assertGreater(rag_service._EXHAUSTED_MODELS["primary-a"] - time.monotonic(), 600)
        self.assertNotIn("primary-b", rag_service._EXHAUSTED_MODELS)
        self.assertEqual(primary.chat.completions.create.call_count, 1)
        self.assertNotIn("secondary:second-a", rag_service._EXHAUSTED_MODELS)

    def test_secondary_last_tries_the_gateway_fallbacks_first(self):
        primary = _failing_client(_HttpError(401))
        with patch.dict(os.environ, {"LLM_SECONDARY_ORDER": "last"}):
            self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a"), "from-secondary")
        tried = [call.kwargs["model"] for call in primary.chat.completions.create.call_args_list]
        self.assertEqual(tried, ["primary-a", "primary-b"])   # the gateway fallback before the other provider

    def test_failover_works_even_when_the_caller_allows_one_attempt(self):
        # KB generation uses max_attempts=1; instant quota errors must not block failover.
        primary = _failing_client(_HttpError(429, {"error": "quota"}))
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a", max_attempts=1), "from-secondary")

    def test_slow_primary_fallback_cannot_starve_configured_secondary(self):
        primary = MagicMock()
        primary.chat.completions.create.side_effect = [_HttpError(401), TimeoutError("fallback slow")]
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a", max_attempts=1), "from-secondary")
        self.assertEqual(primary.chat.completions.create.call_count, 1)

    def test_cooled_primary_is_skipped_without_calling_it(self):
        rag_service._EXHAUSTED_MODELS["primary-a"] = time.monotonic() + rag_service.DAILY_LIMIT_COOLDOWN_SECONDS
        rag_service._EXHAUSTED_MODELS["primary-b"] = time.monotonic() + rag_service.DAILY_LIMIT_COOLDOWN_SECONDS
        primary = llm_client("never")
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a"), "from-secondary")
        primary.chat.completions.create.assert_not_called()

    def test_timeout_respects_attempt_cap_then_the_next_stage_skips_the_stalled_model(self):
        primary = _failing_client(TimeoutError("slow"))
        with self.assertRaises(RuntimeError):
            rag_service.call_llm([], primary, preferred_model="primary-a", max_attempts=1)
        self.assertEqual(primary.chat.completions.create.call_count, 1)
        self.secondary.chat.completions.create.assert_not_called()
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a", max_attempts=1), "from-secondary")
        self.assertEqual(primary.chat.completions.create.call_count, 1)

    def test_timeout_uses_configured_secondary_when_another_attempt_is_available(self):
        primary = _failing_client(TimeoutError("slow"))
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a", max_attempts=2), "from-secondary")
        self.assertEqual(primary.chat.completions.create.call_count, 1)

    def test_server_outage_uses_secondary_without_retrying_the_same_gateway(self):
        primary = _failing_client(_HttpError(503, {"error": "unavailable"}))
        self.assertEqual(rag_service.call_llm([], primary, preferred_model="primary-a"), "from-secondary")
        self.assertEqual(primary.chat.completions.create.call_count, 1)

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

    def test_secondary_schema_support_does_not_force_it_on_primary_gateway(self):
        primary = _failing_client(_HttpError(401))
        with patch.object(rag_service, "STRUCTURED_OUTPUT", False), patch.object(rag_service, "SECONDARY_STRUCTURED_OUTPUT", True):
            rag_service.call_llm([], primary, preferred_model="primary-a")
        self.assertNotIn("response_format", primary.chat.completions.create.call_args.kwargs)
        self.assertEqual(self.secondary.chat.completions.create.call_args.kwargs["response_format"]["type"], "json_schema")


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
