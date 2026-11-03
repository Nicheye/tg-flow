"""Read-only Telegram Business ingestion; never send or acknowledge on Telegram."""

import logging
from datetime import UTC, datetime

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from tortoise.transactions import in_transaction

from models import BusinessConnection, Chat, ChatMessage, UserChatSubscription
from schemas import TelegramUser
from services import auth_client

logger = logging.getLogger(__name__)


def _stale(connection, update_id):
    # A single account's idle time proves nothing about the bot-wide Telegram
    # update stream. Never expire replay protection based on local timestamps.
    return update_id <= connection.last_update_id


async def _verified_new_connection(event, context):
    if context is None:
        return False
    try:
        current = await context.bot.get_business_connection(
            event.id,
            read_timeout=5,
            write_timeout=5,
            connect_timeout=5,
            pool_timeout=5,
        )
    except TelegramError:
        logger.warning("Business connection reset verification failed")
        return False
    return (
        current.id == event.id
        and current.user.id == event.user.id
        and not current.user.is_bot
        and current.is_enabled == event.is_enabled
    )


async def _observe(connection, update_id, db):
    connection.last_update_id = update_id
    await connection.save(using_db=db)


async def business_connection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event = update.business_connection
    if not event or event.user.is_bot:
        return
    owner = event.user
    # Resolve only the account owner from Telegram's connection event. Message
    # senders must never be used to assign ownership of private conversations.
    connection = await BusinessConnection.get_or_none(tg_user_id=owner.id)
    auth = None
    if connection is None:
        auth = await auth_client.register(
            TelegramUser(
                tg_user_id=owner.id,
                tg_username=owner.username,
                first_name=owner.first_name,
                last_name=owner.last_name,
            )
        )
        if auth is None:
            logger.warning("Business connection owner registration failed")
            return
    async with in_transaction() as db:
        connection = (
            await BusinessConnection.filter(tg_user_id=owner.id)
            .using_db(db)
            .select_for_update()
            .first()
        )
        if connection:
            if event.id in connection.retired_connection_ids:
                return
            if _stale(connection, update.update_id):
                # A true bot-wide Telegram update-ID reset requires an explicit
                # new connection identity verified with Telegram. Resetting the
                # watermark for the same ID would admit old messages/deletions.
                if event.id == connection.connection_id or not await _verified_new_connection(
                    event, context
                ):
                    return
            if event.id != connection.connection_id:
                connection.retired_connection_ids = [
                    *connection.retired_connection_ids,
                    connection.connection_id,
                ]
            connection.connection_id = event.id
            connection.is_enabled = event.is_enabled
            connection.last_update_id = update.update_id
            await connection.save(using_db=db)
        else:
            await BusinessConnection.create(
                tg_user_id=owner.id,
                user_id=auth.user_id,
                connection_id=event.id,
                is_enabled=event.is_enabled,
                last_update_id=update.update_id,
                connected_at=event.date,
                using_db=db,
            )


async def business_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.business_message or update.edited_business_message
    if not message or message.chat.type != "private" or message.message_id <= 0:
        return
    connection_id = message.business_connection_id
    if not connection_id:
        return
    async with in_transaction() as db:
        connection = (
            await BusinessConnection.filter(connection_id=connection_id)
            .using_db(db)
            .select_for_update()
            .first()
        )
        if not connection or _stale(connection, update.update_id):
            return
        await _observe(connection, update.update_id, db)
        if not connection.is_enabled:
            return
        chat = (
            await Chat.filter(
                business_connection_id=connection.id, telegram_chat_id=message.chat.id
            )
            .using_db(db)
            .first()
        )
        # Edits cannot bootstrap a private archive, or restore a deleted row.
        is_edit = update.edited_business_message is not None
        if chat is None:
            if is_edit:
                return
            chat = await Chat.create(
                chat_type="private",
                title=message.chat.full_name or message.chat.username,
                username=message.chat.username,
                business_connection=connection,
                telegram_chat_id=message.chat.id,
                using_db=db,
            )
        subscription, _ = await UserChatSubscription.get_or_create(
            user_id=connection.user_id,
            chat=chat,
            using_db=db,
            defaults={"tg_user_id": connection.tg_user_id, "capture_mode": "full"},
        )
        if subscription.tg_user_id != connection.tg_user_id or subscription.capture_mode != "full":
            return
        sender = message.from_user
        if not sender:
            return
        existing = (
            await ChatMessage.filter(chat=chat, message_id=message.message_id).using_db(db).first()
        )
        if is_edit and existing is None:
            return
        values = {
            "from_user_id": sender.id,
            "from_username": sender.username,
            "text": message.text or message.caption,
            "message_date": message.date,
        }
        if existing:
            if any(getattr(existing, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.saved_at = datetime.now(UTC)
                await existing.save(using_db=db)
        else:
            await ChatMessage.create(
                chat=chat, message_id=message.message_id, **values, using_db=db
            )


async def business_messages_deleted_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    event = update.deleted_business_messages
    if not event or event.chat.type != "private":
        return
    async with in_transaction() as db:
        connection = (
            await BusinessConnection.filter(connection_id=event.business_connection_id)
            .using_db(db)
            .select_for_update()
            .first()
        )
        if connection is None or _stale(connection, update.update_id):
            return
        await _observe(connection, update.update_id, db)
        # Deletions also apply to retained history when capture is disabled.
        chat = (
            await Chat.filter(business_connection_id=connection.id, telegram_chat_id=event.chat.id)
            .using_db(db)
            .first()
        )
        if chat:
            await (
                ChatMessage.filter(chat=chat, message_id__in=event.message_ids)
                .using_db(db)
                .delete()
            )
