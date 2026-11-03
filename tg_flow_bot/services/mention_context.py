"""Shared context reads respect a subscriber's persistent capture opt-out."""

from models import ChatMessage, MentionedMessage, UserChatSubscription


async def mention_context_messages(mention: MentionedMessage, before: int, after: int):
    query = ChatMessage.filter(chat_id=mention.chat_id)
    subscription = await UserChatSubscription.get_or_none(
        user_id=mention.user_id,
        chat_id=mention.chat_id,
    )
    if subscription and subscription.capture_mode == "disabled":
        query = query.filter(saved_at__lte=subscription.capture_mode_changed_at)
    previous = (
        await query.filter(message_id__lt=mention.message_id).order_by("-message_id").limit(before)
    )
    following = (
        await query.filter(message_id__gt=mention.message_id).order_by("message_id").limit(after)
    )
    return list(reversed(previous)), following
