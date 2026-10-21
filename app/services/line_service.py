import logging
import json
from dataclasses import dataclass

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    FlexContainer,
    FlexMessage,
    ShowLoadingAnimationRequest,
    TextMessage,
)

from app.config import LINE_CHANNEL_ACCESS_TOKEN
from app.services.rich_menu_service import MENU_ANSWER, menu_as_text, menu_card

logger = logging.getLogger(__name__)

configuration = Configuration(
    access_token=LINE_CHANNEL_ACCESS_TOKEN
)

DUMMY_REPLY_TOKENS = {
    "00000000000000000000000000000000",
    "ffffffffffffffffffffffffffffffff",
}


# (connect, read) seconds. A hung send must not pin a worker forever; a read timeout is
# reported as UNKNOWN because LINE may still have accepted the message.
SEND_TIMEOUT = (3.05, 10.0)

# Outcomes of one send attempt. They decide what the delivery worker may do next:
#   DELIVERED     - LINE accepted the message.
#   TOKEN_INVALID - LINE said the reply token is invalid/expired (definitely not sent
#                   by this call), so a push fallback is safe.
#   RETRYABLE     - definitely not delivered, may succeed later (429, connection never made).
#   PERMANENT     - definitely not delivered and retrying cannot help (auth, bad request).
#   UNKNOWN       - the request may have reached LINE (timeout, reset, 5xx). Never push
#                   or re-send a reply after this: it could duplicate a delivered answer.
DELIVERED = "delivered"
TOKEN_INVALID = "token_invalid"
RETRYABLE = "retryable"
PERMANENT = "permanent"
UNKNOWN = "unknown"

_NEVER_SENT_ERRORS = ("NewConnectionError", "ConnectTimeoutError", "NameResolutionError")


@dataclass(frozen=True)
class SendResult:
    outcome: str
    detail: str = ""

    @property
    def delivered(self) -> bool:
        return self.outcome == DELIVERED


def _safe_text(text: str) -> str:
    # Never silently remove a citation at the end of a long answer.
    return text if len(text) <= 4950 else "คำตอบยาวเกินขอบเขต กรุณาระบุประเด็นให้เฉพาะเจาะจงขึ้นครับ"


def _messages(text: str) -> list:
    """The stored answer as LINE messages: the menu answer becomes the Flex card (shown on LINE PC too)."""
    if text == MENU_ANSWER:
        return [FlexMessage(alt_text=menu_as_text()[:400], contents=FlexContainer.from_dict(menu_card()))]
    return [TextMessage(text=_safe_text(text))]


def _never_reached_line(exc: BaseException) -> bool:
    """True only when the exception chain proves the TCP connection was never made."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        if not isinstance(current, BaseException):
            continue
        seen.add(id(current))
        if type(current).__name__ in _NEVER_SENT_ERRORS:
            return True
        stack.extend([getattr(current, "reason", None), current.__cause__, current.__context__])
    return False


def classify_send_error(exc: BaseException, *, retry_key_used: bool = False) -> SendResult:
    """Map a Messaging API exception to a SendResult without guessing in favour of a resend."""
    status = getattr(exc, "status", None)
    if status is not None:
        body = getattr(exc, "body", None)
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body or "")
        try:
            message = json.loads(text).get("message", "").strip().lower()
        except (ValueError, AttributeError):
            message = ""
        if status == 400 and message == "invalid reply token":
            return SendResult(TOKEN_INVALID, "http_400_invalid_reply_token")
        if status == 409 and retry_key_used:
            # Push with a retry key LINE has already accepted: the message was delivered.
            return SendResult(DELIVERED, "http_409_retry_key_already_accepted")
        if status == 429:
            return SendResult(RETRYABLE, "http_429")
        if 400 <= status < 500 and status != 408:
            return SendResult(PERMANENT, f"http_{status}")
        return SendResult(UNKNOWN, f"http_{status}")
    if _never_reached_line(exc):
        return SendResult(RETRYABLE, type(exc).__name__)
    return SendResult(UNKNOWN, type(exc).__name__)


def send_reply(reply_token: str, text: str) -> SendResult:
    """Send one reply with the single-use reply token and classify the result."""
    if not reply_token or reply_token in DUMMY_REPLY_TOKENS:
        logger.info("Ignoring dummy/test reply token from LINE verification.")
        return SendResult(DELIVERED, "dummy_token_ignored")
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(reply_token=reply_token, messages=_messages(text)),
                _request_timeout=SEND_TIMEOUT,
            )
        return SendResult(DELIVERED)
    except Exception as e:
        result = classify_send_error(e)
        logger.error("Failed to send LINE reply (%s): %s", result.outcome, e)
        return result


def send_push(user_id: str | None, text: str, retry_key: str | None = None) -> SendResult:
    """
    Push fallback. `retry_key` (a UUID) makes LINE de-duplicate repeated pushes for 24h,
    which is what lets the worker safely retry a push after an unknown outcome.
    """
    if not user_id or user_id.startswith("test_") or user_id in DUMMY_REPLY_TOKENS:
        return SendResult(PERMANENT, "no_push_target")
    try:
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).push_message(
                PushMessageRequest(to=user_id, messages=_messages(text)),
                x_line_retry_key=retry_key,
                _request_timeout=SEND_TIMEOUT,
            )
        return SendResult(DELIVERED)
    except Exception as e:
        result = classify_send_error(e, retry_key_used=bool(retry_key))
        logger.error("Failed to push LINE message (%s): %s", result.outcome, type(e).__name__)
        return result


def reply_text(reply_token: str, text: str) -> bool:
    """
    Send a text reply via LINE Messaging API.
    Guards against dummy verification tokens and ensures safe message length.
    """
    return send_reply(reply_token, text).delivered


def push_text(user_id: str | None, text: str) -> bool:
    """
    Fallback delivery via the Push API for when the reply token has expired or
    failed (e.g. a slow answer). Consumes push quota, so use only as a backup
    to reply_text, never as the primary send path.
    """
    return send_push(user_id, text).delivered


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
            line_bot_api.show_loading_animation(req, _request_timeout=(2.0, 2.0))
            return True
    except Exception as e:
        logger.debug(f"Could not show loading animation for {chat_id}: {e}")
        return False
