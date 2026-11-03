from telegram.ext import (
    Application,
    BusinessConnectionHandler,
    BusinessMessagesDeletedHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import settings

from .business import (
    business_connection_handler,
    business_message_handler,
    business_messages_deleted_handler,
)
from .handlers import (
    bot_membership_handler,
    help_handler,
    mode_handler,
    my_mentions_handler,
    start_handler,
    subscribe_handler,
    unsubscribe_handler,
)
from .parser import message_handler


def create_bot_application() -> Application:
    """Create and configure the Telegram bot application"""
    application = Application.builder().token(settings.BOT_TOKEN).build()

    application.add_handler(
        ChatMemberHandler(bot_membership_handler, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # Business updates must be consumed before ordinary bot commands. A /start
    # in somebody's private conversation is archived, never executed by the bot.
    application.add_handler(BusinessConnectionHandler(business_connection_handler))
    application.add_handler(MessageHandler(
        filters.UpdateType.BUSINESS_MESSAGE | filters.UpdateType.EDITED_BUSINESS_MESSAGE,
        business_message_handler,
    ))
    application.add_handler(BusinessMessagesDeletedHandler(business_messages_deleted_handler))

    # Command handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(CommandHandler("subscribe", subscribe_handler))
    application.add_handler(CommandHandler("mode", mode_handler))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_handler))
    application.add_handler(CommandHandler("my_mentions", my_mentions_handler))

    # Capture text, media, captions, and edited messages. Bot commands are handled above.
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))

    return application


__all__ = ["create_bot_application"]
