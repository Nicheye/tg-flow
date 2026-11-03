"""Durable per-owner unread snapshots, separate from Telegram read receipts."""

from datetime import UTC, datetime

from models import ChatMessage, UserChatSubscription
from services.business_access import owned_subscription, owns_subscription


class ChatUnreadError(ValueError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        super().__init__(detail)


async def owned_full_subscription(user_id: int, chat_id: int, generation: datetime | None = None):
    subscription = await owned_subscription(user_id, chat_id)
    if not subscription:
        raise ChatUnreadError(404, "Chat subscription not found")
    if subscription.capture_mode != "full":
        raise ChatUnreadError(403, "Full-chat mode is not enabled for this chat")
    if generation is not None and generation != subscription.capture_mode_changed_at:
        raise ChatUnreadError(409, "Capture mode changed; refresh the unread snapshot")
    return subscription


async def visible_messages(subscription):
    chat = await subscription.chat
    # Private rows have a sole owner and are never captured for anyone else
    # during an opt-out. Resuming capture therefore retains the owner's archive;
    # group rows remain bounded to the current mode interval as before.
    boundary = (subscription.subscribed_at if chat.business_connection_id is not None
                else subscription.capture_mode_changed_at)
    return ChatMessage.filter(
        chat_id=subscription.chat_id,
        saved_at__gte=boundary,
    )


async def unread_count(subscription) -> int:
    if subscription.capture_mode != "full" or not await owns_subscription(subscription, subscription.user_id):
        return 0
    return (
        await (await visible_messages(subscription))
        .filter(
            message_id__gt=subscription.read_through_message_id,
        )
        .count()
    )


async def list_unread(
    user_id: int,
    chat_id: int,
    limit: int = 100,
    after_message_id: int | None = None,
    through_message_id: int | None = None,
    capture_mode_changed_at: datetime | None = None,
):
    if not 1 <= limit <= 200:
        raise ChatUnreadError(422, "limit must be between 1 and 200")
    continuation = after_message_id is not None or through_message_id is not None
    if continuation and (capture_mode_changed_at is None or through_message_id is None):
        raise ChatUnreadError(
            422, "Continuation requires through_message_id and capture_mode_changed_at"
        )
    if (after_message_id is not None and after_message_id < 0) or (
        through_message_id is not None and through_message_id < 0
    ):
        raise ChatUnreadError(422, "Message boundaries must be nonnegative")
    subscription = await owned_full_subscription(user_id, chat_id, capture_mode_changed_at)
    eligible = await visible_messages(subscription)
    if through_message_id is None:
        latest = await eligible.order_by("-message_id").first()
        snapshot = latest.message_id if latest else 0
    else:
        snapshot = through_message_id
        if snapshot and not await eligible.filter(message_id=snapshot).exists():
            raise ChatUnreadError(422, "Snapshot boundary is not visible in this chat")
    if after_message_id is not None and after_message_id > snapshot:
        raise ChatUnreadError(422, "after_message_id must not exceed snapshot boundary")
    cursor = max(subscription.read_through_message_id, after_message_id or 0)
    rows = (
        await eligible.filter(message_id__gt=cursor, message_id__lte=snapshot)
        .order_by("message_id")
        .limit(limit + 1)
    )
    has_more = len(rows) > limit
    messages = rows[:limit]
    return {
        "messages": messages,
        "read_through_message_id": subscription.read_through_message_id,
        "snapshot_through_message_id": snapshot,
        "capture_mode_changed_at": subscription.capture_mode_changed_at,
        "next_after_message_id": messages[-1].message_id if has_more else None,
        "has_more": has_more,
        "unread_count": await unread_count(subscription),
    }


async def mark_read(
    user_id: int, chat_id: int, through_message_id: int, capture_mode_changed_at: datetime
):
    if through_message_id < 1:
        raise ChatUnreadError(422, "through_message_id must be a positive captured message ID")
    subscription = await owned_full_subscription(user_id, chat_id, capture_mode_changed_at)
    if not await (await visible_messages(subscription)).filter(message_id=through_message_id).exists():
        raise ChatUnreadError(422, "Read boundary is not visible in this chat")
    # One conditional SQL UPDATE is both monotonic and bound to the generation.
    # A concurrent mode change cannot acknowledge a snapshot from its prior mode.
    await UserChatSubscription.filter(
        id=subscription.id,
        user_id=user_id,
        capture_mode="full",
        capture_mode_changed_at=capture_mode_changed_at,
        read_through_message_id__lt=through_message_id,
    ).update(read_through_message_id=through_message_id, last_read_at=datetime.now(UTC))
    return await owned_full_subscription(user_id, chat_id, capture_mode_changed_at)
