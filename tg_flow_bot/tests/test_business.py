"""Private account ingestion and isolation across owners sharing a counterpart."""

import importlib
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Update

from bot import create_bot_application
from bot.business import (
    business_connection_handler,
    business_message_handler,
    business_messages_deleted_handler,
)
from models import BusinessConnection, Chat, ChatMessage, MentionedMessage, UserChatSubscription
from schemas import AuthResponse
from services.chat_unread import list_unread


def connection_update(update_id=1, owner=123456789, connection="conn-a", enabled=True):
    return Update.de_json(
        {
            "update_id": update_id,
            "business_connection": {
                "id": connection,
                "user": {"id": owner, "is_bot": False, "first_name": "Owner"},
                "user_chat_id": owner,
                "date": 1793710800,
                "rights": {"can_reply": False},
                "is_enabled": enabled,
            },
        },
        None,
    )


def message_update(
    update_id=2,
    message_id=1,
    connection="conn-a",
    peer=777,
    text="private-a",
    edit=False,
    sender=777,
):
    return Update.de_json(
        {
            "update_id": update_id,
            "edited_business_message" if edit else "business_message": {
                "message_id": message_id,
                "business_connection_id": connection,
                "date": 1793710801,
                "chat": {"id": peer, "type": "private", "first_name": "Counterpart"},
                "from": {"id": sender, "is_bot": False, "first_name": "Sender"},
                "text": text,
            },
        },
        None,
    )


def deletion_update(update_id=3, connection="conn-a", peer=777, ids=(1,)):
    return Update.de_json(
        {
            "update_id": update_id,
            "deleted_business_messages": {
                "business_connection_id": connection,
                "chat": {"id": peer, "type": "private", "first_name": "Counterpart"},
                "message_ids": list(ids),
            },
        },
        None,
    )


@pytest.fixture
def register_owner():
    async def register(user):
        return AuthResponse(
            user_id=1 if user.tg_user_id == 123456789 else 2,
            access="test",
            refresh="test",
            created=True,
        )

    with patch("bot.business.auth_client.register", side_effect=register) as mock:
        yield mock


@pytest.fixture
async def private_subscription(db, register_owner):
    await business_connection_handler(connection_update(), None)
    await business_message_handler(message_update(), None)
    return await UserChatSubscription.get(user_id=1)


@pytest.mark.asyncio
async def test_same_peer_and_message_are_isolated_per_business_owner(private_subscription):
    await business_connection_handler(connection_update(3, owner=999, connection="conn-b"), None)
    await business_message_handler(message_update(4, connection="conn-b", text="private-b"), None)
    chats = await Chat.all().order_by("id")
    assert len(chats) == 2 and chats[0].id != chats[1].id
    assert all(chat.id > 0 and chat.id != 777 for chat in chats)
    assert all(chat.telegram_chat_id == 777 for chat in chats)
    assert [row.text for row in await ChatMessage.all().order_by("id")] == [
        "private-a",
        "private-b",
    ]
    assert await MentionedMessage.all().count() == 0
    one = await list_unread(1, chats[0].id)
    assert [row.text for row in one["messages"]] == ["private-a"]
    with pytest.raises(ValueError, match="not found"):
        await list_unread(2, chats[0].id)


@pytest.mark.asyncio
async def test_unknown_connection_and_registration_failure_do_not_capture(db):
    await business_message_handler(message_update(), None)
    with patch("bot.business.auth_client.register", new=AsyncMock(return_value=None)):
        await business_connection_handler(connection_update(), None)
    await business_message_handler(message_update(), None)
    assert await Chat.all().count() == 0
    assert await BusinessConnection.all().count() == 0


