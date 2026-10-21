import logging
import time

from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.config import LINE_CHANNEL_SECRET
from app.services.ai_service import ask_ai
from app.services.line_service import reply_text

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
        if (
            isinstance(event, MessageEvent)
            and isinstance(event.message, TextMessageContent)
        ):
            user_message = event.message.text
            reply_token = event.reply_token

            # ── STEP 3: CRAG pipeline (ask_ai) ───────────────────────────────
            t0 = time.perf_counter()
            try:
                answer = ask_ai(user_message)
            except Exception as e:
                logger.error(f"Error processing user query in ask_ai: {e}")
                answer = (
                    "ขออภัยครับ ระบบกำลังประสบปัญหาชั่วคราวในการประมวลผล "
                    "กรุณาลองใหม่อีกครั้งในภายหลังครับ"
                )
            t_ask_ai = time.perf_counter() - t0

            # ── STEP 4: Send reply back to LINE ──────────────────────────────
            t0 = time.perf_counter()
            reply_text(
                reply_token,
                answer,
            )
            t_reply = time.perf_counter() - t0

            # ── TIMING SUMMARY ────────────────────────────────────────────────
            t_total = time.perf_counter() - t_request_start
            print(
                "\n"
                "═══════════════════════════════════════════════════════════\n"
                f"[TIMING] User: {user_message[:60]!r}\n"
                "───────────────────────────────────────────────────────────\n"
                f"  LINE → FastAPI (body read)    : {t_body * 1000:7.1f} ms\n"
                f"  LINE signature verify + parse : {t_parse * 1000:7.1f} ms\n"
                f"  CRAG pipeline (ask_ai)        : {t_ask_ai * 1000:7.1f} ms\n"
                f"  LINE reply API call           : {t_reply * 1000:7.1f} ms\n"
                "───────────────────────────────────────────────────────────\n"
                f"  TOTAL response time           : {t_total * 1000:7.1f} ms\n"
                "═══════════════════════════════════════════════════════════\n",
                flush=True,
            )

    return {
        "status": "OK"
    }