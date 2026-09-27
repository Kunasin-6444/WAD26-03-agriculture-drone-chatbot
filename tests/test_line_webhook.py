import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import LINE_CHANNEL_SECRET
from app.main import app
from app.services.line_service import reply_text


def generate_line_signature(body: str, secret: str) -> str:
    """Generate a valid HMAC-SHA256 signature for LINE webhook payload."""
    hash_val = hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(hash_val).decode("utf-8")


class TestLineWebhook(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_root_endpoint(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("running", response.json().get("message", "").lower())

    def test_webhook_missing_signature_header(self):
        response = self.client.post("/webhook", json={"events": []})
        self.assertEqual(response.status_code, 422)

    def test_webhook_invalid_signature(self):
        body = json.dumps({"events": []})
        response = self.client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-line-signature": "invalid_signature_string",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid signature")

    def test_webhook_valid_empty_events_verification(self):
        body = json.dumps({"events": []})
        signature = generate_line_signature(body, LINE_CHANNEL_SECRET)

        response = self.client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-line-signature": signature,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "OK"})

    @patch("app.api.webhook.ask_ai")
    @patch("app.api.webhook.reply_text")
    def test_webhook_text_message_success(self, mock_reply_text, mock_ask_ai):
        mock_ask_ai.return_value = "อัตราการไหล 500 ml/หัวฉีด (แหล่งอ้างอิง: UAV07, หน้า 12)"

        payload = {
            "destination": "U1234567890",
            "events": [
                {
                    "type": "message",
                    "message": {
                        "type": "text",
                        "id": "100001",
                        "text": "หัวฉีดพัดส้มมีอัตราการไหลเท่าไร",
                        "quoteToken": "q_token_1",
                    },
                    "timestamp": 1727150000000,
                    "source": {"type": "user", "userId": "Uuser123"},
                    "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZR",
                    "deliveryContext": {"isRedelivery": False},
                    "replyToken": "test_reply_token_abc123",
                    "mode": "active",
                }
            ],
        }

        body = json.dumps(payload)
        signature = generate_line_signature(body, LINE_CHANNEL_SECRET)

        response = self.client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-line-signature": signature,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "OK"})
        mock_ask_ai.assert_called_once_with("หัวฉีดพัดส้มมีอัตราการไหลเท่าไร")
        mock_reply_text.assert_called_once_with(
            "test_reply_token_abc123",
            "อัตราการไหล 500 ml/หัวฉีด (แหล่งอ้างอิง: UAV07, หน้า 12)",
        )

    @patch("app.api.webhook.ask_ai")
    @patch("app.api.webhook.reply_text")
    def test_webhook_handles_ai_exception_gracefully(
        self, mock_reply_text, mock_ask_ai
    ):
        mock_ask_ai.side_effect = RuntimeError("Temporary LLM connection error")

        payload = {
            "destination": "U1234567890",
            "events": [
                {
                    "type": "message",
                    "message": {
                        "type": "text",
                        "id": "100002",
                        "text": "คำถามทดสอบข้อผิดพลาด",
                        "quoteToken": "q_token_2",
                    },
                    "timestamp": 1727150000000,
                    "source": {"type": "user", "userId": "Uuser123"},
                    "webhookEventId": "01FZ74A0TDDPYRVKNK77XKC3ZS",
                    "deliveryContext": {"isRedelivery": False},
                    "replyToken": "test_reply_token_err",
                    "mode": "active",
                }
            ],
        }

        body = json.dumps(payload)
        signature = generate_line_signature(body, LINE_CHANNEL_SECRET)

        response = self.client.post(
            "/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "x-line-signature": signature,
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_reply_text.assert_called_once()
        sent_reply = mock_reply_text.call_args[0][1]
        self.assertIn("ขออภัย", sent_reply)

    def test_reply_text_ignores_dummy_tokens(self):
        # Dummy verification tokens from LINE should be skipped cleanly
        result_zero = reply_text("00000000000000000000000000000000", "ข้อความทดสอบ")
        self.assertTrue(result_zero)

        result_f = reply_text("ffffffffffffffffffffffffffffffff", "ข้อความทดสอบ")
        self.assertTrue(result_f)

        result_empty = reply_text("", "ข้อความทดสอบ")
        self.assertTrue(result_empty)


if __name__ == "__main__":
    unittest.main()