@pytest.mark.asyncio
async def test_edits_deletes_are_scoped_and_delete_does_not_resurrect(private_subscription):
    await business_connection_handler(connection_update(3, owner=999, connection="conn-b"), None)
    await business_message_handler(message_update(4, connection="conn-b", text="other-owner"), None)
    await business_message_handler(message_update(5, text="edited", edit=True), None)
    assert (await ChatMessage.get(chat_id=private_subscription.chat_id)).text == "edited"
    await business_messages_deleted_handler(deletion_update(6), None)
    await business_message_handler(message_update(2), None)  # original update replay
    await business_message_handler(message_update(7, edit=True), None)
    assert await ChatMessage.filter(chat_id=private_subscription.chat_id).count() == 0
    assert [row.text for row in await ChatMessage.all()] == ["other-owner"]


@pytest.mark.asyncio
async def test_local_disable_blocks_edits_new_messages_but_honors_deletions(private_subscription):
    private_subscription.capture_mode = "disabled"
    await private_subscription.save()
    await business_message_handler(message_update(3, text="new-content", edit=True), None)
    await business_message_handler(message_update(4, message_id=2), None)
    assert (await ChatMessage.get(chat_id=private_subscription.chat_id)).text == "private-a"
    await business_messages_deleted_handler(deletion_update(5), None)
    assert await ChatMessage.all().count() == 0


@pytest.mark.asyncio
async def test_resume_retains_private_archive_and_cursor_but_not_disabled_messages(
    client, private_subscription, monkeypatch
):
    from mcp_server import create_mcp_server
    from services.security import TokenPayload

    chat_id = private_subscription.chat_id
    await business_message_handler(message_update(3, message_id=2, text="saved before pause"), None)
    page = (await client.get(f"/api/chats/{chat_id}/unread")).json()
    old_generation = page["capture_mode_changed_at"]
    marked = await client.post(
        f"/api/chats/{chat_id}/read",
        json={
            "through_message_id": 1,
            "capture_mode_changed_at": old_generation,
        },
    )
    assert marked.status_code == 200
    assert (
        await client.patch(f"/api/chats/{chat_id}/mode", json={"capture_mode": "disabled"})
    ).status_code == 200
    await business_message_handler(message_update(4, message_id=3, text="must not be saved"), None)
    assert (
        await client.patch(f"/api/chats/{chat_id}/mode", json={"capture_mode": "full"})
    ).status_code == 200
    await business_message_handler(message_update(5, message_id=4, text="saved after pause"), None)
    messages = (await client.get(f"/api/chats/{chat_id}/messages")).json()
    assert [row["message_id"] for row in messages] == [1, 2, 4]
    resumed = (await client.get(f"/api/chats/{chat_id}/unread")).json()
    assert [row["message_id"] for row in resumed["messages"]] == [2, 4]
    assert resumed["read_through_message_id"] == 1
    assert resumed["capture_mode_changed_at"] != old_generation
    assert (
        await client.post(
            f"/api/chats/{chat_id}/read",
            json={
                "through_message_id": 2,
                "capture_mode_changed_at": old_generation,
            },
        )
    ).status_code == 409

    async def principal():
        return TokenPayload(user_id=1, scopes=["mentions:read"])

    monkeypatch.setattr("mcp_server._principal", principal)
    server, _ = create_mcp_server()
    result = str(await server.call_tool("list_chat_messages", {"chat_id": chat_id}))
    assert "saved before pause" in result and "saved after pause" in result
    assert "must not be saved" not in result
    result = str(await server.call_tool("list_unread_chat_messages", {"chat_id": chat_id}))
    assert "saved before pause" in result and "saved after pause" in result


