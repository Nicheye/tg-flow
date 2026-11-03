import asyncio
import importlib
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from bot.business import business_message_handler
from models import BusinessConnection, BusinessReplyAttempt, Chat, ChatMessage, UserChatSubscription
from services.business_reply import BusinessReplyError, send_business_reply
from tests.test_business import message_update


@pytest.fixture
async def reply_chat(db):
    connection = await BusinessConnection.create(
        user_id=1,
        tg_user_id=123456789,
        connection_id="reply-connection",
        is_enabled=True,
        last_update_id=10,
        connected_at=datetime.now(UTC),
    )
    chat = await Chat.create(
        chat_type="private",
        telegram_chat_id=777,
        business_connection=connection,
        title="Synthetic recipient",
    )
    subscription = await UserChatSubscription.create(
        user_id=1, tg_user_id=connection.tg_user_id, chat=chat, capture_mode="full"
    )
    await ChatMessage.create(
        chat=chat,
        message_id=1,
        from_user_id=777,
        text="Synthetic incoming",
        message_date=datetime.now(UTC),
    )
    return subscription


@pytest.fixture
def sdk(monkeypatch):
    info = SimpleNamespace(
        id="reply-connection",
        user=SimpleNamespace(id=123456789, is_bot=False, username="synthetic_owner"),
        is_enabled=True,
        rights=SimpleNamespace(can_reply=True),
    )
    sent = SimpleNamespace(
        message_id=2,
        text="Synthetic reply",
        date=datetime.now(UTC),
        reply_to_message=SimpleNamespace(message_id=1),
    )
    bot = SimpleNamespace(
        get_business_connection=AsyncMock(return_value=info),
        send_message=AsyncMock(return_value=sent),
    )

    @asynccontextmanager
    async def fake_bot():
        yield bot

    monkeypatch.setattr("services.business_reply.telegram_bot", fake_bot)
    return bot


async def send(subscription, key=None, text="Synthetic reply", **kwargs):
    return await send_business_reply(
        1, subscription.chat_id, 1, text, key or str(uuid4()), **kwargs
    )


@pytest.mark.asyncio
async def test_success_uses_stored_destination_echo_dedup_and_does_not_read(reply_chat, sdk):
    key = str(uuid4())
    result = await send(reply_chat, key)
    assert result == {
        "status": "sent",
        "request_id": key,
        "message_id": 2,
        "reply_attached": True,
        "error_code": None,
        "error": None,
    }
    args = sdk.send_message.call_args.kwargs
    assert args["chat_id"] == 777 and args["chat_id"] != reply_chat.chat_id
    assert args["business_connection_id"] == "reply-connection"
    assert args["reply_parameters"].message_id == 1
    assert args["reply_parameters"].chat_id is None
    assert "parse_mode" not in args and "reply_to_message_id" not in args
    await business_message_handler(
        message_update(
            11, 2, connection="reply-connection", text="Synthetic reply", sender=123456789
        ),
        None,
    )
    assert await ChatMessage.filter(chat_id=reply_chat.chat_id, message_id=2).count() == 1
    await reply_chat.refresh_from_db()
    assert reply_chat.read_through_message_id == 0 and reply_chat.last_read_at is None
    assert await send(reply_chat, key) == result
    sdk.send_message.assert_awaited_once()
    row = await BusinessReplyAttempt.get(request_id=key)
    assert row.status == "sent" and "Synthetic reply" not in row.payload_hash


@pytest.mark.asyncio
async def test_same_key_concurrent_requests_send_only_once(reply_chat, sdk):
    original = sdk.send_message.return_value

    async def slow_send(**kwargs):
        await asyncio.sleep(0.02)
        return original

    sdk.send_message.side_effect = slow_send
    key = str(uuid4())
    results = await asyncio.gather(send(reply_chat, key), send(reply_chat, key))
    assert all(r["status"] in {"sent", "unknown"} for r in results)
    assert any(r["status"] == "sent" for r in results)
    sdk.send_message.assert_awaited_once()
    assert await BusinessReplyAttempt.filter(request_id=key).count() == 1


@pytest.mark.asyncio
async def test_payload_conflict_never_reuses_approval(reply_chat, sdk):
    key = str(uuid4())
    await send(reply_chat, key)
    with pytest.raises(BusinessReplyError) as error:
        await send(reply_chat, key, text="Different approved text")
    assert error.value.status_code == 409
    sdk.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_prior_result_accessible_after_disabled_disconnect_target_delete(reply_chat, sdk):
    key = str(uuid4())
    result = await send(reply_chat, key)
    reply_chat.capture_mode = "disabled"
    await reply_chat.save()
    await BusinessConnection.all().update(is_enabled=False)
    await ChatMessage.filter(chat_id=reply_chat.chat_id, message_id=1).delete()
    assert await send(reply_chat, key) == result
    with pytest.raises(BusinessReplyError):
        await send(reply_chat)
    sdk.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["disabled", "disconnected", "target", "forged", "group"])
