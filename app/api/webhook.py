import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.config import LINE_CHANNEL_SECRET
from app.services.ai_service import ask_ai
from app.services.line_service import push_text, reply_text, show_loading_animation

logger = logging.getLogger(__name__)

router = APIRouter()


def process_message(user_message: str, reply_token: str, user_id: str | None) -> None:
    try:
        answer = ask_ai(user_message, user_id=user_id)
    except Exception as e:
        logger.error(f"Error processing user query in ask_ai: {e}")
        answer = (
            "ขออภัยครับ ระบบกำลังประสบปัญหาชั่วคราวในการประมวลผล "
            "กรุณาลองใหม่อีกครั้งในภายหลังครับ"
        )

    # Reply token may have expired on slow answers: fall back to push so the user always gets a reply
    if not reply_text(reply_token, answer):
        push_text(user_id, answer)

parser = WebhookParser(LINE_CHANNEL_SECRET)


@router.post("/webhook")
async def webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(...),
):
    body = await request.body()
    body_text = body.decode("utf-8")

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

    for event in events:
        if (
            isinstance(event, MessageEvent)
            and isinstance(event.message, TextMessageContent)
        ):
            user_message = event.message.text
            reply_token = event.reply_token
            user_id = getattr(event.source, "user_id", None)

            # Trigger native LINE Loading Animation (bouncing dots) immediately
            show_loading_animation(user_id, loading_seconds=20)

            # Process after responding 200 so LINE's webhook never times out on slow answers
            background_tasks.add_task(process_message, user_message, reply_token, user_id)

    return {
        "status": "OK"
    }