"""Contract tests for LINE delivery reliability (durable inbox + worker).

All offline: the LINE send functions and ask_ai are fakes, and the SQLite inbox lives in a
temp directory. No test can reach LINE or write the production inbox.
"""
import concurrent.futures
import asyncio
import sqlite3
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from linebot.v3.messaging.exceptions import ApiException
from urllib3.exceptions import MaxRetryError, NewConnectionError, ReadTimeoutError

from app.main import app
from app.services import line_service
from app.services.line_inbox import FRIENDLY_ERROR, InboxStore, LineInbox, PUSH_RETRY_WINDOW_SECONDS, retry_key_for
from app.services.line_service import (
    DELIVERED, PERMANENT, RETRYABLE, TOKEN_INVALID, UNKNOWN, SendResult, classify_send_error,
)
from tests.line_helpers import InboxAppCase, event_payload, signed_request, wait_for


class WebhookIntakeTests(InboxAppCase):
    def test_signed_duplicate_event_is_processed_and_replied_once(self):
        for _ in range(3):  # LINE redelivery reuses webhookEventId
            self.assertEqual(self.post(event_payload()).status_code, 200)
        self.wait_terminal()
        time.sleep(0.2)  # any wrongly-accepted duplicate would have been claimed by now
        self.assertEqual(self.inbox.store.count(), 1)
        self.assertEqual(self.ask.call_count, 1)
        self.assertEqual(self.reply.call_count, 1)

    def test_concurrent_duplicates_are_stored_and_replied_once(self):
        body, headers = signed_request(event_payload())
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            codes = list(pool.map(lambda _: self.client.post("/webhook", content=body, headers=headers).status_code, range(8)))
        self.assertEqual(codes, [200] * 8)
        self.wait_terminal()
        time.sleep(0.2)
        self.assertEqual(self.inbox.store.count(), 1)
        self.assertEqual(self.reply.call_count, 1)

    def test_distinct_events_in_one_request_all_processed(self):
        payload = event_payload(event_id="a", token="tok-a")
        second = event_payload(event_id="b", token="tok-b")["events"][0]
        payload["events"].append(second)
        self.assertEqual(self.post(payload).status_code, 200)
        self.wait_terminal("a"); self.wait_terminal("b")
        self.assertEqual({c.args[0] for c in self.reply.call_args_list}, {"tok-a", "tok-b"})

    def test_ack_is_prompt_and_loop_free_while_ai_is_blocked(self):
        entered, release = threading.Event(), threading.Event()

        def slow_answer(_):
            entered.set()
            release.wait(timeout=10)
            return "mock answer"
        self.ask.side_effect = slow_answer
        try:
            started = time.monotonic()
            self.assertEqual(self.post(event_payload()).status_code, 200)
            self.assertLess(time.monotonic() - started, 1.0)  # did not wait for RAG
            self.assertTrue(entered.wait(2), "worker never started the AI call")
            self.assertEqual(self.state(), "processing")
            self.reply.assert_not_called()
            self.assertEqual(self.client.get("/").status_code, 200)  # event loop still serving
        finally:
            release.set()
        self.assertEqual(self.wait_terminal()["state"], "done")
        self.reply.assert_called_once_with("mock-reply", "mock answer")

    def test_invalid_signature_stores_and_processes_nothing(self):
        body, headers = signed_request(event_payload())
        bad = {**headers, "x-line-signature": "AAAA" + headers["x-line-signature"][4:]}
        self.assertEqual(self.client.post("/webhook", content=body, headers=bad).status_code, 400)
        forged, _ = signed_request(event_payload(text="อื่น"))  # valid signature of a different body
        self.assertEqual(self.client.post("/webhook", content=forged, headers=headers).status_code, 400)
        wrong_secret, other = signed_request(event_payload(), secret="not-the-channel-secret")
        self.assertEqual(self.client.post("/webhook", content=wrong_secret, headers=other).status_code, 400)
        time.sleep(0.1)
        self.assertEqual(self.inbox.store.count(), 0)
        self.ask.assert_not_called()
        self.reply.assert_not_called()

    def test_not_acknowledged_when_inbox_unavailable(self):
        with patch.object(self.inbox.store, "add_events", side_effect=OSError("disk full")):
            self.assertEqual(self.post(event_payload()).status_code, 503)  # LINE will redeliver
        app.state.line_inbox = None
        try:
            self.assertEqual(self.post(event_payload()).status_code, 503)
            self.assertEqual(self.post({"events": []}).status_code, 200)  # nothing to persist
        finally:
            app.state.line_inbox = self.inbox
        self.ask.assert_not_called()

    def test_finished_rows_drop_user_text_token_and_answer(self):
        self.post(event_payload())
        row = self.wait_terminal()
        self.assertEqual((row["text"], row["reply_token"], row["answer"]), ("", "", None))
        self.assertEqual(row["outcome"], "delivered_reply")


