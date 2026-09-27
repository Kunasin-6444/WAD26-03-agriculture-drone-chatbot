import logging

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
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

    safe_text = text[:4950] if len(text) > 4950 else text

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