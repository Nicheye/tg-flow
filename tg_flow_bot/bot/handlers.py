import logging
from datetime import UTC, datetime

from telegram import ChatMember, Update
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
    return {
        "full": "все сообщения",
        "mentions": "упоминания и контекст",
        "disabled": "сохранение выключено",
    }[mode]


async def _resolve_user(user):
    """Resolve the durable auth identity; never trust a cached process-local ID."""
    if not user or user.is_bot or user.id in {1087968824, 136817688}:
        return None
    return await auth_client.register(
        TelegramUser(
            tg_user_id=user.id,
            tg_username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )
    )


async def bot_membership_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Subscribe only the human who actually added this bot to a group."""
    event = update.my_chat_member
    if not event or event.chat.type not in {"group", "supergroup"}:
        return

    def present(member):
        return member.status in {ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER} or (
            member.status == ChatMember.RESTRICTED and member.is_member
        )

    if present(event.old_chat_member) or not present(event.new_chat_member):
        return
    actor = event.from_user
    auth = await _resolve_user(actor)
    if not auth:
        return
    chat, _ = await Chat.get_or_create(
        id=event.chat.id,
        defaults={
            "chat_type": event.chat.type,
            "title": event.chat.title,
            "username": event.chat.username,
        },
    )
    # Replayed events and re-adds must never override an existing user's choice.
    await UserChatSubscription.get_or_create(
        user_id=auth.user_id,
        chat=chat,
        defaults={
            "tg_user_id": actor.id,
            "tg_username": actor.username,
            "capture_mode": "full",
        },
    )


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
                f"👋 Привет, {user.first_name}!\n\n"
                f"✅ Ты успешно зарегистрирован.\n\n"
                f"Добавь меня в группу — все новые сообщения сохранятся автоматически для тебя. Режим и выключение доступны на сайте.\n\n"
                f"Команды:\n"
                f"/subscribe mentions — упоминания и контекст\n"
                f"/subscribe all — сохранять весь чат\n"
                f"/mode — посмотреть или сменить режим\n"
                f"/unsubscribe — отписаться от чата\n"
                f"/my_mentions — список упоминаний\n"
                f"/help — справка"
            )
        else:
            logger.info(f"User {user.id} already registered, logged in")
            await update.message.reply_text(
                f"👋 С возвращением, {user.first_name}!\n\n"
                f"✅ Ты уже зарегистрирован.\n\n"
                f"Используй /help для списка команд."
            )
    else:
        logger.error(f"Failed to register user {user.id}")
        await update.message.reply_text("❌ Ошибка регистрации. Попробуй позже.")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    await update.message.reply_text(
        "🤖 <b>TG Flow Bot</b>\n\n"
        "Я умею работать в двух режимах: упоминания с контекстом или полная лента чата.\n\n"
        "<b>Как использовать:</b>\n"
        "1. Добавь меня в чат\n"
        "2. Все новые сообщения автоматически сохраняются для добавившего меня пользователя\n"
        "3. Сменить режим или выключить сохранение можно на сайте; /subscribe — необязательное восстановление\n\n"
        "<b>Команды:</b>\n"
        "/start — регистрация\n"
        "/subscribe mentions — упоминания и контекст (по умолчанию)\n"
        "/subscribe all — полная лента чата\n"
        "/mode [mentions|all] — посмотреть или сменить режим\n"
        "/unsubscribe — отписаться от чата\n"
        "/my_mentions — список упоминаний\n"
        "/help — эта справка",
        parse_mode="HTML",
    )


async def subscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /subscribe command - subscribe to mentions in current chat"""
    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type not in {"group", "supergroup"}:
        await update.message.reply_text(
            "❌ Эта команда работает только в групповых чатах.\n"
            "Добавь меня в чат и напиши /subscribe там."
        )
        return

    capture_mode = _requested_capture_mode(context)
    if capture_mode is None:
        await update.message.reply_text(
            "❌ Неизвестный режим. Используй /subscribe mentions или /subscribe all."
        )
        return

    auth = await _resolve_user(user)
    user_id = auth.user_id if auth else None
    if not user_id:
        logger.warning("Auth failed for subscription actor %s", user.id)
        await update.message.reply_text("❌ Не удалось подтвердить аккаунт. Попробуй позже.")
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
            "ты подписан на упоминания в этом чате"
            if capture_mode == CAPTURE_MODE_MENTIONS
            else "ты подписан на полную ленту этого чата"
        )
        await update.message.reply_text(
            f"✅ {user.first_name}, {status}!\nРежим: {_mode_title(capture_mode)}."
        )
    else:
        changed = subscription.capture_mode != capture_mode
        if changed:
            subscription.capture_mode_changed_at = datetime.now(UTC)
        subscription.capture_mode = capture_mode
        subscription.tg_user_id = user.id
        subscription.tg_username = user.username
        await subscription.save(
            update_fields=(
                "capture_mode",
                "capture_mode_changed_at",
                "tg_user_id",
                "tg_username",
            )
        )
        logger.info(f"User {user.id} set {capture_mode} mode for chat {chat.id}")
        prefix = "✅ Режим изменён" if changed else "ℹ️ Ты уже подписан, этот режим включён"
        await update.message.reply_text(f"{prefix}: {_mode_title(capture_mode)}.")