@pytest.mark.asyncio
async def test_revoke_rotation_replay_and_reconnect_preserve_optout_cursor(private_subscription):
    private_subscription.capture_mode = "disabled"
    private_subscription.read_through_message_id = 1
    await private_subscription.save()
    await business_connection_handler(connection_update(3, enabled=False), None)
    await business_connection_handler(connection_update(1, enabled=True), None)
    await business_message_handler(message_update(4, message_id=2), None)
    assert await ChatMessage.all().count() == 1
    await business_connection_handler(connection_update(5, connection="conn-new"), None)
    await business_connection_handler(connection_update(6, connection="conn-a"), None)
    await business_message_handler(message_update(7, connection="conn-a", message_id=3), None)
    await business_message_handler(message_update(8, connection="conn-new", message_id=4), None)
    await private_subscription.refresh_from_db()
    assert private_subscription.capture_mode == "disabled"
    assert private_subscription.read_through_message_id == 1
    assert await Chat.all().count() == 1
    assert await ChatMessage.all().count() == 1
    assert (await BusinessConnection.get()).connection_id == "conn-new"


@pytest.mark.asyncio
async def test_aged_owner_never_reactivates_or_mutates_from_stale_updates(private_subscription):
    await business_connection_handler(connection_update(10, enabled=False), None)
    await BusinessConnection.all().update(updated_at=datetime.now(UTC) - timedelta(days=8))
    await business_connection_handler(connection_update(1, enabled=True), None)
    connection = await BusinessConnection.get()
    assert not connection.is_enabled and connection.last_update_id == 10
    await business_message_handler(message_update(2, message_id=2), None)
    await business_messages_deleted_handler(deletion_update(3), None)
    assert await ChatMessage.all().count() == 1
    # Even an enabled, old account cannot accept old edits/deletions after an
    # idle week, while unrelated groups may have kept the bot stream active.
    await business_connection_handler(connection_update(11, enabled=True), None)
    await BusinessConnection.all().update(updated_at=datetime.now(UTC) - timedelta(days=8))
    await business_message_handler(message_update(5, edit=True, text="replayed edit"), None)
    await business_messages_deleted_handler(deletion_update(6), None)
    assert (await ChatMessage.get()).text == "private-a"
    assert (await BusinessConnection.get()).last_update_id == 11


@pytest.mark.asyncio
async def test_verified_new_connection_recovers_true_global_update_reset(private_subscription):
    await business_connection_handler(connection_update(100, enabled=False), None)
    reset = connection_update(1, connection="fresh-id")
    verify = AsyncMock(return_value=reset.business_connection)
    context = SimpleNamespace(bot=SimpleNamespace(get_business_connection=verify))
    await business_connection_handler(reset, context)
    connection = await BusinessConnection.get()
    assert connection.connection_id == "fresh-id" and connection.is_enabled
    assert connection.last_update_id == 1 and "conn-a" in connection.retired_connection_ids
    verify.assert_awaited_once()
    await business_message_handler(message_update(2, connection="fresh-id", message_id=2), None)
    await business_message_handler(message_update(101, message_id=3), None)
    await business_messages_deleted_handler(deletion_update(102), None)
    assert [row.message_id for row in await ChatMessage.all().order_by("message_id")] == [1, 2]
    # An authoritative response for the same active ID still cannot lower its
    # watermark and permit old message content to be replayed.
    await business_connection_handler(connection_update(0, connection="fresh-id"), context)
    assert (await BusinessConnection.get()).last_update_id == 2
    assert verify.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("verification", ["network", "owner", "id", "enabled"])
async def test_reset_verification_fails_closed(private_subscription, verification):
    from telegram.error import TimedOut

    await business_connection_handler(connection_update(100, enabled=False), None)
    reset = connection_update(1, connection="fresh-id")
    if verification == "network":
        verify = AsyncMock(side_effect=TimedOut("fixture timeout"))
    else:
        current = connection_update(
            1,
            owner=999 if verification == "owner" else 123456789,
            connection="wrong-id" if verification == "id" else "fresh-id",
            enabled=verification != "enabled",
        ).business_connection
        verify = AsyncMock(return_value=current)
    context = SimpleNamespace(bot=SimpleNamespace(get_business_connection=verify))
    await business_connection_handler(reset, context)
    connection = await BusinessConnection.get()
    assert connection.connection_id == "conn-a" and not connection.is_enabled
    assert connection.last_update_id == 100