async def test_local_access_failures_never_send_or_reserve(reply_chat, sdk, reason):
    if reason == "disabled":
        reply_chat.capture_mode = "disabled"
        await reply_chat.save()
    elif reason == "disconnected":
        await BusinessConnection.all().update(is_enabled=False)
    elif reason == "target":
        await ChatMessage.filter(chat_id=reply_chat.chat_id).delete()
    elif reason == "forged":
        await BusinessConnection.all().update(user_id=2)
    else:
        await Chat.filter(id=reply_chat.chat_id).update(
            chat_type="group", business_connection_id=None
        )
    with pytest.raises(BusinessReplyError):
        await send(reply_chat)
    assert await BusinessReplyAttempt.all().count() == 0
    sdk.get_business_connection.assert_not_awaited()
    sdk.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["rights", "owner", "id", "enabled", "verification"])
async def test_fresh_telegram_verification_fails_closed(reply_chat, sdk, reason):
    info = sdk.get_business_connection.return_value
    if reason == "rights":
        info.rights = None
    elif reason == "owner":
        info.user.id = 999
    elif reason == "id":
        info.id = "changed"
    elif reason == "enabled":
        info.is_enabled = False
    else:
        sdk.get_business_connection.side_effect = TimedOut("synthetic secret must not escape")
    result = await send(reply_chat)
    assert result["status"] == "failed"
    assert "secret" not in str(result)
    sdk.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status,code",
    [
        (TimedOut("do not disclose"), "unknown", "delivery_unknown"),
        (BadRequest("BUSINESS_PEER_USAGE_MISSING: private text"), "failed", "telegram_rejected"),
        (Forbidden("private text"), "failed", "telegram_forbidden"),
        (RetryAfter(10), "failed", "rate_limited"),
    ],
)
async def test_delivery_errors_are_sanitized_and_never_auto_retry(
    reply_chat, sdk, error, status, code
):
    sdk.send_message.side_effect = error
    key = str(uuid4())
    result = await send(reply_chat, key)
    assert result["status"] == status and result["error_code"] == code
    assert "private text" not in str(result) and "disclose" not in str(result)
    assert await send(reply_chat, key) == result
    sdk.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_is_reported_honestly(reply_chat, sdk):
    sdk.send_message.return_value.reply_to_message = None
    result = await send(reply_chat)
    assert result["status"] == "sent" and result["reply_attached"] is False


