from datetime import datetime
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models import MentionedMessage


@pytest.mark.asyncio
async def test_get_mentions_unauthorized(client_no_auth):
    r = await client_no_auth.get("/api/mentions/")
    assert r.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_mentions_empty(client):
    r = await client.get("/api/mentions/")
    assert r.status_code == HTTPStatus.OK
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_mentions_success(client, mentions):
    r = await client.get("/api/mentions/")

    assert r.status_code == HTTPStatus.OK
    data = r.json()
    assert len(data) == 5

    first = data[0]
    assert first["user_id"] == 1
    assert first["from_username"] == "sender"
    assert "t.me/c/" in first["link"]


@pytest.mark.asyncio
async def test_get_mentions_sorted_by_date(client, mentions):
    r = await client.get("/api/mentions/")

    assert r.status_code == HTTPStatus.OK
    dates = [datetime.fromisoformat(m["message_date"]) for m in r.json()]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_get_mentions_filter_by_chat(client, mentions, mentions_in_another_chat, chat):
    r = await client.get("/api/mentions/", params={"chat_id": chat.id})

    assert r.status_code == HTTPStatus.OK
    data = r.json()
    assert len(data) == 5
    assert all(m["chat_id"] == chat.id for m in data)


@pytest.mark.asyncio
async def test_get_mentions_pagination_limit(client, mentions):
    r = await client.get("/api/mentions/", params={"limit": 2})

    assert r.status_code == HTTPStatus.OK
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_get_mentions_pagination_offset(client, mentions):
    all_data = (await client.get("/api/mentions/")).json()
    offset_data = (await client.get("/api/mentions/", params={"offset": 2})).json()

    assert len(offset_data) == 3
    assert offset_data[0]["id"] == all_data[2]["id"]


@pytest.mark.asyncio
async def test_get_mentions_link_format(client, chat, subscription):
    await MentionedMessage.create(
        user_id=1,  # matches auth_user.user_id
        chat=chat,
        subscription=subscription,
        message_id=99999,
        from_user_id=111111,
        from_username="sender",
        text="@testuser check this",
        message_date=datetime.now(),
    )

    data = (await client.get("/api/mentions/")).json()

    assert len(data) == 1
    assert data[0]["link"] == "https://t.me/c/1234567890/99999"


@pytest.mark.asyncio
async def test_get_mentions_only_own_mentions(client, chat, subscription):
    # Different user's mention
    await MentionedMessage.create(
        user_id=999,
        chat=chat,
        subscription=None,
        message_id=8888,
        from_user_id=111111,
        from_username="sender",
        text="@otheruser hello",
        message_date=datetime.now(),
    )
    # Our user's mention (user_id=1 matches auth_user.user_id)
    await MentionedMessage.create(
        user_id=1,
        chat=chat,
        subscription=subscription,
        message_id=7777,
        from_user_id=111111,
        from_username="sender",
        text="@testuser hello",
        message_date=datetime.now(),
    )

    data = (await client.get("/api/mentions/")).json()

    assert len(data) == 1
    assert data[0]["user_id"] == 1
    assert data[0]["message_id"] == 7777


@pytest.mark.asyncio
async def test_get_mentions_invalid_limit(client):
    r = await client.get("/api/mentions/", params={"limit": 200})
    assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_mentions_invalid_offset(client):
    r = await client.get("/api/mentions/", params={"offset": -1})
    assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.fixture
async def mention_for_reply(db, chat, subscription):
    return await MentionedMessage.create(
        user_id=1,  # matches auth_user.user_id
        chat=chat,
        subscription=subscription,
        message_id=5555,
        from_user_id=111111,
        from_username="sender",
        text="@testuser please reply",
        message_date=datetime.now(),
    )


@pytest.fixture
async def archived_mention(db, chat, subscription):
    return await MentionedMessage.create(
        user_id=1,  # matches auth_user.user_id
        chat=chat,
        subscription=subscription,
        message_id=7777,
        from_user_id=111111,
        from_username="sender",
        text="@testuser archived message",
        message_date=datetime.now(),
        is_archived=True,
    )


@pytest.fixture
async def other_user_mention(db, chat):
    return await MentionedMessage.create(
        user_id=999,  # different user
        chat=chat,
        subscription=None,
        message_id=6666,
        from_user_id=111111,
        from_username="sender",
        text="@otheruser message",
        message_date=datetime.now(),
    )