@pytest.mark.asyncio
async def test_outgoing_caption_is_captured_without_sending_or_telegram_read(private_subscription):
    payload = message_update(3, message_id=2, sender=123456789).business_message.to_dict()
    payload.pop("text")
    payload["caption"] = "Owner's outgoing caption"
    update = Update.de_json({"update_id": 3, "business_message": payload}, None)
    context = SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock(), read_business_message=AsyncMock())
    )
    await business_message_handler(update, context)
    row = await ChatMessage.get(chat_id=private_subscription.chat_id, message_id=2)
    assert row.from_user_id == 123456789 and row.text == "Owner's outgoing caption"
    context.bot.send_message.assert_not_awaited()
    context.bot.read_business_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_business_restart_uses_persistent_owner_and_cursor(tmp_path, register_owner):
    from tortoise import Tortoise

    url = f"sqlite://{tmp_path / 'restart.sqlite3'}"
    config = {"db_url": url, "modules": {"models": ["models"]}}
    try:
        await Tortoise.init(**config)
        await Tortoise.generate_schemas()
        await business_connection_handler(connection_update(), None)
        await business_message_handler(message_update(), None)
        subscription = await UserChatSubscription.get(user_id=1)
        chat_id = subscription.chat_id
        subscription.read_through_message_id = 1
        await subscription.save()
        await Tortoise.close_connections()
        await Tortoise.init(**config)
        # A new process receives only a message, not the original connection
        # event. Durable ownership and the read marker must still be available.
        await business_message_handler(message_update(3, message_id=2), None)
        page = await list_unread(1, chat_id)
        assert [row.message_id for row in page["messages"]] == [2]
        assert page["read_through_message_id"] == 1
        assert await Chat.all().count() == 1
        assert register_owner.call_count == 1
    finally:
        await Tortoise.close_connections()


@pytest.mark.asyncio
async def test_disconnected_history_and_read_cursor_remain_owner_accessible(
    client, private_subscription
):
    await business_connection_handler(connection_update(3, enabled=False), None)
    chat_id = private_subscription.chat_id
    listing = (await client.get("/api/chats/")).json()[0]
    assert listing["source"] == "business" and listing["connection_active"] is False
    assert listing["telegram_chat_id"] == 777
    assert (await client.get(f"/api/chats/{chat_id}/messages")).json()[0]["text"] == "private-a"
    page = (await client.get(f"/api/chats/{chat_id}/unread")).json()
    marked = await client.post(
        f"/api/chats/{chat_id}/read",
        json={
            "through_message_id": 1,
            "capture_mode_changed_at": page["capture_mode_changed_at"],
        },
    )
    assert marked.status_code == 200 and marked.json()["unread_count"] == 0
    assert (
        await client.patch(f"/api/chats/{chat_id}/mode", json={"capture_mode": "mentions"})
    ).status_code == 422
    assert (
        await client.patch(f"/api/chats/{chat_id}/mode", json={"capture_mode": "disabled"})
    ).status_code == 200
    assert (
        await client.patch(f"/api/chats/{chat_id}/mode", json={"capture_mode": "full"})
    ).status_code == 409
    assert (await client.get(f"/api/chats/{chat_id}/photo")).status_code == 404


