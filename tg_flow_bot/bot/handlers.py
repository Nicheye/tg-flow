import logging
from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

from models import Chat, UserChatSubscription
from schemas import TelegramUser
from services import auth_client

logger = logging.getLogger(__name__)

CAPTURE_MODE_MENTIONS = "mentions"
CAPTURE_MODE_FULL = "full"


def _requested_capture_mode(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    args = getattr(context, "args", None)
    if not isinstance(args, (list, tuple)) or not args:
        return CAPTURE_MODE_MENTIONS
    value = str(args[0]).lower()
    if value in {"mentions", "mention", "tags", "tags_only"}:
        return CAPTURE_MODE_MENTIONS
    if value in {"all", "full", "everything"}:
        return CAPTURE_MODE_FULL
    return None


def _mode_title(mode: str) -> str:
    return "all messages" if mode == CAPTURE_MODE_FULL else "mentions and context"


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command. Registers user in the auth service."""
    user = update.effective_user
    if not user:
        return

    logger.info(f"User {user.id} (@{user.username}) started bot")

    tg_user = TelegramUser(
        tg_user_id=user.id,
        tg_username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

    auth_response = await auth_client.register(tg_user)

    if auth_response:
        context.user_data["user_id"] = auth_response.user_id
        context.user_data["access_token"] = auth_response.access

        if auth_response.created:
            logger.info(f"User {user.id} registered successfully")
            await update.message.reply_text(
                f"👋 Hello, {user.first_name}!\n\n"
                "✅ You have successfully registered.\n\n"
                "Add me to a chat and choose a mode with /subscribe.\n\n"
                "Commands:\n"
                "/subscribe mentions — mentions and context\n"
                "/subscribe all — save the full chat feed\n"
                "/mode — view or change the mode\n"
                "/unsubscribe — unsubscribe from a chat\n"
                "/my_mentions — list mentions\n"
                "/help — help"
            )
        else:
            logger.info(f"User {user.id} already registered, logged in")
            await update.message.reply_text(
                f"👋 Welcome back, {user.first_name}!\n\n"
                "✅ You are already registered.\n\n"
                "Use /help to see the available commands."
            )
    else:
        logger.error(f"Failed to register user {user.id}")
        await update.message.reply_text("❌ Registration failed. Please try again later.")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    await update.message.reply_text(
        "🤖 <b>TG Flow Bot</b>\n\n"
        "Choose between mentions with context and a full chat feed.\n\n"
        "<b>How to use:</b>\n"
        "1. Add me to a chat\n"
        "2. Send /subscribe mentions or /subscribe all in the chat\n"
        "3. Change the mode later with /mode\n\n"
        "<b>Commands:</b>\n"
        "/start — register\n"
        "/subscribe mentions — mentions and context (default)\n"
        "/subscribe all — full chat feed\n"
        "/mode [mentions|all] — view or change the mode\n"
        "/unsubscribe — unsubscribe from a chat\n"
        "/my_mentions — list mentions\n"
        "/help — show this help",
        parse_mode="HTML",
    )


async def subscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /subscribe command - subscribe to mentions in current chat"""
    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type == "private":
        await update.message.reply_text(
            "❌ This command only works in group chats.\n"
            "Add me to a chat and send /subscribe there."
        )
        return

    capture_mode = _requested_capture_mode(context)
    if capture_mode is None:
        await update.message.reply_text(
            "❌ Unknown mode. Use /subscribe mentions or /subscribe all."
        )
        return

    user_id = context.user_data.get("user_id")
    if not user_id:
        logger.warning(f"User {user.id} tried to subscribe without registration")
        await update.message.reply_text(
            "❌ Please register first: send me /start in a private message."
        )
        return

    # Get full chat info (including photo) from Telegram API
    full_chat = await context.bot.get_chat(chat.id)
    photo_file_id = None
    if full_chat.photo:
        photo_file_id = full_chat.photo.small_file_id

    db_chat, chat_created = await Chat.get_or_create(
        id=chat.id,
        defaults={
            "chat_type": chat.type,
            "title": full_chat.title,
            "username": full_chat.username,
            "photo_file_id": photo_file_id,
        },
    )

    if not chat_created:
        db_chat.title = full_chat.title
        db_chat.username = full_chat.username
        db_chat.photo_file_id = photo_file_id
        await db_chat.save()

    if chat_created:
        logger.info(f"Chat {chat.id} ({chat.title}) added to database")

    subscription, created = await UserChatSubscription.get_or_create(
        user_id=user_id,
        chat=db_chat,
        defaults={
            "tg_user_id": user.id,
            "tg_username": user.username,
            "capture_mode": capture_mode,
        },
    )

    if created:
        logger.info(f"User {user.id} subscribed to chat {chat.id}")
        status = (
            "you are subscribed to mentions in this chat"
            if capture_mode == CAPTURE_MODE_MENTIONS
            else "you are subscribed to the full chat feed"
        )
        await update.message.reply_text(
            f"✅ {user.first_name}, {status}!\n"
            f"Mode: {_mode_title(capture_mode)}."
        )
    else:
        changed = subscription.capture_mode != capture_mode
        if changed:
            subscription.capture_mode_changed_at = datetime.now(UTC)
        subscription.capture_mode = capture_mode
        subscription.tg_user_id = user.id
        subscription.tg_username = user.username
        await subscription.save()
        logger.info(f"User {user.id} set {capture_mode} mode for chat {chat.id}")
        prefix = "✅ Mode changed" if changed else "ℹ️ You are already subscribed with this mode"
        await update.message.reply_text(f"{prefix}: {_mode_title(capture_mode)}.")


async def mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or change the capture mode for the current chat."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or chat.type == "private":
        await update.message.reply_text("❌ This command only works in group chats.")
        return

    user_id = context.user_data.get("user_id")
    if not user_id:
        await update.message.reply_text(
            "❌ Please register first: send me /start in a private message."
        )
        return

    subscription = await UserChatSubscription.get_or_none(user_id=user_id, chat_id=chat.id)
    if not subscription:
        await update.message.reply_text(
            "ℹ️ Please subscribe first: /subscribe mentions or /subscribe all."
        )
        return

    args = getattr(context, "args", None)
    if not isinstance(args, (list, tuple)) or not args:
        await update.message.reply_text(
            f"Current mode: {_mode_title(subscription.capture_mode)}.\n"
            "Change it with /mode mentions or /mode all."
        )
        return

    capture_mode = _requested_capture_mode(context)
    if capture_mode is None:
        await update.message.reply_text("❌ Use /mode mentions or /mode all.")
        return

    if subscription.capture_mode != capture_mode:
        subscription.capture_mode = capture_mode
        subscription.capture_mode_changed_at = datetime.now(UTC)
        await subscription.save(update_fields=("capture_mode", "capture_mode_changed_at"))
    await update.message.reply_text(f"✅ Mode changed: {_mode_title(capture_mode)}.")


async def unsubscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unsubscribe command"""
    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type == "private":
        await update.message.reply_text("❌ This command only works in group chats.")
        return

    user_id = context.user_data.get("user_id")
    if not user_id:
        logger.warning(f"User {user.id} tried to unsubscribe without registration")
        await update.message.reply_text(
            "❌ Please register first: send me /start in a private message."
        )
        return

    deleted = await UserChatSubscription.filter(user_id=user_id, chat_id=chat.id).delete()

    if deleted:
        logger.info(f"User {user.id} unsubscribed from chat {chat.id}")
        await update.message.reply_text(
            f"✅ {user.first_name}, you have unsubscribed from this chat."
        )
    else:
        logger.debug(f"User {user.id} was not subscribed to chat {chat.id}")
        await update.message.reply_text(f"ℹ️ {user.first_name}, you were not subscribed to this chat.")


async def my_mentions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /my_mentions command - show saved mentions"""
    user = update.effective_user

    if not user:
        return

    logger.debug(f"User {user.id} requested mentions")

    # TODO: Fetch mentions from database
    await update.message.reply_text(
        "📋 <b>Your mentions:</b>\n\n"
        "<i>No saved mentions yet.</i>\n\n"
        "Subscribe to a chat with /subscribe",
        parse_mode="HTML",
    )
