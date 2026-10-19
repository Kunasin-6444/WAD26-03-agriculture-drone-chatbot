import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.config import LINE_CHANNEL_SECRET
from app.services.line_service import DUMMY_REPLY_TOKENS

logger = logging.getLogger(__name__)

router = APIRouter()

parser = WebhookParser(LINE_CHANNEL_SECRET)


@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(...),
):
    body = await request.body()

    # Signature is checked before anything is stored or processed.
    try:
        events = parser.parse(
            body.decode("utf-8"),
            x_line_signature,
        )
    except (InvalidSignatureError, UnicodeDecodeError):
        logger.warning("Received webhook request with invalid signature.")
        raise HTTPException(
            status_code=400,
            detail="Invalid signature",
        )

    records = []
    for event in events:
        if (
            isinstance(event, MessageEvent)
            and isinstance(event.message, TextMessageContent)
        ):
            reply_token = event.reply_token
            if not reply_token or reply_token in DUMMY_REPLY_TOKENS:
                continue
            records.append({
                # LINE redelivers with the same webhookEventId; it is the dedupe key.
                "event_id": event.webhook_event_id or f"reply:{reply_token}",
                "user_id": getattr(event.source, "user_id", None),
                "reply_token": reply_token,
                "text": event.message.text,
            })

    if records:
        inbox = getattr(request.app.state, "line_inbox", None)
        if inbox is None:
            # Never ACK what was not persisted: a non-2xx makes LINE redeliver.
            logger.error("LINE inbox is not running; rejecting webhook so LINE redelivers.")
            raise HTTPException(status_code=503, detail="Inbox unavailable")
        try:
            added = await asyncio.to_thread(inbox.store.add_events, records)
        except Exception:
            logger.exception("Could not persist LINE events; rejecting so LINE redelivers.")
            raise HTTPException(status_code=503, detail="Inbox unavailable")
        if added < len(records):
            logger.info("Ignored %d duplicate LINE event(s).", len(records) - added)
        inbox.notify()

    return {
        "status": "OK"
    }