@pytest.fixture
def mock_bot():
    mock_app = MagicMock()
    mock_message = MagicMock()
    mock_message.message_id = 12345
    mock_app.bot.send_message = AsyncMock(return_value=mock_message)
    return mock_app


@pytest.mark.asyncio
async def test_reply_to_mention_success(client, mention_for_reply, mock_bot):
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(
            f"/api/mentions/{mention_for_reply.id}/reply", json={"text": "Hello, this is my reply!"}
        )

    assert r.status_code == HTTPStatus.OK
    data = r.json()
    assert data["success"] is True
    assert data["message_id"] == 12345
    assert data["error"] is None

    # Verify bot was called correctly
    mock_bot.bot.send_message.assert_called_once_with(
        chat_id=mention_for_reply.chat_id,
        text="Hello, this is my reply!",
        reply_to_message_id=mention_for_reply.message_id,
    )

    await mention_for_reply.refresh_from_db()
    assert mention_for_reply.is_archived is True


@pytest.mark.asyncio
async def test_reply_to_mention_strips_whitespace(client, mention_for_reply, mock_bot):
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(
            f"/api/mentions/{mention_for_reply.id}/reply", json={"text": "  trimmed text  "}
        )

    assert r.status_code == HTTPStatus.OK
    mock_bot.bot.send_message.assert_called_once()
    call_args = mock_bot.bot.send_message.call_args
    assert call_args.kwargs["text"] == "trimmed text"


@pytest.mark.asyncio
async def test_reply_to_mention_not_found(client, mock_bot):
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post("/api/mentions/999999/reply", json={"text": "Hello"})

    assert r.status_code == HTTPStatus.NOT_FOUND
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reply_to_other_users_mention_is_not_disclosed(client, other_user_mention, mock_bot):
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(
            f"/api/mentions/{other_user_mention.id}/reply", json={"text": "Hello"}
        )

    assert r.status_code == HTTPStatus.NOT_FOUND
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reply_to_mention_empty_text(client, mention_for_reply, mock_bot):
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(f"/api/mentions/{mention_for_reply.id}/reply", json={"text": ""})

    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert "empty" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reply_to_mention_whitespace_only(client, mention_for_reply, mock_bot):
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(f"/api/mentions/{mention_for_reply.id}/reply", json={"text": "   "})

    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert "empty" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reply_to_mention_text_too_long(client, mention_for_reply, mock_bot):
    long_text = "x" * 4097
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(
            f"/api/mentions/{mention_for_reply.id}/reply", json={"text": long_text}
        )

    assert r.status_code == HTTPStatus.BAD_REQUEST
    assert "too long" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reply_to_mention_max_length_ok(client, mention_for_reply, mock_bot):
    max_text = "x" * 4096
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(
            f"/api/mentions/{mention_for_reply.id}/reply", json={"text": max_text}
        )

    assert r.status_code == HTTPStatus.OK
    assert r.json()["success"] is True


@pytest.mark.asyncio
async def test_reply_to_mention_bot_error(client, mention_for_reply):
    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock(side_effect=Exception("Telegram API error"))

    with patch("main.get_bot", return_value=mock_app):
        r = await client.post(f"/api/mentions/{mention_for_reply.id}/reply", json={"text": "Hello"})

    assert r.status_code == HTTPStatus.OK
    data = r.json()
    assert data["success"] is False
    assert data["error"] == "Telegram could not send the reply"


@pytest.mark.asyncio
async def test_reply_to_mention_unauthorized(client_no_auth, mention_for_reply):
    r = await client_no_auth.post(
        f"/api/mentions/{mention_for_reply.id}/reply", json={"text": "Hello"}
    )
    assert r.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_reply_to_mention_missing_text_field(client, mention_for_reply, mock_bot):
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(f"/api/mentions/{mention_for_reply.id}/reply", json={})

    assert r.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_mentions_includes_archived_by_default(
    client, mention_for_reply, archived_mention
):
    r = await client.get("/api/mentions/")

    assert r.status_code == HTTPStatus.OK
    data = r.json()
    assert len(data) == 2
    ids = {item["id"] for item in data}
    assert mention_for_reply.id in ids
    assert archived_mention.id in ids


@pytest.mark.asyncio
async def test_reply_to_archived_mention_not_found(client, archived_mention, mock_bot):
    with patch("main.get_bot", return_value=mock_bot):
        r = await client.post(f"/api/mentions/{archived_mention.id}/reply", json={"text": "Hello"})

    assert r.status_code == HTTPStatus.NOT_FOUND
    assert "not found" in r.json()["detail"].lower()
