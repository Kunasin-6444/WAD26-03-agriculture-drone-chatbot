import asyncio
import base64
import hashlib
import hmac
import json
import threading
import unittest
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient

from app.config import LINE_CHANNEL_SECRET
from app.main import app
from app.services.line_service import reply_text
from app.services.rich_menu_service import build_rich_menu_request


def event_payload(token="mock-reply", message_type="text", text="หัวฉีดพัดส้ม"):
    return {
        "destination": "Ubot",
        "events": [
            {
                "type": "message",
                "message": {"type": message_type, "id": "1", "text": text, "quoteToken": "q"},
                "timestamp": 1727150000000,
                "source": {"type": "user", "userId": "Utest"},
                "replyToken": token,
                "webhookEventId": "event-1",
                "deliveryContext": {"isRedelivery": False},
                "mode": "active",
            }
        ],
    }


def postback_payload(token="mock-reply", data="richmenu_1"):
    return {
        "destination": "Ubot",
        "events": [
            {
                "type": "postback",
                "postback": {"data": data},
                "timestamp": 1727150000000,
                "source": {"type": "user", "userId": "Utest"},
                "replyToken": token,
                "webhookEventId": "event-postback-1",
                "deliveryContext": {"isRedelivery": False},
                "mode": "active",
            }
        ],
    }


def signed_request(payload):
    body = json.dumps(payload, ensure_ascii=False)
    digest = hmac.new(LINE_CHANNEL_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return body, {"x-line-signature": base64.b64encode(digest).decode(), "Content-Type": "application/json"}


class LineIntegrationContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        patches = [
            patch("app.api.webhook.show_loading_animation", return_value=True),
            patch("app.api.webhook.ask_ai", return_value="หัวฉีด 500 ml\n\nแหล่งอ้างอิง:\n[1] UAV07.pdf, หน้า 12"),
            patch("app.api.webhook.reply_text", return_value=True),
        ]
        self.loading, self.ask, self.reply = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def test_health_check(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_signature_missing_and_invalid_rejected_before_ai(self):
        self.assertEqual(self.client.post("/webhook", json={"events": []}).status_code, 422)
        self.assertEqual(self.client.post("/webhook", json={"events": []}, headers={"x-line-signature": "bad"}).status_code, 400)
        self.ask.assert_not_called()

    def test_signed_empty_verification_has_no_side_effects(self):
        body, headers = signed_request({"events": []})
        self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        self.ask.assert_not_called()
        self.reply.assert_not_called()

    def test_signed_text_preserves_answer_and_citations(self):
        body, headers = signed_request(event_payload())
        self.assertEqual(self.client.post("/api/webhook", content=body, headers=headers).status_code, 200)
        self.ask.assert_called_once_with("หัวฉีดพัดส้ม")
        self.reply.assert_called_once_with("mock-reply", self.ask.return_value)

    def test_dummy_token_skips_expensive_pipeline(self):
        body, headers = signed_request(event_payload("0" * 32))
        self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        self.ask.assert_not_called()
        self.reply.assert_not_called()

    def test_ai_failure_returns_friendly_message_without_invented_citations(self):
        self.ask.side_effect = RuntimeError("Unavailable")
        body, headers = signed_request(event_payload())
        self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        answer = self.reply.call_args.args[1]
        self.assertIn("ปัญหาชั่วคราว", answer)
        self.assertNotIn("UAV", answer)

    def test_line_sender_does_not_silently_truncate_citation(self):
        api = MagicMock()
        with patch("app.services.line_service.ApiClient"), patch("app.services.line_service.MessagingApi", return_value=api):
            self.assertTrue(reply_text("mock-token", "ก" * 5000 + "\nUAV07.pdf หน้า 12"))
        request = api.reply_message.call_args.args[0]
        self.assertIn("คำตอบยาวเกิน", request.messages[0].text)
        self.assertLess(len(request.messages[0].text), 4950)

    def test_rich_menu_structure_and_buttons(self):
        menu = build_rich_menu_request()
        self.assertEqual(len(menu.areas), 6)
        self.assertIn("ขึ้นทะเบียนโดรน", menu.areas[0].action.text)
        self.assertIn("ขึ้นทะเบียนนักบินโดรน", menu.areas[1].action.text)
        self.assertIn("ขออนุญาตบินโดรน", menu.areas[2].action.text)
        self.assertIn("กฎหมายการบินโดรน", menu.areas[3].action.text)
        self.assertIn("โดรนฉีดพ่นและหัวฉีด", menu.areas[4].action.text)
        self.assertIn("การใช้สารกำจัดวัชพืช", menu.areas[5].action.text)

    def test_rich_menu_preanswer_fastpath_bypasses_crag(self):
        body, headers = signed_request(event_payload(text="ขึ้นทะเบียนโดรน"))
        self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        # CRAG backend must NOT be called for Rich Menu pre-answers
        self.ask.assert_not_called()
        self.reply.assert_called_once()
        answer = self.reply.call_args.args[1]
        self.assertIn("คู่มือการขึ้นทะเบียนโดรน", answer)

    def test_rich_menu_postback_event_returns_preanswer(self):
        body, headers = signed_request(postback_payload(data="richmenu_5"))
        self.assertEqual(self.client.post("/webhook", content=body, headers=headers).status_code, 200)
        self.ask.assert_not_called()
        self.reply.assert_called_once()
        answer = self.reply.call_args.args[1]
        self.assertIn("คู่มือโดรนฉีดพ่นทางการเกษตร", answer)

    def test_slow_ai_does_not_block_async_event_loop(self):
        entered, release = threading.Event(), threading.Event()

        def slow_answer(_):
            entered.set()
            release.wait(timeout=5)
            return "mock answer"

        self.ask.side_effect = slow_answer

        async def verify():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                body, headers = signed_request(event_payload())
                pending = asyncio.create_task(client.post("/webhook", content=body, headers=headers))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    health = await asyncio.wait_for(client.get("/"), timeout=1)
                    self.assertEqual(health.status_code, 200)
                finally:
                    release.set()
                    await pending

        asyncio.run(verify())
