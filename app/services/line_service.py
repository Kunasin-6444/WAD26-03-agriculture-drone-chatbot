import logging

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)

from app.config import LINE_CHANNEL_ACCESS_TOKEN

logger = logging.getLogger(__name__)

configuration = Configuration(
    access_token=LINE_CHANNEL_ACCESS_TOKEN
)

DUMMY_REPLY_TOKENS = {
    "00000000000000000000000000000000",
    "ffffffffffffffffffffffffffffffff",
}


def reply_text(reply_token: str, text: str) -> bool:
    """
    Send a text reply via LINE Messaging API.
    Guards against dummy verification tokens and ensures safe message length.
    """
    if not reply_token or reply_token in DUMMY_REPLY_TOKENS:
        logger.info("Ignoring dummy/test reply token from LINE verification.")
        return True

    # Never silently remove a citation at the end of a long answer.
    safe_text = text if len(text) <= 4950 else "คำตอบยาวเกินขอบเขต กรุณาระบุประเด็นให้เฉพาะเจาะจงขึ้นครับ"

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[
                        TextMessage(text=safe_text)
                    ],
                )
            )
            return True
    except Exception as e:
        logger.error(f"Failed to send LINE reply: {e}")
        return False


def push_text(user_id: str | None, text: str) -> bool:
    """
    Fallback delivery via the Push API for when the reply token has expired or
    failed (e.g. a slow answer). Consumes push quota, so use only as a backup
    to reply_text, never as the primary send path.
    """
    if not user_id or user_id.startswith("test_") or user_id in DUMMY_REPLY_TOKENS:
        return False

    safe_text = text if len(text) <= 4950 else "คำตอบยาวเกินขอบเขต กรุณาระบุประเด็นให้เฉพาะเจาะจงขึ้นครับ"

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=safe_text)],
                )
            )
            return True
    except Exception as e:
        logger.error(f"Failed to push LINE message: {e}")
        return False


def show_loading_animation(chat_id: str | None, loading_seconds: int = 20) -> bool:
    """
    Display LINE's official native loading animation (bouncing dots) in the user's chat.
    Valid loading_seconds is between 5 and 60 seconds (default 20s).
    Automatically dismissed by LINE as soon as reply_message is sent.
    Free, does not consume push quota or replyToken.
    """
    if not chat_id:
        return False

    # Ignore dummy / mock user IDs from verification requests
    if chat_id.startswith("test_") or chat_id in DUMMY_REPLY_TOKENS:
        return True

    safe_seconds = min(max(loading_seconds, 5), 60)

    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            req = ShowLoadingAnimationRequest(
                chat_id=chat_id,
                loading_seconds=safe_seconds,
            )
            line_bot_api.show_loading_animation(req)
            return True
    except Exception as e:
        logger.debug(f"Could not show loading animation for {chat_id}: {e}")
        return False
