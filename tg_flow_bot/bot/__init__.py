from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import settings

from .handlers import (
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
