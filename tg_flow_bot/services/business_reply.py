"""Explicit Business replies with a durable, committed no-resend boundary.

No automatic retry is safe after a possibly accepted Telegram request. A reserved
attempt is therefore permanent until its outcome is known, including after a
worker crash. A fresh request ID means a separate, deliberately approved send.
"""

import hashlib
import json
import logging
from contextlib import asynccontextmanager
from uuid import UUID

from telegram import Bot, ReplyParameters
from telegram.error import BadRequest, Forbidden, RetryAfter
from tortoise.transactions import in_transaction

from config import settings
from models import BusinessConnection, BusinessReplyAttempt, ChatMessage
from services.business_access import owned_subscription
from services.chat_unread import visible_messages

logger = logging.getLogger(__name__)
TIMEOUTS = {"read_timeout": 10, "write_timeout": 10, "connect_timeout": 5, "pool_timeout": 5}
ERRORS = {
    "delivery_pending": "Delivery is pending or uncertain. Check Telegram before starting another attempt.",
    "delivery_unknown": "Delivery could not be confirmed. Check Telegram before starting another attempt.",
    "verification_unavailable": "Could not verify Telegram permissions. No message was sent.",
    "connection_changed": "The Business connection changed. Refresh the chat before sending again.",
    "connection_inactive": "Reconnect Telegram Business before sending a reply.",
    "reply_permission_missing": "Allow replies for this bot in Telegram's chat automation settings.",
    "capture_disabled": "Enable All messages for this private chat before replying.",
    "target_missing": "The selected message is no longer available. Refresh the chat.",
    "telegram_rejected": "Telegram rejected the reply. Check chat access and whether an incoming message was received in the last 24 hours.",
    "telegram_forbidden": "Telegram denied access. Check this chat and the bot's reply permissions.",
    "rate_limited": "Telegram rate-limited the reply. No automatic retry was made.",
}


