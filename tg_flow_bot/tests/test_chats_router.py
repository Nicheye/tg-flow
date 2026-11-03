from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest

from models import ChatMessage, UserChatSubscription


@pytest.mark.asyncio
async def test_list_chats_can_be_empty(client):
    response = await client.get("/api/chats/")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_chats_returns_capture_mode(client, subscription):
    response = await client.get("/api/chats/")

    assert response.status_code == HTTPStatus.OK
    assert response.json()[0]["capture_mode"] == "mentions"


@pytest.mark.asyncio
async def test_list_chats_returns_only_current_users_subscriptions(client, chat, subscription):
    await UserChatSubscription.create(
        user_id=999,
        chat=chat,
        tg_user_id=999,
        tg_username="other",
        capture_mode="full",
    )

    response = await client.get("/api/chats/")

    assert response.status_code == HTTPStatus.OK
    assert [item["id"] for item in response.json()] == [subscription.id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/chats/", "get"),
        ("/api/chats/-1001234567890/mode", "patch"),
        ("/api/chats/-1001234567890/messages", "get"),
    ],
)
async def test_chat_endpoints_require_authentication(client_no_auth, path, method):
    kwargs = {"json": {"capture_mode": "full"}} if method == "patch" else {}
    response = await getattr(client_no_auth, method)(path, **kwargs)

    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_full_feed_requires_full_mode(client, subscription):
    response = await client.get(f"/api/chats/{subscription.chat_id}/messages")

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_full_feed_can_be_empty(client, subscription):
    subscription.capture_mode = "full"
    await subscription.save(update_fields=("capture_mode",))

    response = await client.get(f"/api/chats/{subscription.chat_id}/messages")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


@pytest.mark.asyncio
async def test_update_mode_rejects_unknown_mode(client, subscription):
    response = await client.patch(
        f"/api/chats/{subscription.chat_id}/mode",
        json={"capture_mode": "unexpected"},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    await subscription.refresh_from_db()
    assert subscription.capture_mode == "mentions"


@pytest.mark.asyncio
async def test_update_mode_requires_owned_subscription(client, chat):
    response = await client.patch(
        f"/api/chats/{chat.id}/mode",
        json={"capture_mode": "full"},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_updating_to_same_mode_keeps_cutoff(client, subscription):
    original_timestamp = subscription.capture_mode_changed_at

    response = await client.patch(
        f"/api/chats/{subscription.chat_id}/mode",
        json={"capture_mode": "mentions"},
    )

    assert response.status_code == HTTPStatus.OK
    assert datetime.fromisoformat(response.json()["capture_mode_changed_at"]) == original_timestamp


@pytest.mark.asyncio
async def test_switch_to_full_and_read_new_messages(client, subscription):
    old_message = await ChatMessage.create(
        chat_id=subscription.chat_id,
        message_id=1,
        from_user_id=10,
        text="old",
        message_date=datetime.now(UTC) - timedelta(seconds=1),
    )
    response = await client.patch(
        f"/api/chats/{subscription.chat_id}/mode",
        json={"capture_mode": "full"},
    )
    assert response.status_code == HTTPStatus.OK

    await subscription.refresh_from_db()
    new_message = await ChatMessage.create(
        chat_id=subscription.chat_id,
        message_id=2,
        from_user_id=10,
        text="new",
        message_date=datetime.now(UTC),
    )

    feed = await client.get(f"/api/chats/{subscription.chat_id}/messages")

    assert feed.status_code == HTTPStatus.OK
    assert [message["id"] for message in feed.json()] == [new_message.id]
    assert old_message.id != new_message.id


@pytest.mark.asyncio
async def test_cannot_read_another_users_full_feed(client, chat):
    response = await client.get(f"/api/chats/{chat.id}/messages")

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_full_feed_is_ordered_and_supports_cursor_pagination(client, subscription):
    subscription.capture_mode = "full"
    await subscription.save(update_fields=("capture_mode",))
    for message_id in (10, 20, 30):
        await ChatMessage.create(
            chat_id=subscription.chat_id,
            message_id=message_id,
            from_user_id=10,
            text=str(message_id),
            message_date=datetime.now(UTC),
        )

    latest = await client.get(
        f"/api/chats/{subscription.chat_id}/messages",
        params={"limit": 2},
    )
    previous = await client.get(
        f"/api/chats/{subscription.chat_id}/messages",
        params={"before_message_id": 20},
    )

    assert [item["message_id"] for item in latest.json()] == [20, 30]
    assert [item["message_id"] for item in previous.json()] == [10]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 201])
async def test_full_feed_rejects_invalid_limits(client, subscription, limit):
    subscription.capture_mode = "full"
    await subscription.save(update_fields=("capture_mode",))

    response = await client.get(
        f"/api/chats/{subscription.chat_id}/messages",
        params={"limit": limit},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_switching_back_to_mentions_closes_full_feed(client, subscription):
    subscription.capture_mode = "full"
    await subscription.save(update_fields=("capture_mode",))

    changed = await client.patch(
        f"/api/chats/{subscription.chat_id}/mode",
        json={"capture_mode": "mentions"},
    )
    feed = await client.get(f"/api/chats/{subscription.chat_id}/messages")

    assert changed.status_code == HTTPStatus.OK
    assert changed.json()["capture_mode"] == "mentions"
    assert feed.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.asyncio
async def test_disable_preserves_data_and_remains_listed(client, subscription, mentions):
    changed = await client.patch(
        f"/api/chats/{subscription.chat_id}/mode", json={"capture_mode": "disabled"}
    )
    assert changed.status_code == 200
    await subscription.refresh_from_db()
    assert subscription.capture_mode == "disabled"
    from models import MentionedMessage

    assert await MentionedMessage.filter(subscription=subscription).count() == len(mentions)
    listed = await client.get("/api/chats/")
    assert listed.json()[0]["capture_mode"] == "disabled"
    assert (await client.get(f"/api/chats/{subscription.chat_id}/messages")).status_code == 403
    changed = await client.patch(
        f"/api/chats/{subscription.chat_id}/mode", json={"capture_mode": "full"}
    )
    assert changed.status_code == 200


@pytest.mark.asyncio
async def test_disable_cannot_change_other_users_subscription(client, chat):
    other = await UserChatSubscription.create(
        user_id=999, tg_user_id=999, chat=chat, capture_mode="full"
    )
    changed = await client.patch(f"/api/chats/{chat.id}/mode", json={"capture_mode": "disabled"})
    assert changed.status_code == 404
    await other.refresh_from_db()
    assert other.capture_mode == "full"


@pytest.mark.asyncio
async def test_read_scope_cannot_disable(client, auth_user, subscription):
    auth_user.scopes = ["mentions:read"]
    changed = await client.patch(
        f"/api/chats/{subscription.chat_id}/mode", json={"capture_mode": "disabled"}
    )
    assert changed.status_code == 403
    await subscription.refresh_from_db()
    assert subscription.capture_mode == "mentions"
