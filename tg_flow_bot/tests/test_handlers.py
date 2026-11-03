from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers import (
    help_handler,
    mode_handler,
    my_mentions_handler,
    start_handler,
    subscribe_handler,
    unsubscribe_handler,
)
from models import Chat, UserChatSubscription
from schemas import AuthResponse


@pytest.fixture(autouse=True)
def registered_identity(mock_context):
    async def resolve(user):
        user_id = mock_context.user_data.get("user_id")
        return (
            AuthResponse(user_id=user_id, access="test", refresh="test", created=False)
            if user_id
            else None
        )

    with patch("bot.handlers._resolve_user", side_effect=resolve):
        yield


# === /start ===


@pytest.mark.asyncio
async def test_start_ignores_update_without_user(make_update, mock_context):
    update = make_update("", chat_type="private")
    update.effective_user = None

    await start_handler(update, mock_context)

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_start_new_user(make_update, mock_context):
    update = make_update("", chat_type="private")
    auth = AuthResponse(user_id=1, access="token", refresh="refresh", created=True)

    with patch("bot.handlers.auth_client.register", new_callable=AsyncMock, return_value=auth):
        await start_handler(update, mock_context)

    assert mock_context.user_data["user_id"] == 1
    assert "зарегистрирован" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_start_existing_user(make_update, mock_context):
    update = make_update("", chat_type="private")
    auth = AuthResponse(user_id=1, access="token", refresh="refresh", created=False)

    with patch("bot.handlers.auth_client.register", new_callable=AsyncMock, return_value=auth):
        await start_handler(update, mock_context)

    assert "уже зарегистрирован" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_start_error(make_update, mock_context):
    update = make_update("", chat_type="private")

    with patch("bot.handlers.auth_client.register", new_callable=AsyncMock, return_value=None):
        await start_handler(update, mock_context)

    assert "Ошибка" in update.message.reply_text.call_args[0][0]


# === /help ===


@pytest.mark.asyncio
async def test_help(make_update, mock_context):
    update = make_update("", chat_type="private")
    await help_handler(update, mock_context)

    text = update.message.reply_text.call_args[0][0]
    assert "/start" in text
    assert "/subscribe" in text


# === /subscribe ===


