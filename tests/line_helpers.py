"""Shared fixtures for LINE webhook tests: signed requests and an isolated inbox app.

Nothing here talks to LINE: the send functions and ask_ai are patched on
`app.services.line_inbox`, and the inbox database lives in a per-test temp directory.
"""
import base64
import hashlib
import hmac
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import LINE_CHANNEL_SECRET
from app.main import app
from app.services.line_service import DELIVERED, SendResult

TERMINAL = {"done", "failed_permanent", "unknown_outcome"}


def event_payload(token="mock-reply", message_type="text", event_id="event-1", text="หัวฉีดพัดส้ม", user_id="Utest"):
    return {"destination": "Ubot", "events": [{"type": "message", "message": {"type": message_type, "id": "1", "text": text, "quoteToken": "q"},
        "timestamp": 1727150000000, "source": {"type": "user", "userId": user_id}, "replyToken": token,
        "webhookEventId": event_id, "deliveryContext": {"isRedelivery": False}, "mode": "active"}]}


def signed_request(payload, secret=LINE_CHANNEL_SECRET):
    body = json.dumps(payload, ensure_ascii=False)
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return body, {"x-line-signature": base64.b64encode(digest).decode(), "Content-Type": "application/json"}


def wait_for(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class InboxAppCase(unittest.TestCase):
    """Runs the real app (lifespan, webhook, worker) against a temp SQLite file and fakes."""

    lease_seconds = "120"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="line-inbox-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = str(Path(self.tmp) / "inbox.sqlite3")
        env = patch.dict(os.environ, {"LINE_INBOX_DB_PATH": self.db_path, "WARMUP_ON_STARTUP": "false",
                                      "LINE_INBOX_LEASE_SECONDS": self.lease_seconds})
        env.start()
        self.addCleanup(env.stop)
        self.ask = self.patch("app.services.line_inbox.ask_ai", return_value="หัวฉีด 500 ml\n\nแหล่งอ้างอิง:\n[1] UAV07.pdf, หน้า 12")
        self.reply = self.patch("app.services.line_inbox.send_reply", return_value=SendResult(DELIVERED))
        self.push = self.patch("app.services.line_inbox.send_push", return_value=SendResult(DELIVERED))
        self.loading = self.patch("app.services.line_inbox.show_loading_animation", return_value=True)
        self.client = None
        self.addCleanup(self.stop_app)
        self.start_app()

    def start_app(self):
        """Run the real lifespan (opens the inbox, starts the worker)."""
        self.client = TestClient(app)
        self.client.__enter__()
        self.inbox = app.state.line_inbox
        self.inbox.backoff = (0.05,)

    def stop_app(self):
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None

    def patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def post(self, payload, path="/webhook"):
        body, headers = signed_request(payload)
        return self.client.post(path, content=body, headers=headers)

    def state(self, event_id="event-1"):
        row = self.inbox.store.get(event_id)
        return row["state"] if row else None

    def wait_terminal(self, event_id="event-1", timeout=5.0):
        self.assertTrue(wait_for(lambda: self.state(event_id) in TERMINAL, timeout),
                        f"event never finished; state={self.state(event_id)}")
        return self.inbox.store.get(event_id)