@pytest.mark.asyncio
async def test_forged_subscription_cannot_expose_private_feed(client, private_subscription):
    await business_connection_handler(connection_update(3, owner=999, connection="conn-b"), None)
    await business_message_handler(
        message_update(4, connection="conn-b", text="secret-other-owner"), None
    )
    other = await UserChatSubscription.get(user_id=2)
    forged = await UserChatSubscription.create(
        user_id=1, tg_user_id=123456789, chat_id=other.chat_id, capture_mode="full"
    )
    listing = (await client.get("/api/chats/")).json()
    assert len(listing) == 1 and listing[0]["chat_id"] == private_subscription.chat_id
    for suffix in ("messages", "unread", "photo"):
        assert (await client.get(f"/api/chats/{other.chat_id}/{suffix}")).status_code == 404
    assert (
        await client.patch(f"/api/chats/{other.chat_id}/mode", json={"capture_mode": "full"})
    ).status_code == 404
    assert (
        await client.post(
            f"/api/chats/{other.chat_id}/read",
            json={
                "through_message_id": 1,
                "capture_mode_changed_at": forged.capture_mode_changed_at.isoformat(),
            },
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_business_commands_dispatched_only_to_capture(private_subscription, monkeypatch):
    monkeypatch.setattr("bot.settings.BOT_TOKEN", "123456:test-token")
    application = create_bot_application()
    update = message_update(3, message_id=2, text="/subscribe all")
    from telegram import MessageEntity

    update = Update.de_json(
        {
            "update_id": 3,
            "business_message": {
                **update.business_message.to_dict(),
                "entities": [{"type": MessageEntity.BOT_COMMAND, "offset": 0, "length": 10}],
            },
        },
        application.bot,
    )
    selected = next(handler for handler in application.handlers[0] if handler.check_update(update))
    assert selected.callback is business_message_handler
    await selected.callback(update, None)
    assert (
        await ChatMessage.get(chat_id=private_subscription.chat_id, message_id=2)
    ).text == "/subscribe all"


@pytest.mark.asyncio
async def test_business_mcp_read_ack_and_other_owner_rejection(private_subscription, monkeypatch):
    from mcp_server import create_mcp_server
    from services.security import TokenPayload

    principal = TokenPayload(user_id=1, scopes=["mentions:read", "mentions:write"])

    async def current():
        return principal

    monkeypatch.setattr("mcp_server._principal", current)
    server, _ = create_mcp_server()
    subscriptions = await server.call_tool("list_chat_subscriptions", {})
    assert "business" in str(subscriptions)
    result = await server.call_tool(
        "list_unread_chat_messages", {"chat_id": private_subscription.chat_id}
    )
    assert "private-a" in str(result)
    await server.call_tool(
        "mark_chat_read",
        {
            "chat_id": private_subscription.chat_id,
            "through_message_id": 1,
            "capture_mode_changed_at": private_subscription.capture_mode_changed_at.isoformat(),
        },
    )
    await private_subscription.refresh_from_db()
    assert private_subscription.read_through_message_id == 1
    principal.user_id = 2
    with pytest.raises(Exception, match="not found"):
        await server.call_tool("list_chat_messages", {"chat_id": private_subscription.chat_id})


@pytest.mark.asyncio
async def test_business_migration_preserves_existing_rows_and_restart(tmp_path):
    migration = importlib.import_module(
        "migrations.models.5_20261103120000_add_business_connections"
    )
    dialect = SimpleNamespace(capabilities=SimpleNamespace(dialect="sqlite"))
    path = tmp_path / "business.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE chats (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
        db.execute("INSERT INTO chats VALUES(-100, 'Existing group')")
        db.executescript(await migration.upgrade(dialect))
        assert db.execute("SELECT id,title,business_connection_id FROM chats").fetchone() == (
            -100,
            "Existing group",
            None,
        )
        db.execute(
            "INSERT INTO business_connections(tg_user_id,user_id,connection_id,connected_at) VALUES(123,1,'conn',CURRENT_TIMESTAMP)"
        )
        db.execute(
            "INSERT INTO chats(title,business_connection_id,telegram_chat_id) VALUES('Private',1,777)"
        )
        assert db.execute("SELECT id FROM chats WHERE telegram_chat_id=777").fetchone()[0] > 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT connection_id FROM business_connections").fetchone() == ("conn",)
        assert db.execute("SELECT count(*) FROM chats").fetchone() == (2,)
    with pytest.raises(RuntimeError, match="verified backup"):
        await migration.downgrade(dialect)