class SendOutcomeTests(InboxAppCase):
    def test_ambiguous_reply_outcome_is_never_pushed_or_resent(self):
        self.reply.return_value = SendResult(UNKNOWN, "ReadTimeoutError")
        self.post(event_payload())
        row = self.wait_terminal()
        time.sleep(0.2)
        self.assertEqual((row["state"], row["outcome"]), ("unknown_outcome", "reply_unknown"))
        self.assertEqual(self.reply.call_count, 1)
        self.push.assert_not_called()

    def test_verified_invalid_reply_token_falls_back_to_push_with_stable_retry_key(self):
        self.reply.return_value = SendResult(TOKEN_INVALID, "http_400_invalid_reply_token")
        self.post(event_payload())
        row = self.wait_terminal()
        self.assertEqual((row["state"], row["outcome"]), ("done", "delivered_push"))
        self.push.assert_called_once_with("Utest", self.ask.return_value, retry_key_for("event-1"))

    def test_retryable_reply_failure_retries_without_rerunning_ai(self):
        self.reply.side_effect = [SendResult(RETRYABLE, "http_429"), SendResult(DELIVERED)]
        self.post(event_payload())
        row = self.wait_terminal()
        self.assertEqual(row["outcome"], "delivered_reply")
        self.assertEqual(self.reply.call_count, 2)
        self.assertEqual(self.ask.call_count, 1)
        self.push.assert_not_called()

    def test_retryable_failures_stop_after_max_attempts(self):
        self.reply.return_value = SendResult(RETRYABLE, "http_429")
        self.post(event_payload())
        row = self.wait_terminal()
        self.assertEqual((row["state"], row["outcome"]), ("failed_permanent", "retries_exhausted"))
        self.assertEqual(self.reply.call_count, self.inbox.store.max_attempts)
        self.push.assert_not_called()

    def test_permanent_reply_failure_is_terminal_without_push(self):
        self.reply.return_value = SendResult(PERMANENT, "http_403")
        self.post(event_payload())
        row = self.wait_terminal()
        self.assertEqual((row["state"], row["outcome"]), ("failed_permanent", "reply_permanent"))
        self.push.assert_not_called()

    def test_unknown_push_outcome_is_retried_only_with_the_same_retry_key(self):
        self.reply.return_value = SendResult(TOKEN_INVALID)
        self.push.side_effect = [SendResult(UNKNOWN, "ReadTimeoutError"), SendResult(DELIVERED)]
        self.post(event_payload())
        row = self.wait_terminal()
        self.assertEqual(row["outcome"], "delivered_push")
        self.assertEqual(self.reply.call_count, 1)  # the reply token is not reused
        keys = {call.args[2] for call in self.push.call_args_list}
        self.assertEqual(keys, {retry_key_for("event-1")})
        self.assertEqual(self.push.call_count, 2)

    def test_push_that_stays_unknown_ends_as_unknown_outcome(self):
        self.reply.return_value = SendResult(TOKEN_INVALID)
        self.push.return_value = SendResult(UNKNOWN, "ReadTimeoutError")
        self.post(event_payload())
        row = self.wait_terminal()
        self.assertEqual((row["state"], row["outcome"]), ("unknown_outcome", "push_unknown"))
        self.assertEqual(self.push.call_count, self.inbox.store.max_attempts)

    def test_ai_exception_still_delivers_friendly_message(self):
        self.ask.side_effect = RuntimeError("boom")
        self.post(event_payload())
        self.wait_terminal()
        self.reply.assert_called_once_with("mock-reply", FRIENDLY_ERROR)


