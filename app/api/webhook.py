from fastapi import APIRouter, Header, Request
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.config import LINE_CHANNEL_SECRET
from app.services.ai_service import ask_ai
from app.services.line_service import reply_text


router = APIRouter()

parser = WebhookParser(LINE_CHANNEL_SECRET)


@router.post("/webhook")
async def webhook(
    request: Request,
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
        return {
            "message": "Invalid signature"
        }

    for event in events:
        if (
            isinstance(event, MessageEvent)
            and isinstance(event.message, TextMessageContent)
        ):
            user_message = event.message.text

            answer = ask_ai(user_message)

            reply_text(
                event.reply_token,
                answer,
            )

    return {
        "message": "OK"
    }