@pytest.mark.asyncio
async def test_subscribe_ignores_update_without_chat(make_update, mock_context):
    update = make_update("")
    update.effective_chat = None

    await subscribe_handler(update, mock_context)

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_subscribe_private_chat(make_update, mock_context):
    update = make_update("", chat_type="private")
    await subscribe_handler(update, mock_context)

    assert "групповых чатах" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_subscribe_not_registered(make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {}

    await subscribe_handler(update, mock_context)

    assert "подтвердить аккаунт" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_subscribe_success(db, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": 1}

    await subscribe_handler(update, mock_context)

    assert "подписан на упоминания" in update.message.reply_text.call_args[0][0]
    assert await Chat.exists(id=-1001234567890)
    assert await UserChatSubscription.exists(user_id=1)


@pytest.mark.asyncio
async def test_subscribe_saves_chat_photo(db, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": 1}
    photo = MagicMock()
    photo.small_file_id = "small-photo-id"
    mock_context.bot.get_chat.return_value.photo = photo

    await subscribe_handler(update, mock_context)

    chat = await Chat.get(id=-1001234567890)
    assert chat.photo_file_id == "small-photo-id"


@pytest.mark.asyncio
async def test_subscribe_full_mode(db, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": 1}
    mock_context.args = ["all"]

    await subscribe_handler(update, mock_context)

    subscription = await UserChatSubscription.get(user_id=1)
    assert subscription.capture_mode == "full"
    assert "полную ленту" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_subscribe_rejects_unknown_mode(db, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": 1}
    mock_context.args = ["unexpected"]

    await subscribe_handler(update, mock_context)

    assert "Неизвестный режим" in update.message.reply_text.call_args[0][0]
    assert await UserChatSubscription.all().count() == 0


@pytest.mark.asyncio
async def test_mode_changes_existing_subscription(db, subscription, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": subscription.user_id}
    mock_context.args = ["all"]

    await mode_handler(update, mock_context)

    await subscription.refresh_from_db()
    assert subscription.capture_mode == "full"


@pytest.mark.asyncio
async def test_mode_reports_current_mode(db, subscription, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": subscription.user_id}
    mock_context.args = []

    await mode_handler(update, mock_context)

    assert "Текущий режим" in update.message.reply_text.call_args[0][0]
    assert "упоминания и контекст" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_mode_private_chat_is_rejected(make_update, mock_context):
    update = make_update("", chat_type="private")

    await mode_handler(update, mock_context)

    assert "групповых чатах" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_mode_requires_registration(make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {}

    await mode_handler(update, mock_context)

    assert "подтвердить аккаунт" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_mode_requires_subscription(db, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": 1}

    await mode_handler(update, mock_context)

    assert "Сначала подпишись" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_mode_rejects_unknown_value(db, subscription, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": subscription.user_id}
    mock_context.args = ["unexpected"]

    await mode_handler(update, mock_context)

    await subscription.refresh_from_db()
    assert subscription.capture_mode == "mentions"
    assert "Используй /mode" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_mode_same_value_keeps_original_timestamp(
    db, subscription, make_update, mock_context
):
    update = make_update("")
    original_timestamp = subscription.capture_mode_changed_at
    mock_context.user_data = {"user_id": subscription.user_id}
    mock_context.args = ["mentions"]

    await mode_handler(update, mock_context)

    await subscription.refresh_from_db()
    assert subscription.capture_mode_changed_at == original_timestamp


@pytest.mark.asyncio
async def test_subscribe_already_subscribed(db, subscription, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": subscription.user_id}

    await subscribe_handler(update, mock_context)

    assert "уже подписан" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_subscribe_existing_subscription_changes_mode(
    db, subscription, make_update, mock_context
):
    update = make_update("")
    original_timestamp = subscription.capture_mode_changed_at
    mock_context.user_data = {"user_id": subscription.user_id}
    mock_context.args = ["all"]

    await subscribe_handler(update, mock_context)

    await subscription.refresh_from_db()
    assert subscription.capture_mode == "full"
    assert subscription.capture_mode_changed_at >= original_timestamp
    assert "Режим изменён" in update.message.reply_text.call_args[0][0]


# === /unsubscribe ===


@pytest.mark.asyncio
async def test_unsubscribe_ignores_update_without_user(make_update, mock_context):
    update = make_update("")
    update.effective_user = None

    await unsubscribe_handler(update, mock_context)

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_unsubscribe_rejects_private_chat(make_update, mock_context):
    update = make_update("", chat_type="private")

    await unsubscribe_handler(update, mock_context)

    assert "групповых чатах" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_unsubscribe_requires_registration(make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {}

    await unsubscribe_handler(update, mock_context)

    assert "подтвердить аккаунт" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_unsubscribe_success(db, subscription, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": subscription.user_id}

    await unsubscribe_handler(update, mock_context)

    assert "отписан" in update.message.reply_text.call_args[0][0]
    await subscription.refresh_from_db()
    assert subscription.capture_mode == "disabled"


@pytest.mark.asyncio
async def test_unsubscribe_not_subscribed(db, chat, make_update, mock_context):
    update = make_update("")
    mock_context.user_data = {"user_id": 999}

    await unsubscribe_handler(update, mock_context)

    assert "не был подписан" in update.message.reply_text.call_args[0][0]


# === /my_mentions ===


@pytest.mark.asyncio
async def test_my_mentions_ignores_update_without_user(make_update, mock_context):
    update = make_update("", chat_type="private")
    update.effective_user = None

    await my_mentions_handler(update, mock_context)

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_my_mentions_empty(make_update, mock_context):
    update = make_update("", chat_type="private")
    await my_mentions_handler(update, mock_context)

    assert "нет сохранённых" in update.message.reply_text.call_args[0][0]