class RestartRecoveryTests(InboxAppCase):
    # Long enough that a deliberately stuck AI call is not re-queued before the "crash",
    # short enough that the restarted worker recovers the row within a few seconds.
    lease_seconds = "1.5"

    def test_uniqueness_survives_restart(self):
        self.post(event_payload())
        self.wait_terminal()
        self.stop_app()
        self.start_app()
        self.assertEqual(self.post(event_payload()).status_code, 200)  # LINE redelivers after our restart
        time.sleep(0.3)
        self.assertEqual(self.inbox.store.count(), 1)
        self.assertEqual(self.reply.call_count, 1)

    def test_accepted_event_not_yet_answered_is_processed_after_restart(self):
        release = threading.Event()
        calls = []

        def answer(_):
            calls.append(1)
            if len(calls) == 1:
                release.wait(timeout=10)  # first process "dies" while the AI is running
            return "recovered answer"
        self.ask.side_effect = answer
        self.inbox.shutdown_grace = 0.05
        self.post(event_payload())
        self.assertTrue(wait_for(lambda: self.state() == "processing"))
        threading.Timer(0.3, release.set).start()  # frees the stuck thread so shutdown can finish
        self.stop_app()
        self.reply.assert_not_called()
        self.assertEqual(self.inbox.store.get("event-1")["state"], "processing")

        self.start_app()  # lease expires, row is re-queued and answered exactly once
        row = self.wait_terminal(timeout=8)
        self.assertEqual(row["state"], "done")
        self.reply.assert_called_once_with("mock-reply", "recovered answer")

    def test_crash_during_send_is_unknown_and_never_resent(self):
        self.stop_app()
        store = InboxStore(self.db_path, lease_seconds=0.2)
        store.add_events([{"event_id": "event-1", "user_id": "Utest", "reply_token": "mock-reply", "text": "q"}])
        row = store.claim()
        self.assertTrue(store.set_answer("event-1", row["claim_token"], "answer"))
        self.assertTrue(store.begin_send("event-1", row["claim_token"]))  # ...then the process dies
        time.sleep(0.3)

        self.start_app()
        row = self.wait_terminal(timeout=5)
        self.assertEqual((row["state"], row["outcome"]), ("unknown_outcome", "unknown"))
        self.reply.assert_not_called()
        self.push.assert_not_called()
        self.ask.assert_not_called()


