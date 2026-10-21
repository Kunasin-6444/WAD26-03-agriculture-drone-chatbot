import logging
import asyncio
import time

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent

from app.config import LINE_CHANNEL_SECRET
from app.services.ai_service import ask_ai
from app.services.line_service import DUMMY_REPLY_TOKENS, push_text, reply_text, show_loading_animation
from app.services.rich_menu_service import get_rich_menu_preanswer

logger = logging.getLogger(__name__)

router = APIRouter()

parser = WebhookParser(LINE_CHANNEL_SECRET)


@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(...),
):
    # ── TIMING: total request start ──────────────────────────────────────────
    t_request_start = time.perf_counter()

    # ── STEP 1: Read & decode request body ───────────────────────────────────
    t0 = time.perf_counter()
    body = await request.body()
    body_text = body.decode("utf-8")
    t_body = time.perf_counter() - t0

    # ── STEP 2: Parse LINE signature & events ────────────────────────────────
    t0 = time.perf_counter()
    try:
        events = parser.parse(
            body_text,
            x_line_signature,
        )
    except InvalidSignatureError:
        logger.warning("Received webhook request with invalid signature.")
        raise HTTPException(
            status_code=400,
            detail="Invalid signature",
        )
    t_parse = time.perf_counter() - t0

    for event in events:
        # ── Rich Menu Postback Event ─────────────────────────────────────────
        if isinstance(event, PostbackEvent):
            reply_token = event.reply_token
            if not reply_token or reply_token in DUMMY_REPLY_TOKENS:
                continue
            postback_data = getattr(event.postback, "data", "")
            pre_answer = get_rich_menu_preanswer(postback_data)
            if pre_answer:
                sent = await run_in_threadpool(reply_text, reply_token, pre_answer)
                if not sent:
                    user_id = getattr(event.source, "user_id", None)
                    await run_in_threadpool(push_text, user_id, pre_answer)
            continue

        # ── Rich Menu or User Text Message Event ─────────────────────────────
        if (
            isinstance(event, MessageEvent)
            and isinstance(event.message, TextMessageContent)
        ):
            user_message = event.message.text
            reply_token = event.reply_token
            user_id = getattr(event.source, "user_id", None)

            if not reply_token or reply_token in DUMMY_REPLY_TOKENS:
                continue

            # ── Fast-path: Rich Menu Pre-Answer (Bypasses CRAG backend) ───────
            pre_answer = get_rich_menu_preanswer(user_message)
            if pre_answer:
                sent = await run_in_threadpool(reply_text, reply_token, pre_answer)
                if not sent:
                    await run_in_threadpool(push_text, user_id, pre_answer)
                continue

            # Trigger native LINE Loading Animation (bouncing dots) immediately
            loading = asyncio.create_task(run_in_threadpool(show_loading_animation, user_id, loading_seconds=20))

            # ── STEP 3: CRAG pipeline (ask_ai) ───────────────────────────────
            t0 = time.perf_counter()
            try:
                answer = await run_in_threadpool(ask_ai, user_message)
            except Exception as e:
                logger.error(f"Error processing user query in ask_ai: {e}")
                answer = (
                    "ขออภัยครับ ระบบกำลังประสบปัญหาชั่วคราวในการประมวลผล "
                    "กรุณาลองใหม่อีกครั้งในภายหลังครับ"
                )
            t_ask_ai = time.perf_counter() - t0

            sent = await run_in_threadpool(reply_text, reply_token, answer)
            if not sent:
                # Reply token may have expired on a slow answer: fall back to push
                # so the user still gets a reply instead of silence.
                await run_in_threadpool(push_text, user_id, answer)
            if not loading.done():
                loading.cancel()

    return {
        "status": "OK"
    }