async def mode_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or change the capture mode for the current chat."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or chat.type not in {"group", "supergroup"}:
        await update.message.reply_text("❌ Эта команда работает только в групповых чатах.")
        return

    auth = await _resolve_user(user)
    user_id = auth.user_id if auth else None
    if not user_id:
        await update.message.reply_text("❌ Не удалось подтвердить аккаунт. Попробуй позже.")
        return

    subscription = await UserChatSubscription.get_or_none(user_id=user_id, chat_id=chat.id)
    if not subscription:
        await update.message.reply_text(
            "ℹ️ Сначала подпишись: /subscribe mentions или /subscribe all."
        )
        return

    args = getattr(context, "args", None)
    if not isinstance(args, (list, tuple)) or not args:
        await update.message.reply_text(
            f"Текущий режим: {_mode_title(subscription.capture_mode)}.\n"
            "Сменить: /mode mentions или /mode all."
        )
        return

    capture_mode = _requested_capture_mode(context)
    if capture_mode is None:
        await update.message.reply_text("❌ Используй /mode mentions или /mode all.")
        return

    if subscription.capture_mode != capture_mode:
        subscription.capture_mode = capture_mode
        subscription.capture_mode_changed_at = datetime.now(UTC)
        await subscription.save(update_fields=("capture_mode", "capture_mode_changed_at"))
    await update.message.reply_text(f"✅ Режим изменён: {_mode_title(capture_mode)}.")


async def unsubscribe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unsubscribe command"""
    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    if chat.type not in {"group", "supergroup"}:
        await update.message.reply_text("❌ Эта команда работает только в групповых чатах.")
        return

    auth = await _resolve_user(user)
    user_id = auth.user_id if auth else None
    if not user_id:
        logger.warning("Auth failed for unsubscription actor %s", user.id)
        await update.message.reply_text("❌ Не удалось подтвердить аккаунт. Попробуй позже.")
        return

    subscription = await UserChatSubscription.get_or_none(user_id=user_id, chat_id=chat.id)
    found = subscription is not None
    if subscription and subscription.capture_mode != "disabled":
        subscription.capture_mode = "disabled"
        subscription.capture_mode_changed_at = datetime.now(UTC)
        await subscription.save(update_fields=("capture_mode", "capture_mode_changed_at"))

    if found:
        logger.info(f"User {user.id} unsubscribed from chat {chat.id}")
        await update.message.reply_text(f"✅ {user.first_name}, ты отписан от этого чата.")
    else:
        logger.debug(f"User {user.id} was not subscribed to chat {chat.id}")
        await update.message.reply_text(f"ℹ️ {user.first_name}, ты не был подписан на этот чат.")


async def my_mentions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /my_mentions command - show saved mentions"""
    user = update.effective_user

    if not user:
        return

    logger.debug(f"User {user.id} requested mentions")

    # TODO: Fetch mentions from database
    await update.message.reply_text(
        "📋 <b>Твои упоминания:</b>\n\n"
        "<i>Пока нет сохранённых упоминаний.</i>\n\n"
        "Подпишись на чат командой /subscribe",
        parse_mode="HTML",
    )