class StoreContractTests(unittest.TestCase):
    def setUp(self):
        import shutil, tempfile
        tmp = tempfile.mkdtemp(prefix="line-store-test-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.store = InboxStore(f"{tmp}/inbox.sqlite3", lease_seconds=0.2)
        self.event = {"event_id": "e1", "user_id": "U1", "reply_token": "t", "text": "q"}

    def test_duplicate_ids_are_ignored_even_inside_one_batch(self):
        self.assertEqual(self.store.add_events([self.event, dict(self.event)]), 1)
        self.assertEqual(self.store.add_events([self.event]), 0)
        self.assertEqual(self.store.count(), 1)

    def test_only_one_claimant_wins_a_row(self):
        self.store.add_events([self.event])
        with concurrent.futures.ThreadPoolExecutor(6) as pool:
            claims = [c for c in pool.map(lambda _: self.store.claim(), range(6)) if c is not None]
        self.assertEqual(len(claims), 1)

    def test_stale_claim_cannot_overwrite_a_newer_one(self):
        self.store.add_events([self.event])
        stale = self.store.claim()
        time.sleep(0.3)
        self.store.reap()
        fresh = self.store.claim()
        self.assertFalse(self.store.finish("e1", stale["claim_token"], "done", "delivered_reply"))
        self.assertTrue(self.store.finish("e1", fresh["claim_token"], "done", "delivered_reply"))
        self.assertEqual(self.store.get("e1")["state"], "done")

    def test_old_push_retry_key_is_not_reused_after_long_outage(self):
        self.store.add_events([self.event])
        row = self.store.claim()
        self.store.set_answer("e1", row["claim_token"], "persisted answer")
        self.store.begin_send("e1", row["claim_token"])
        self.store.begin_push("e1", row["claim_token"])
        self.store.retry_later("e1", row["claim_token"], 0, "retry", reply_dead=True)
        with sqlite3.connect(self.store.path) as connection:
            connection.execute("UPDATE events SET push_started_at = ? WHERE event_id = 'e1'", (time.time() - PUSH_RETRY_WINDOW_SECONDS - 1,))
        row = self.store.claim()
        with patch("app.services.line_inbox.send_reply") as reply, patch("app.services.line_inbox.send_push") as push:
            asyncio.run(LineInbox(self.store)._deliver(row))
        reply.assert_not_called()
        push.assert_not_called()
        self.assertEqual(self.store.get("e1")["outcome"], "push_retry_window_expired")


class SendClassificationTests(unittest.TestCase):
    def api_error(self, status, body=b""):
        error = ApiException(status=status, reason="x")
        error.body = body
        return error

    def test_http_errors_are_classified_without_favouring_a_resend(self):
        cases = [
            (400, b'{"message":"Invalid reply token"}', TOKEN_INVALID),
            (400, b'{"message":"The request body has 1 error(s)"}', PERMANENT),
            (401, b"", PERMANENT),
            (403, b"", PERMANENT),
            (409, b"", PERMANENT),  # no retry key on a generic/reply request
            (429, b"", RETRYABLE),
            (500, b"", UNKNOWN),
            (503, b"", UNKNOWN),
        ]
        for status, body, expected in cases:
            with self.subTest(status=status):
                self.assertEqual(classify_send_error(self.api_error(status, body)).outcome, expected)

    def test_timeouts_and_resets_are_unknown_but_unmade_connections_are_retryable(self):
        self.assertEqual(classify_send_error(ReadTimeoutError(None, "/v2/bot/message/reply", "slow")).outcome, UNKNOWN)
        self.assertEqual(classify_send_error(ConnectionResetError()).outcome, UNKNOWN)
        self.assertEqual(classify_send_error(TimeoutError()).outcome, UNKNOWN)
        refused = MaxRetryError(None, "/v2/bot/message/reply", NewConnectionError(None, "refused"))
        self.assertEqual(classify_send_error(refused).outcome, RETRYABLE)

    def test_409_is_accepted_only_for_a_push_using_retry_key(self):
        error = self.api_error(409, b'{"message":"The retry key is already accepted"}')
        self.assertEqual(classify_send_error(error).outcome, PERMANENT)
        self.assertEqual(classify_send_error(error, retry_key_used=True).outcome, DELIVERED)

    def test_incidental_reply_token_text_does_not_trigger_push(self):
        error = self.api_error(400, b'{"message":"Other validation error involving reply token"}')
        self.assertEqual(classify_send_error(error).outcome, PERMANENT)

    def test_string_exception_reason_does_not_break_classification(self):
        error = RuntimeError("network")
        error.reason = "not an exception"
        self.assertEqual(classify_send_error(error).outcome, UNKNOWN)

    def test_send_reply_reports_classified_result_and_reply_text_stays_boolean(self):
        api = MagicMock()
        api.reply_message.side_effect = self.api_error(400, b'{"message":"Invalid reply token"}')
        with patch("app.services.line_service.ApiClient"), patch("app.services.line_service.MessagingApi", return_value=api):
            self.assertEqual(line_service.send_reply("tok", "hi").outcome, TOKEN_INVALID)
            self.assertFalse(line_service.reply_text("tok", "hi"))

    def test_push_passes_retry_key_and_timeout(self):
        api = MagicMock()
        with patch("app.services.line_service.ApiClient"), patch("app.services.line_service.MessagingApi", return_value=api):
            self.assertTrue(line_service.send_push("Ureal", "hi", "key-1").delivered)
        self.assertEqual(api.push_message.call_args.kwargs["x_line_retry_key"], "key-1")
        self.assertEqual(api.push_message.call_args.kwargs["_request_timeout"], line_service.SEND_TIMEOUT)

    def test_push_refuses_fake_targets_without_calling_line(self):
        with patch("app.services.line_service.MessagingApi") as api:
            self.assertEqual(line_service.send_push("test_user", "hi").outcome, PERMANENT)
            self.assertEqual(line_service.send_push(None, "hi").outcome, PERMANENT)
        api.assert_not_called()


class WithoutLifespanTests(unittest.TestCase):
    def test_events_are_rejected_not_acknowledged_when_inbox_was_never_started(self):
        from fastapi.testclient import TestClient
        client = TestClient(app)  # no `with`: lifespan (and so the inbox) never runs
        previous = getattr(app.state, "line_inbox", None)
        app.state.line_inbox = None
        try:
            body, headers = signed_request(event_payload())
            self.assertEqual(client.post("/webhook", content=body, headers=headers).status_code, 503)
        finally:
            app.state.line_inbox = previous


if __name__ == "__main__":
    unittest.main()
