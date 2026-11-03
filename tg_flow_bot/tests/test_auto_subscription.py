"""Automatic owner subscription and persistent opt-out regression coverage."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram.ext import ChatMemberHandler

from bot import create_bot_application
from bot.handlers import bot_membership_handler, subscribe_handler, unsubscribe_handler
from bot.parser import message_handler
from models import Chat, ChatMessage, MentionedMessage, UserChatSubscription
from schemas import AuthResponse


def membership(
    old="left",
    new="member",
    *,
    chat_type="supergroup",
    actor_id=123,
    is_bot=False,
    old_member=False,
    new_member=True,
):
    actor = SimpleNamespace(
        id=actor_id, is_bot=is_bot, username="owner", first_name="Owner", last_name=None
    )
    event = SimpleNamespace(
        chat=SimpleNamespace(id=-1001234567890, type=chat_type, title="Group", username=None),
        from_user=actor,
        old_chat_member=SimpleNamespace(status=old, is_member=old_member),
        new_chat_member=SimpleNamespace(status=new, is_member=new_member),
    )
    return SimpleNamespace(my_chat_member=event)


@pytest.fixture
def auth_register():
    with patch("bot.handlers.auth_client.register", new_callable=AsyncMock) as register:
        register.return_value = AuthResponse(
            user_id=42, access="test", refresh="test", created=True
        )
        yield register


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "old,new", [("left", "member"), ("kicked", "administrator"), ("restricted", "member")]
)
async def test_add_registers_only_actor_without_start(db, mock_context, auth_register, old, new):
    update = membership(old, new)
    await bot_membership_handler(update, mock_context)
    auth_register.assert_awaited_once()
    assert auth_register.call_args.args[0].tg_user_id == 123
    subscriptions = await UserChatSubscription.all()
    assert len(subscriptions) == 1
    assert (
        subscriptions[0].user_id,
        subscriptions[0].tg_user_id,
        subscriptions[0].capture_mode,
    ) == (42, 123, "full")
    assert mock_context.user_data == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"old": "member", "new": "administrator"},
        {"old": "administrator", "new": "member"},
        {"new": "left"},
        {"new": "kicked"},
        {"chat_type": "private"},
        {"chat_type": "channel"},
        {"is_bot": True},
        {"actor_id": 1087968824},
        {"old": "restricted", "old_member": True},
        {"new": "restricted", "new_member": False},
    ],
)
async def test_non_add_events_and_nonhuman_actors_ignored(db, mock_context, auth_register, kwargs):
    await bot_membership_handler(membership(**kwargs), mock_context)
    auth_register.assert_not_awaited()
    assert not await UserChatSubscription.all().exists()


@pytest.mark.asyncio
async def test_missing_actor_or_membership_ignored(db, mock_context, auth_register):
    update = membership()
    update.my_chat_member.from_user = None
    await bot_membership_handler(update, mock_context)
    await bot_membership_handler(SimpleNamespace(my_chat_member=None), mock_context)
    auth_register.assert_not_awaited()
    assert not await Chat.all().exists()


@pytest.mark.asyncio
async def test_auth_failure_does_not_create_subscription(db, mock_context, auth_register):
    auth_register.return_value = None
    await bot_membership_handler(membership(), mock_context)
    assert not await Chat.all().exists()
    assert not await UserChatSubscription.all().exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mentions", "full", "disabled"])
async def test_duplicates_and_readd_preserve_mode_and_timestamp(
    db, mock_context, auth_register, mode
):
    await bot_membership_handler(membership(), mock_context)
    subscription = await UserChatSubscription.get(user_id=42)
    subscription.capture_mode = mode
    await subscription.save()
    cutoff = subscription.capture_mode_changed_at
    await bot_membership_handler(membership(), mock_context)
    await bot_membership_handler(membership(new="left"), mock_context)
    await bot_membership_handler(membership(), mock_context)
    await subscription.refresh_from_db()
    assert subscription.capture_mode == mode
    assert subscription.capture_mode_changed_at == cutoff
    assert await UserChatSubscription.all().count() == 1


@pytest.mark.asyncio
async def test_add_does_not_change_other_users_subscription(db, chat, mock_context, auth_register):
    other = await UserChatSubscription.create(
        user_id=99, tg_user_id=99, chat=chat, capture_mode="disabled"
    )
    await bot_membership_handler(membership(), mock_context)
    await other.refresh_from_db()
    assert other.capture_mode == "disabled"
    assert await UserChatSubscription.all().count() == 2


@pytest.mark.asyncio
async def test_recovery_command_resolves_identity_after_restart(
    db, make_update, mock_context, auth_register
):
    update = make_update("")
    update.effective_user.is_bot = False
    mock_context.args = ["all"]
    mock_context.user_data = {"user_id": 666}  # cached data must not authorize a different user
    await subscribe_handler(update, mock_context)
    auth_register.assert_awaited_once()
    assert await UserChatSubscription.exists(user_id=42, capture_mode="full")
    assert not await UserChatSubscription.exists(user_id=666)


@pytest.mark.asyncio
async def test_unsubscribe_preserves_history_and_can_reenable(
    db, make_update, mock_context, auth_register
):
    await bot_membership_handler(membership(), mock_context)
    subscription = await UserChatSubscription.get(user_id=42)
    mention = await MentionedMessage.create(
        user_id=42,
        chat_id=subscription.chat_id,
        subscription=subscription,
        message_id=2,
        from_user_id=8,
        text="saved",
        message_date=datetime.now(UTC),
    )
    update = make_update("")
    update.effective_user.is_bot = False
    await unsubscribe_handler(update, mock_context)
    await subscription.refresh_from_db()
    assert subscription.capture_mode == "disabled"
    assert await MentionedMessage.exists(id=mention.id)
    mock_context.args = ["all"]
    await subscribe_handler(update, mock_context)
    await subscription.refresh_from_db()
    assert subscription.capture_mode == "full"
    assert await MentionedMessage.exists(id=mention.id)


@pytest.mark.asyncio
async def test_disabled_only_group_captures_no_content(db, subscription, make_update, mock_context):
    subscription.capture_mode = "disabled"
    await subscription.save()
    await message_handler(make_update("Hey @testuser", mentions=[(4, 9, "mention")]), mock_context)
    assert not await ChatMessage.all().exists()
    assert not await MentionedMessage.all().exists()


@pytest.mark.asyncio
async def test_shared_edits_keep_disabled_history_and_reconcile_active_mentions(
    db, subscription, make_update, mock_context
):
    second = await UserChatSubscription.create(
        user_id=2,
        chat_id=subscription.chat_id,
        tg_user_id=222,
        tg_username="second",
        capture_mode="full",
    )
    original = make_update("@testuser @second", mentions=[(0, 9, "mention"), (10, 7, "mention")])
    await message_handler(original, mock_context)
    assert await MentionedMessage.all().count() == 2
    subscription.capture_mode = "disabled"
    await subscription.save()
    edited = make_update("edited without mentions")
    await message_handler(edited, mock_context)
    saved = await MentionedMessage.get(subscription_id=subscription.id)
    assert saved.text == "@testuser @second"
    assert not await MentionedMessage.exists(subscription_id=second.id)
    assert (await ChatMessage.get(message_id=12345)).text == "edited without mentions"
    # Disabled users are not newly matched while others still capture content.
    edited = make_update("@testuser", mentions=[(0, 9, "mention")])
    await message_handler(edited, mock_context)
    assert await MentionedMessage.all().count() == 1
    await saved.refresh_from_db()
    assert saved.text == "@testuser @second"


def test_application_registers_bot_membership_handler(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "BOT_TOKEN", "123:test-only")
    app = create_bot_application()
    assert any(
        isinstance(handler, ChatMemberHandler)
        and handler.chat_member_types == ChatMemberHandler.MY_CHAT_MEMBER
        for handlers in app.handlers.values()
        for handler in handlers
    )


@pytest.mark.asyncio
async def test_disabled_context_excludes_new_and_edited_shared_content(
    db, subscription, make_update, mock_context, client, monkeypatch
):
    from mcp_server import create_mcp_server
    from services.security import TokenPayload

    active = await UserChatSubscription.create(
        user_id=2, chat_id=subscription.chat_id, tg_user_id=222, capture_mode="full"
    )
    # A keeps an independent historical mention; neighboring rows belong to the
    # shared stream and may continue to be captured for B after A opts out.
    for message_id, text, entities in (
        (10, "historical before", None),
        (20, "@testuser", [(0, 9, "mention")]),
        (30, "historical after", None),
        (40, "historical context later edited", None),
    ):
        update = make_update(text, mentions=entities)
        update.effective_message.message_id = message_id
        await message_handler(update, mock_context)
    mention = await MentionedMessage.get(subscription_id=subscription.id)
    subscription.capture_mode = "disabled"
    subscription.capture_mode_changed_at = datetime.now(UTC)
    await subscription.save()
    update = make_update("new private-to-active-subscriber content")
    update.effective_message.message_id = 50
    await message_handler(update, mock_context)
    update = make_update("edited private-to-active-subscriber content")
    update.effective_message.message_id = 40
    await message_handler(update, mock_context)
    # The mention's primary shared row can also be edited, but its historical
    # snapshot must remain the primary response for the disabled subscriber.
    update = make_update("edited primary private content")
    update.effective_message.message_id = 20
    await message_handler(update, mock_context)

    response = await client.get(f"/api/mentions/{mention.id}/context", params={"after": 50})
    assert response.status_code == 200
    data = response.json()
    assert data["mention"]["text"] == "@testuser"
    assert [row["message_id"] for row in data["before"]] == [10]
    assert [row["message_id"] for row in data["after"]] == [30]
    assert "private" not in str(data)
    assert await ChatMessage.exists(message_id=50)
    assert "edited" in (await ChatMessage.get(message_id=40)).text
    assert active.capture_mode == "full"

    async def principal():
        return TokenPayload(user_id=1, scopes=["mentions:read"])

    monkeypatch.setattr("mcp_server._principal", principal)
    server, _ = create_mcp_server()
    result = await server.call_tool("get_mention_context", {"mention_id": mention.id, "after": 50})
    assert "historical before" in str(result)
    assert "historical after" in str(result)
    assert "private" not in str(result)
    assert "later edited" not in str(result)