@pytest.mark.asyncio
async def test_crashed_reservation_never_expires_or_resends(reply_chat, sdk):
    import hashlib
    import json

    key = str(uuid4())
    digest = hashlib.sha256(
        json.dumps(
            [reply_chat.chat_id, 1, "Synthetic reply"], ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
    await BusinessReplyAttempt.create(
        user_id=1,
        chat_id=reply_chat.chat_id,
        request_id=key,
        target_message_id=1,
        payload_hash=digest,
        connection_id="reply-connection",
    )
    result = await send(reply_chat, key)
    assert result["status"] == "unknown" and result["error_code"] == "delivery_pending"
    sdk.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_connection_rotation_between_reservation_and_send_rejected(
    reply_chat, sdk, monkeypatch
):
    @asynccontextmanager
    async def rotating_bot():
        await BusinessConnection.all().update(connection_id="rotated")
        yield sdk

    monkeypatch.setattr("services.business_reply.telegram_bot", rotating_bot)
    result = await send(reply_chat)
    assert result["status"] == "failed" and result["error_code"] == "connection_changed"
    sdk.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_rest_reply_requires_write_scope_and_uses_shared_service(
    client, reply_chat, sdk, auth_user
):
    url = f"/api/chats/{reply_chat.chat_id}/messages/1/reply"
    payload = {"text": "Synthetic reply", "request_id": str(uuid4())}
    auth_user.scopes = ["mentions:read"]
    assert (await client.post(url, json=payload)).status_code == 403
    auth_user.scopes.append("mentions:write")
    response = await client.post(url, json=payload)
    assert response.status_code == 200 and response.json()["status"] == "sent"
    sdk.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_mcp_confirmation_write_gate_and_metadata(reply_chat, sdk, monkeypatch):
    from mcp_server import WRITE_TOOLS, create_mcp_server
    from services.security import TokenPayload

    principal = TokenPayload(user_id=1, scopes=["mentions:read", "mentions:write"])

    async def current():
        return principal

    monkeypatch.setattr("mcp_server._principal", current)
    server, _ = create_mcp_server()
    args = {
        "chat_id": reply_chat.chat_id,
        "message_id": 1,
        "text": "Synthetic reply",
        "request_id": str(uuid4()),
    }
    with pytest.raises(Exception, match="approval"):
        await server.call_tool("reply_to_chat_message", args)
    assert await BusinessReplyAttempt.all().count() == 0
    principal.scopes = ["mentions:read"]
    with pytest.raises(Exception, match="mentions:write"):
        await server.call_tool("reply_to_chat_message", {**args, "confirmed": True})
    principal.scopes.append("mentions:write")
    assert "sent" in str(
        await server.call_tool("reply_to_chat_message", {**args, "confirmed": True})
    )
    assert "reply_to_chat_message" in WRITE_TOOLS
    tool = next(t for t in await server.list_tools() if t.name == "reply_to_chat_message")
    assert tool.annotations.open_world_hint and not tool.annotations.read_only_hint
    assert tool.annotations.idempotent_hint


@pytest.mark.asyncio
async def test_readonly_status_never_creates_or_sends_and_retains_owner_access(
    client, reply_chat, sdk, auth_user
):
    key = str(uuid4())
    url = f"/api/chats/{reply_chat.chat_id}/reply-attempts/{key}"
    auth_user.scopes = ["mentions:read"]
    assert (await client.get(url)).status_code == 404
    assert await BusinessReplyAttempt.all().count() == 0
    sdk.send_message.assert_not_awaited()
    await send(reply_chat, key)
    reply_chat.capture_mode = "disabled"
    await reply_chat.save()
    await BusinessConnection.all().update(is_enabled=False)
    assert (await client.get(url)).json()["status"] == "sent"
    auth_user.user_id = 2
    assert (await client.get(url)).status_code == 404
    sdk.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_mcp_readonly_status_unknown_key_has_no_side_effects(reply_chat, sdk, monkeypatch):
    from mcp_server import create_mcp_server
    from services.security import TokenPayload

    async def current():
        return TokenPayload(user_id=1, scopes=["mentions:read"])

    monkeypatch.setattr("mcp_server._principal", current)
    server, _ = create_mcp_server()
    with pytest.raises(Exception, match="not found"):
        await server.call_tool(
            "get_chat_reply_status", {"chat_id": reply_chat.chat_id, "request_id": str(uuid4())}
        )
    assert await BusinessReplyAttempt.all().count() == 0
    sdk.get_business_connection.assert_not_awaited()
    sdk.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepted_delivery_with_capture_failure_is_unknown_and_cannot_resend(
    reply_chat, sdk, monkeypatch
):
    monkeypatch.setattr(
        ChatMessage, "get_or_create", AsyncMock(side_effect=RuntimeError("private database error"))
    )
    key = str(uuid4())
    result = await send(reply_chat, key)
    assert result["status"] == "unknown" and result["message_id"] == 2
    assert "private database" not in str(result)
    assert await send(reply_chat, key) == result
    sdk.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_same_uuid_peer_and_target_are_scoped_to_each_owner(reply_chat, sdk):
    key = str(uuid4())
    await send(reply_chat, key)
    connection = await BusinessConnection.create(
        user_id=2,
        tg_user_id=222,
        connection_id="second-connection",
        is_enabled=True,
        connected_at=datetime.now(UTC),
    )
    chat = await Chat.create(
        chat_type="private", telegram_chat_id=777, business_connection=connection
    )
    await UserChatSubscription.create(user_id=2, tg_user_id=222, chat=chat, capture_mode="full")
    await ChatMessage.create(
        chat=chat,
        message_id=1,
        from_user_id=777,
        text="Other owner incoming",
        message_date=datetime.now(UTC),
    )
    sdk.get_business_connection.return_value.id = connection.connection_id
    sdk.get_business_connection.return_value.user.id = 222
    result = await send_business_reply(2, chat.id, 1, "Other owner reply", key)
    assert result["status"] == "sent"
    assert await BusinessReplyAttempt.filter(request_id=key).count() == 2
    assert await ChatMessage.filter(message_id=2).count() == 2
    assert sdk.send_message.await_count == 2
    assert sdk.send_message.call_args.kwargs["business_connection_id"] == "second-connection"


@pytest.mark.asyncio
async def test_migration_preserves_existing_chats_and_reply_reservations_restart(tmp_path):
    module = importlib.import_module(
        "migrations.models.6_20261103180000_add_business_reply_attempts"
    )
    dialect = SimpleNamespace(capabilities=SimpleNamespace(dialect="sqlite"))
    path = tmp_path / "reply.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE chats (id INTEGER PRIMARY KEY, title TEXT)")
        db.execute("INSERT INTO chats VALUES (1,'Existing private')")
        db.executescript(await module.upgrade(dialect))
        db.execute(
            "INSERT INTO business_reply_attempts(user_id,request_id,chat_id,target_message_id,payload_hash,connection_id) VALUES(1,'key',1,1,'hash','conn')"
        )
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT title FROM chats").fetchone() == ("Existing private",)
        assert db.execute("SELECT status FROM business_reply_attempts").fetchone() == ("reserved",)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO business_reply_attempts(user_id,request_id,chat_id,target_message_id,payload_hash,connection_id) VALUES(1,'key',1,1,'hash','conn')"
            )
    with pytest.raises(RuntimeError, match="duplicate sends"):
        await module.downgrade(dialect)
