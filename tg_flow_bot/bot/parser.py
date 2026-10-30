import logging

from telegram import Update
from telegram.ext import ContextTypes

from models import Chat, ChatMessage, MentionedMessage, UserChatSubscription

logger = logging.getLogger(__name__)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process all messages to detect mentions"""
    message = update.effective_message
    if not message:
        return

    chat = update.effective_chat
    if chat.type == "private":
        return

    text = message.text or message.caption
    entities = message.entities or message.caption_entities
    sender = message.from_user or message.sender_chat
    if not sender:
        logger.warning("Message %s in chat %s has no sender", message.message_id, chat.id)
        return
    sender_username = getattr(sender, "username", None) or getattr(sender, "title", None)

    db_chat, chat_created = await Chat.get_or_create(
        id=chat.id,
        defaults={
            "chat_type": chat.type,
            "title": chat.title,
            "username": chat.username,
        },
    )

    if not chat_created:
        db_chat.chat_type = chat.type
        db_chat.title = chat.title
        db_chat.username = chat.username
        await db_chat.save()

    # Mention mode needs the stream for surrounding context; full mode exposes
    # that same stream as a complete, paginated conversation.
    subscriptions = await UserChatSubscription.filter(chat_id=chat.id)

    chat_message, created = await ChatMessage.get_or_create(
        chat=db_chat,
        message_id=message.message_id,
        defaults={
            "from_user_id": sender.id,
            "from_username": sender_username,
            "text": text,
            "message_date": message.date,
        },
    )
    if not created:
        chat_message.from_user_id = sender.id
        chat_message.from_username = sender_username
        chat_message.text = text
        chat_message.message_date = message.date
        await chat_message.save()

    if not entities:
        await MentionedMessage.filter(chat_message=chat_message).delete()
        return

    mentioned_targets: list[tuple[str, str | int]] = []
    for entity in entities:
        if entity.type == "mention":  # @username
            if not text:
                continue
            username = text[entity.offset : entity.offset + entity.length]
            mentioned_targets.append(("username", username.lstrip("@")))
        elif entity.type == "text_mention":  # mention without a username
            mentioned_targets.append(("user_id", entity.user.id))

    if not mentioned_targets:
        await MentionedMessage.filter(chat_message=chat_message).delete()
        return

    logger.debug("Found mentions: %s in chat %s", mentioned_targets, chat.id)

    matched_subscriptions = {
        item.id: item
        for item in subscriptions
        if any(
            (kind == "user_id" and item.tg_user_id == value)
            or (
                kind == "username"
                and item.tg_username
                and item.tg_username.casefold() == str(value).casefold()
            )
            for kind, value in mentioned_targets
        )
    }

    existing_mentions = await MentionedMessage.filter(chat_message=chat_message)
    retained_subscription_ids: set[int] = set()
    for existing in existing_mentions:
        if (
            existing.subscription_id not in matched_subscriptions
            or existing.subscription_id in retained_subscription_ids
        ):
            await existing.delete()
        else:
            retained_subscription_ids.add(existing.subscription_id)

    for subscription in matched_subscriptions.values():
        existing = next(
            (
                mention
                for mention in existing_mentions
                if mention.subscription_id == subscription.id
            ),
            None,
        )
        if existing:
            existing.from_user_id = sender.id
            existing.from_username = sender_username
            existing.text = text or ""
            existing.message_date = message.date
            existing.chat_message = chat_message
            await existing.save()
        else:
            await MentionedMessage.create(
                user_id=subscription.user_id,
                chat_id=chat.id,
                subscription_id=subscription.id,
                chat_message=chat_message,
                message_id=message.message_id,
                from_user_id=sender.id,
                from_username=sender_username,
                text=text or "",
                message_date=message.date,
            )
            logger.info("Saved mention for subscription %s in chat %s", subscription.id, chat.id)