class BusinessReplyError(ValueError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(detail)


def _result(attempt):
    reserved = attempt.status == "reserved"
    code = "delivery_pending" if reserved else attempt.error_code
    return {
        "status": "unknown" if reserved else attempt.status,
        "request_id": attempt.request_id,
        "message_id": attempt.telegram_message_id,
        "reply_attached": attempt.reply_attached,
        "error_code": code,
        "error": ERRORS.get(code),
    }


@asynccontextmanager
async def telegram_bot():
    # Combined process reuses its initialized bot. Standalone MCP uses the same
    # authenticated SDK, without starting another polling process.
    from main import get_bot

    try:
        app = get_bot()
    except RuntimeError:
        app = None
    if app is not None:
        yield app.bot
    else:
        async with Bot(settings.BOT_TOKEN) as bot:
            yield bot


async def _record_failure(attempt, status, code):
    attempt.status = status
    attempt.error_code = code
    try:
        await attempt.save(
            update_fields=(
                "status",
                "error_code",
                "telegram_message_id",
                "reply_attached",
                "updated_at",
            )
        )
    except Exception:
        # The committed reservation still forbids re-send. Never turn a database
        # outage after delivery into a fresh/retryable attempt.
        logger.warning("Business reply outcome could not be persisted")
    return _result(attempt)


async def get_business_reply_status(user_id, chat_id, request_id):
    """Read a stored outcome only: a missing attempt must never cause a send."""
    try:
        key = str(UUID(str(request_id)))
    except (ValueError, TypeError, AttributeError) as error:
        raise BusinessReplyError(422, "request_id must be a UUID") from error
    subscription = await owned_subscription(user_id, chat_id)
    if not subscription:
        raise BusinessReplyError(404, "Reply attempt not found")
    chat = await subscription.chat
    if chat.business_connection_id is None or chat.chat_type != "private":
        raise BusinessReplyError(404, "Reply attempt not found")
    attempt = await BusinessReplyAttempt.get_or_none(
        user_id=user_id, chat_id=chat_id, request_id=key
    )
    if attempt is None:
        raise BusinessReplyError(404, "Reply attempt not found")
    return _result(attempt)


async def send_business_reply(user_id, chat_id, message_id, text, request_id):
    try:
        key = str(UUID(str(request_id)))
    except (ValueError, TypeError, AttributeError) as error:
        raise BusinessReplyError(422, "request_id must be a UUID") from error
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4096:
        raise BusinessReplyError(422, "Reply text must contain 1-4096 characters")
    text = text.strip()
    if message_id <= 0:
        raise BusinessReplyError(422, "message_id must be positive")
    subscription = await owned_subscription(user_id, chat_id)
    if not subscription:
        raise BusinessReplyError(404, "Chat subscription not found")
    chat = await subscription.chat
    if (
        chat.business_connection_id is None
        or chat.chat_type != "private"
        or not chat.telegram_chat_id
    ):
        raise BusinessReplyError(403, "Replies require an owned Business private chat")
    payload_hash = hashlib.sha256(
        json.dumps([chat_id, message_id, text], ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    prior = await BusinessReplyAttempt.get_or_none(user_id=user_id, request_id=key)
    if prior:
        if prior.payload_hash != payload_hash or prior.chat_id != chat_id:
            raise BusinessReplyError(409, "request_id was already used for another reply")
        return _result(prior)
    connection = await BusinessConnection.get(id=chat.business_connection_id)
    if subscription.capture_mode != "full":
        raise BusinessReplyError(403, ERRORS["capture_disabled"])
    if not connection.is_enabled:
        raise BusinessReplyError(409, ERRORS["connection_inactive"])
    if not await (await visible_messages(subscription)).filter(message_id=message_id).exists():
        raise BusinessReplyError(404, ERRORS["target_missing"])

    # No enclosing transaction: get_or_create commits the reservation before
    # any Telegram request, so concurrent calls/crashes cannot re-send its key.
    attempt, created = await BusinessReplyAttempt.get_or_create(
        user_id=user_id,
        request_id=key,
        defaults={
            "chat": chat,
            "target_message_id": message_id,
            "payload_hash": payload_hash,
            "connection_id": connection.connection_id,
        },
    )
    if not created:
        if attempt.payload_hash != payload_hash or attempt.chat_id != chat_id:
            raise BusinessReplyError(409, "request_id was already used for another reply")
        return _result(attempt)

    send_started = False
    delivery_committed = False
    try:
        async with telegram_bot() as bot:
            async with in_transaction() as db:
                # Same lock as capture mode/lifecycle/ingestion. The committed
                # attempt remains visible while the bounded network calls run.
                current = (
                    await BusinessConnection.filter(id=connection.id)
                    .using_db(db)
                    .select_for_update()
                    .first()
                )
                latest = await owned_subscription(user_id, chat_id)
                if (
                    not current
                    or not latest
                    or current.user_id != user_id
                    or current.tg_user_id != latest.tg_user_id
                ):
                    raise BusinessReplyError(409, "connection_changed")
                if current.connection_id != attempt.connection_id:
                    raise BusinessReplyError(409, "connection_changed")
                if not current.is_enabled:
                    raise BusinessReplyError(409, "connection_inactive")
                if latest.capture_mode != "full":
                    raise BusinessReplyError(403, "capture_disabled")
                if (
                    not await (await visible_messages(latest))
                    .filter(message_id=message_id)
                    .exists()
                ):
                    raise BusinessReplyError(404, "target_missing")
                info = await bot.get_business_connection(current.connection_id, **TIMEOUTS)
                if (
                    info.id != current.connection_id
                    or info.user.id != current.tg_user_id
                    or info.user.is_bot
                ):
                    raise BusinessReplyError(409, "connection_changed")
                if not info.is_enabled:
                    raise BusinessReplyError(409, "connection_inactive")
                if not info.rights or not info.rights.can_reply:
                    raise BusinessReplyError(403, "reply_permission_missing")
                send_started = True
                sent = await bot.send_message(
                    chat_id=chat.telegram_chat_id,
                    business_connection_id=current.connection_id,
                    text=text,
                    reply_parameters=ReplyParameters(message_id=message_id),
                    **TIMEOUTS,
                )
                if sent.message_id <= 0:
                    raise ValueError("Telegram returned an unusable message identifier")
                attempt.status = "sent"
                attempt.telegram_message_id = sent.message_id
                attempt.reply_attached = bool(
                    sent.reply_to_message and sent.reply_to_message.message_id == message_id
                )
                attempt.error_code = None
                await ChatMessage.get_or_create(
                    chat=chat,
                    message_id=sent.message_id,
                    defaults={
                        "from_user_id": current.tg_user_id,
                        "from_username": info.user.username,
                        "text": sent.text or text,
                        "message_date": sent.date,
                    },
                    using_db=db,
                )
                await attempt.save(using_db=db)
            delivery_committed = True
        return _result(attempt)
    except BusinessReplyError as error:
        return await _record_failure(attempt, "failed", str(error))
    except RetryAfter:
        return await _record_failure(
            attempt, "failed", "rate_limited" if send_started else "verification_unavailable"
        )
    except (BadRequest, Forbidden) as error:
        code = (
            ("telegram_forbidden" if isinstance(error, Forbidden) else "telegram_rejected")
            if send_started
            else "verification_unavailable"
        )
        return await _record_failure(attempt, "failed", code)
    except Exception:
        if delivery_committed:
            return _result(attempt)
        # Do not log the SDK exception: it may contain message text or a token
        # URL. A request may already have been accepted even on network error.
        return await _record_failure(
            attempt,
            "unknown" if send_started else "failed",
            "delivery_unknown" if send_started else "verification_unavailable",
        )
