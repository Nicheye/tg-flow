"""Business history belongs to the connected account, never to a shared peer ID."""

from models import BusinessConnection, UserChatSubscription


async def owns_subscription(subscription, user_id: int) -> bool:
    if subscription.user_id != user_id:
        return False
    chat = await subscription.chat
    if chat.business_connection_id is None:
        return chat.chat_type in {"group", "supergroup"}
    connection = await BusinessConnection.get_or_none(id=chat.business_connection_id)
    return bool(
        connection
        and connection.user_id == user_id
        and connection.tg_user_id == subscription.tg_user_id
    )


async def owned_subscription(user_id: int, chat_id: int):
    subscription = await UserChatSubscription.get_or_none(user_id=user_id, chat_id=chat_id)
    if subscription and await owns_subscription(subscription, user_id):
        return subscription
    return None


async def source_metadata(chat) -> dict:
    if chat.business_connection_id is None:
        return {"source": "group", "connection_active": True, "telegram_chat_id": None}
    connection = await BusinessConnection.get_or_none(id=chat.business_connection_id)
    return {
        "source": "business",
        "connection_active": bool(connection and connection.is_enabled),
        "telegram_chat_id": chat.telegram_chat_id,
    }
