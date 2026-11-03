"""Read checkpoints acknowledge only observed snapshots and never Telegram receipts."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from models import ChatMessage, UserChatSubscription
from services.chat_unread import ChatUnreadError, list_unread, mark_read


@pytest.fixture
async def full_subscription(subscription):
    subscription.capture_mode = "full"
    await subscription.save()
    return subscription


async def messages(subscription, *ids):
    await ChatMessage.bulk_create(
        [
            ChatMessage(
                chat_id=subscription.chat_id,
                message_id=message_id,
                from_user_id=10,
                text=f"message {message_id}",
                message_date=datetime.now(UTC),
            )
            for message_id in ids
        ]
    )


@pytest.mark.asyncio
async def test_existing_full_history_initially_unread_and_reads_do_not_ack(
    client, full_subscription
):
    s = full_subscription
    await messages(s, 30, 10, 20)
    response = await client.get(f"/api/chats/{s.chat_id}/unread")
    assert response.status_code == 200
    result = response.json()
    assert [row["message_id"] for row in result["messages"]] == [10, 20, 30]
    assert result["snapshot_through_message_id"] == 30
    assert result["read_through_message_id"] == 0
    assert result["unread_count"] == 3
    assert not result["has_more"]
    assert result["next_after_message_id"] is None
    await client.get(f"/api/chats/{s.chat_id}/messages")
    await s.refresh_from_db()
    assert s.read_through_message_id == 0
    assert s.last_read_at is None
    listed = await client.get("/api/chats/")
    assert listed.json()[0]["unread_count"] == 3


@pytest.mark.asyncio
async def test_empty_snapshot_never_marks(full_subscription):
    page = await list_unread(1, full_subscription.chat_id)
    assert page["messages"] == []
    assert page["snapshot_through_message_id"] == 0
    assert page["read_through_message_id"] == 0
    assert page["unread_count"] == 0


@pytest.mark.asyncio
async def test_paginate_over_200_snapshot_no_gaps_new_arrival_stays_unread(full_subscription):
    s = full_subscription
    await messages(s, *range(1, 452))
    page = await list_unread(1, s.chat_id, limit=200)
    assert page["snapshot_through_message_id"] == 451
    assert len(page["messages"]) == 200
    await messages(s, 452)
    seen = [m.message_id for m in page["messages"]]
    while page["has_more"]:
        page = await list_unread(
            1,
            s.chat_id,
            limit=200,
            after_message_id=page["next_after_message_id"],
            through_message_id=page["snapshot_through_message_id"],
            capture_mode_changed_at=page["capture_mode_changed_at"],
        )
        seen += [m.message_id for m in page["messages"]]
    assert seen == list(range(1, 452))
    # Reading/summarizing alone does not move state, so an unsuccessful summary retries all.
    assert (await list_unread(1, s.chat_id))["read_through_message_id"] == 0
    await mark_read(1, s.chat_id, 451, s.capture_mode_changed_at)
    remaining = await list_unread(1, s.chat_id)
    assert [m.message_id for m in remaining["messages"]] == [452]


@pytest.mark.asyncio
async def test_mark_observed_target_preserves_later_arrivals_and_smaller_repeats(
    client, full_subscription
):
    s = full_subscription
    await messages(s, 10, 20)
    initial = (await client.get(f"/api/chats/{s.chat_id}/unread")).json()
    await messages(s, 30)
    response = await client.post(
        f"/api/chats/{s.chat_id}/read",
        json={
            "through_message_id": initial["snapshot_through_message_id"],
            "capture_mode_changed_at": initial["capture_mode_changed_at"],
        },
    )
    assert response.status_code == 200
    assert response.json()["read_through_message_id"] == 20
    assert response.json()["unread_count"] == 1
    assert response.json()["last_read_at"]
    await s.refresh_from_db()
    stamp = s.last_read_at
    await mark_read(1, s.chat_id, 10, s.capture_mode_changed_at)
    await mark_read(1, s.chat_id, 20, s.capture_mode_changed_at)
    await s.refresh_from_db()
    assert s.read_through_message_id == 20
    assert s.last_read_at == stamp


@pytest.mark.asyncio
async def test_concurrent_markers_monotonic(full_subscription):
    s = full_subscription
    await messages(s, *range(1, 21))
    await asyncio.gather(
        *[
            mark_read(1, s.chat_id, target, s.capture_mode_changed_at)
            for target in [15, 5, 20, 10, 1]
        ]
    )
    await s.refresh_from_db()
    assert s.read_through_message_id == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["mentions", "disabled"])
async def test_nonfull_mode_rejects_reads_and_marks_and_lists_zero(client, subscription, mode):
    s = subscription
    s.capture_mode = mode
    s.read_through_message_id = 5
    await s.save()
    await messages(s, 10)
    assert (await client.get(f"/api/chats/{s.chat_id}/unread")).status_code == 403
    assert (
        await client.post(
            f"/api/chats/{s.chat_id}/read",
            json={
                "through_message_id": 10,
                "capture_mode_changed_at": s.capture_mode_changed_at.isoformat(),
            },
        )
    ).status_code == 403
    row = (await client.get("/api/chats/")).json()[0]
    assert row["unread_count"] == 0
    assert row["read_through_message_id"] == 5


@pytest.mark.asyncio
async def test_other_owner_and_other_chat_cannot_ack(client, full_subscription, another_chat):
    s = full_subscription
    await messages(s, 10)
    other = await UserChatSubscription.create(
        user_id=999, tg_user_id=999, chat=another_chat, capture_mode="full"
    )
    await messages(other, 200)
    assert (await client.get(f"/api/chats/{other.chat_id}/unread")).status_code == 404
    assert (
        await client.post(
            f"/api/chats/{other.chat_id}/read",
            json={
                "through_message_id": 200,
                "capture_mode_changed_at": other.capture_mode_changed_at.isoformat(),
            },
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/chats/{s.chat_id}/read",
            json={
                "through_message_id": 200,
                "capture_mode_changed_at": s.capture_mode_changed_at.isoformat(),
            },
        )
    ).status_code == 422
    await s.refresh_from_db()
    assert s.read_through_message_id == 0


@pytest.mark.asyncio
async def test_scopes_and_auth_required(client, client_no_auth, auth_user, full_subscription):
    s = full_subscription
    await messages(s, 10)
    body = {
        "through_message_id": 10,
        "capture_mode_changed_at": s.capture_mode_changed_at.isoformat(),
    }
    assert (await client_no_auth.get(f"/api/chats/{s.chat_id}/unread")).status_code == 401
    assert (await client_no_auth.post(f"/api/chats/{s.chat_id}/read", json=body)).status_code == 401
    auth_user.scopes = ["mentions:read"]
    assert (await client.post(f"/api/chats/{s.chat_id}/read", json=body)).status_code == 403
    auth_user.scopes = ["mentions:write"]
    assert (await client.get(f"/api/chats/{s.chat_id}/unread")).status_code == 403


@pytest.mark.asyncio
async def test_invalid_targets_and_continuation_boundaries(client, full_subscription):
    s = full_subscription
    await messages(s, 10)
    old = await ChatMessage.create(
        chat_id=s.chat_id,
        message_id=5,
        from_user_id=9,
        text="before mode",
        message_date=datetime.now(UTC),
    )
    old.saved_at = s.capture_mode_changed_at - timedelta(seconds=1)
    await old.save()
    generation = s.capture_mode_changed_at.isoformat()
    for target in (0, -1, 5, 999):
        response = await client.post(
            f"/api/chats/{s.chat_id}/read",
            json={
                "through_message_id": target,
                "capture_mode_changed_at": generation,
            },
        )
        assert response.status_code == 422
    for params in (
        {"after_message_id": 10},
        {"through_message_id": 10},
        {"limit": 201},
        {"through_message_id": 999, "capture_mode_changed_at": generation},
        {"through_message_id": 10, "after_message_id": 11, "capture_mode_changed_at": generation},
    ):
        assert (
            await client.get(f"/api/chats/{s.chat_id}/unread", params=params)
        ).status_code == 422


@pytest.mark.asyncio
async def test_mode_changes_reject_snapshot_and_preserve_cursor(client, full_subscription):
    s = full_subscription
    await messages(s, 10, 20)
    await mark_read(1, s.chat_id, 10, s.capture_mode_changed_at)
    generation = s.capture_mode_changed_at
    await client.patch(f"/api/chats/{s.chat_id}/mode", json={"capture_mode": "disabled"})
    await client.patch(f"/api/chats/{s.chat_id}/mode", json={"capture_mode": "full"})
    await s.refresh_from_db()
    assert s.read_through_message_id == 10
    assert s.last_read_at
    for operation in (
        list_unread(
            1,
            s.chat_id,
            after_message_id=10,
            through_message_id=20,
            capture_mode_changed_at=generation,
        ),
        mark_read(1, s.chat_id, 20, generation),
    ):
        with pytest.raises(ChatUnreadError) as error:
            await operation
        assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_mode_change_racing_atomic_update_cannot_mark(full_subscription, monkeypatch):
    from tortoise.queryset import QuerySet

    s = full_subscription
    await messages(s, 10)
    original = QuerySet.update

    def race(query, **kwargs):
        update = original(query, **kwargs)

        async def execute():
            await original(
                UserChatSubscription.filter(id=s.id),
                capture_mode="disabled",
                capture_mode_changed_at=datetime.now(UTC),
            )
            return await update

        return execute()

    monkeypatch.setattr(QuerySet, "update", race)
    with pytest.raises(ChatUnreadError):
        await mark_read(1, s.chat_id, 10, s.capture_mode_changed_at)
    await s.refresh_from_db()
    assert s.read_through_message_id == 0
    assert s.last_read_at is None


@pytest.mark.asyncio
async def test_edit_already_read_id_stays_read(full_subscription, make_update, mock_context):
    from bot.parser import message_handler

    s = full_subscription
    await messages(s, 10)
    await mark_read(1, s.chat_id, 10, s.capture_mode_changed_at)
    update = make_update("edited after read")
    update.effective_message.message_id = 10
    await message_handler(update, mock_context)
    page = await list_unread(1, s.chat_id)
    assert page["messages"] == []
    assert page["unread_count"] == 0


@pytest.mark.asyncio
async def test_mcp_unread_and_mark_share_state_and_scope(full_subscription, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    from mcp_server import create_mcp_server
    from services.security import TokenPayload

    s = full_subscription
    await messages(s, 10, 20, 30)
    principal = TokenPayload(user_id=1, scopes=["mentions:read"])

    async def current():
        return principal

    monkeypatch.setattr("mcp_server._principal", current)
    server, _ = create_mcp_server()
    page_result = await server.call_tool(
        "list_unread_chat_messages", {"chat_id": s.chat_id, "limit": 2}
    )
    # Assert structured output from the installed MCP server API.
    page = page_result.structured_content or json.loads(page_result.content[0].text)
    assert [m["message_id"] for m in page["messages"]] == [10, 20]
    assert page["has_more"]
    assert page["snapshot_through_message_id"] == 30
    body = {
        "chat_id": s.chat_id,
        "through_message_id": 30,
        "capture_mode_changed_at": page["capture_mode_changed_at"],
    }
    with pytest.raises(ToolError, match="mentions:write"):
        await server.call_tool("mark_chat_read", body)
    await s.refresh_from_db()
    assert s.read_through_message_id == 0
    principal.scopes.append("mentions:write")
    next_result = await server.call_tool(
        "list_unread_chat_messages",
        {
            "chat_id": s.chat_id,
            "after_message_id": page["next_after_message_id"],
            "through_message_id": 30,
            "capture_mode_changed_at": page["capture_mode_changed_at"],
        },
    )
    assert [
        m["message_id"]
        for m in (next_result.structured_content or json.loads(next_result.content[0].text))[
            "messages"
        ]
    ] == [30]
    await messages(s, 40)
    result = await server.call_tool("mark_chat_read", body)
    marked = result.structured_content or json.loads(result.content[0].text)
    assert marked["read_through_message_id"] == 30
    assert marked["unread_count"] == 1
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert tools["list_unread_chat_messages"].annotations.read_only_hint
    assert not tools["mark_chat_read"].annotations.read_only_hint
    assert not tools["mark_chat_read"].annotations.destructive_hint
    assert tools["mark_chat_read"].annotations.idempotent_hint
