import unittest
from unittest.mock import MagicMock, patch

from app.services import ai_service
from app.services.line_service import reply_text
from app.services.rich_menu_service import build_rich_menu_request
from tests.line_helpers import InboxAppCase, event_payload


def postback_payload(token="mock-reply", data="richmenu_1", event_id="event-postback-1"):
    return {"destination": "Ubot", "events": [{
        "type": "postback", "postback": {"data": data}, "timestamp": 1727150000000,
        "source": {"type": "user", "userId": "Utest"}, "replyToken": token, "webhookEventId": event_id,
        "deliveryContext": {"isRedelivery": False}, "mode": "active"}]}


class LineIntegrationContractTests(InboxAppCase):
    def test_health_check(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_signature_missing_and_invalid_rejected_before_ai(self):
        self.assertEqual(self.client.post("/webhook", json={"events": []}).status_code, 422)
        self.assertEqual(self.client.post("/webhook", json={"events": []}, headers={"x-line-signature": "bad"}).status_code, 400)
        self.ask.assert_not_called()

    def test_signed_empty_verification_has_no_side_effects(self):
        self.assertEqual(self.post({"events": []}).status_code, 200)
        self.ask.assert_not_called()
        self.reply.assert_not_called()
        self.assertEqual(self.inbox.store.count(), 0)

    def test_signed_text_preserves_answer_and_citations(self):
        self.assertEqual(self.post(event_payload(), "/api/webhook").status_code, 200)
        self.assertEqual(self.wait_terminal()["state"], "done")
        self.ask.assert_called_once_with("หัวฉีดพัดส้ม")
        self.reply.assert_called_once_with("mock-reply", self.ask.return_value)

    def test_dummy_token_skips_expensive_pipeline(self):
        self.assertEqual(self.post(event_payload("0" * 32)).status_code, 200)
        self.assertEqual(self.inbox.store.count(), 0)
        self.ask.assert_not_called()
        self.reply.assert_not_called()

    def test_non_text_event_is_not_stored(self):
        self.assertEqual(self.post(event_payload(message_type="sticker")).status_code, 200)
        self.assertEqual(self.inbox.store.count(), 0)

    def test_ai_failure_returns_friendly_message_without_invented_citations(self):
        self.ask.side_effect = RuntimeError("Unavailable")
        self.assertEqual(self.post(event_payload()).status_code, 200)
        self.wait_terminal()
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
        for area, label in zip(menu.areas, ("ขึ้นทะเบียนโดรน", "ขึ้นทะเบียนนักบินโดรน", "ขออนุญาตบินโดรน",
                                            "กฎหมายการบินโดรน", "โดรนฉีดพ่นและหัวฉีด", "การใช้สารกำจัดวัชพืช")):
            self.assertIn(label, area.action.text)

    def test_rich_menu_text_gets_its_guide_through_the_inbox_without_the_pipeline(self):
        self.ask.side_effect = ai_service.ask_ai   # the real fast path, behind the inbox
        with patch("app.services.ai_service.run_crag_pipeline") as pipeline:
            self.assertEqual(self.post(event_payload(text="ขึ้นทะเบียนโดรน")).status_code, 200)
            self.assertEqual(self.wait_terminal()["state"], "done")
        pipeline.assert_not_called()
        answer = self.reply.call_args.args[1]
        self.assertIn("คู่มือการขึ้นทะเบียนโดรน", answer)
        self.assertNotIn("**", answer)   # LINE would show markdown literally

    def test_rich_menu_postback_is_stored_once_and_answered_from_the_guide(self):
        self.ask.side_effect = ai_service.ask_ai
        with patch("app.services.ai_service.run_crag_pipeline") as pipeline:
            self.assertEqual(self.post(postback_payload(data="richmenu_5")).status_code, 200)
            self.assertEqual(self.post(postback_payload(data="richmenu_5")).status_code, 200)   # LINE redelivery
            self.assertEqual(self.wait_terminal("event-postback-1")["state"], "done")
        pipeline.assert_not_called()
        self.assertEqual(self.inbox.store.count(), 1)
        self.assertIn("คู่มือโดรนฉีดพ่นทางการเกษตร", self.reply.call_args.args[1])

    def test_unknown_postback_is_ignored(self):
        self.assertEqual(self.post(postback_payload(data="richmenu_99")).status_code, 200)
        self.assertEqual(self.inbox.store.count(), 0)
        self.ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
