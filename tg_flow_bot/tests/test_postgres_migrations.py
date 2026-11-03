"""Opt-in regression against a dedicated, initially empty PostgreSQL database."""

import asyncio
import copy
import importlib
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from aerich import Command
from tortoise import Tortoise

from database import TORTOISE_ORM


@pytest.mark.skipif(
    not os.environ.get("TG_FLOW_MIGRATION_TEST_URL"),
    reason="Requires a dedicated TG_FLOW_MIGRATION_TEST_URL PostgreSQL database",
)
async def test_postgres_migrations_create_every_model_column(monkeypatch):
    url = os.environ["TG_FLOW_MIGRATION_TEST_URL"]
    assert urlsplit(url).path.startswith("/tg_flow_migration_"), "Use a dedicated test database"
    config = copy.deepcopy(TORTOISE_ORM)
    config["connections"]["default"] = url
    command = Command(tortoise_config=config, app="models", location="./migrations")
    try:
        await command.init()
        await command.upgrade()
        connection = Tortoise.get_connection("default")
        rows = await connection.execute_query_dict(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        )
        columns = {}
        for row in rows:
            columns.setdefault(row["table_name"], set()).add(row["column_name"])
        missing = {}
        for model in Tortoise.apps["models"].values():
            table = model._meta.db_table
            absent = set(model._meta.fields_db_projection.values()) - columns.get(table, set())
            if absent:
                missing[table] = sorted(absent)
        assert missing == {}, f"Checked-in migrations omit model columns: {missing}"
        assert await command.upgrade() == [], "Migration replay should be a no-op"

        # Legacy installations may already have these columns from manual changes.
        # Replaying the additive SQL must preserve archived state and cached photos.
        await connection.execute_script("""
            INSERT INTO chats (id, chat_type, photo_file_id)
            VALUES (-12345, 'supergroup', 'fixture-photo') ON CONFLICT (id) DO NOTHING;
            INSERT INTO mentioned_messages
                (id, user_id, chat_id, message_id, from_user_id, text, message_date, is_archived)
            VALUES (12345, 1, -12345, 1, 1, 'fixture mention', NOW(), TRUE)
            ON CONFLICT (id) DO NOTHING;
        """)
        migration = importlib.import_module(
            "migrations.models.3_20261031123000_add_archive_and_chat_photo"
        )
        await connection.execute_script(await migration.upgrade(connection))
        rows = await connection.execute_query_dict(
            "SELECT is_archived, photo_file_id FROM mentioned_messages "
            "JOIN chats ON chats.id = mentioned_messages.chat_id "
            "WHERE mentioned_messages.id = 12345"
        )
        assert rows == [{"is_archived": True, "photo_file_id": "fixture-photo"}]

        # Upgrade legacy cursor-free subscriptions without losing modes/history.
        # The database is isolated and disposable by the test's URL contract.
        await connection.execute_script("""
            INSERT INTO user_chat_subscriptions
                (id, user_id, chat_id, tg_user_id, capture_mode)
            VALUES (12345, 7, -12345, 77, 'full') ON CONFLICT (id) DO NOTHING;
            UPDATE user_chat_subscriptions SET read_through_message_id = 42,
                last_read_at = NOW() WHERE id = 12345;
        """)
        cursor_migration = importlib.import_module(
            "migrations.models.4_20261102120000_add_chat_read_cursor"
        )
        await connection.execute_script(await cursor_migration.upgrade(connection))
        row = (
            await connection.execute_query_dict(
                "SELECT user_id, capture_mode, read_through_message_id, last_read_at "
                "FROM user_chat_subscriptions WHERE id = 12345"
            )
        )[0]
        assert row["user_id"] == 7 and row["capture_mode"] == "full"
        assert row["read_through_message_id"] == 42 and row["last_read_at"] is not None
        await connection.execute_script(await cursor_migration.downgrade(connection))
        await connection.execute_script(await cursor_migration.upgrade(connection))
        row = (
            await connection.execute_query_dict(
                "SELECT user_id, capture_mode, read_through_message_id, last_read_at "
                "FROM user_chat_subscriptions WHERE id = 12345"
            )
        )[0]
        assert row == {
            "user_id": 7,
            "capture_mode": "full",
            "read_through_message_id": 0,
            "last_read_at": None,
        }
        assert (
            await connection.execute_query_dict(
                "SELECT text, is_archived FROM mentioned_messages WHERE id = 12345"
            )
        ) == [{"text": "fixture mention", "is_archived": True}]

        # Exercise the real PostgreSQL unique reservation and owner-row locking,
        # not merely the more permissive in-memory SQLite test implementation.
        from models import (
            BusinessConnection,
            BusinessReplyAttempt,
            Chat,
            ChatMessage,
            UserChatSubscription,
        )
        from services.business_reply import send_business_reply

        owner = await BusinessConnection.create(
            user_id=77,
            tg_user_id=77777,
            connection_id="pg-reply-connection",
            is_enabled=True,
            connected_at=datetime.now(UTC),
        )
        chat = await Chat.create(
            chat_type="private", telegram_chat_id=88888, business_connection=owner
        )
        await UserChatSubscription.create(
            user_id=77, tg_user_id=77777, chat=chat, capture_mode="full"
        )
        await ChatMessage.create(
            chat=chat,
            message_id=1,
            from_user_id=88888,
            text="Synthetic PG incoming",
            message_date=datetime.now(UTC),
        )
        info = SimpleNamespace(
            id=owner.connection_id,
            is_enabled=True,
            user=SimpleNamespace(id=77777, is_bot=False, username=None),
            rights=SimpleNamespace(can_reply=True),
        )
        sent = SimpleNamespace(
            message_id=2,
            text="Synthetic PG reply",
            date=datetime.now(UTC),
            reply_to_message=SimpleNamespace(message_id=1),
        )

        async def slow_send(**kwargs):
            await asyncio.sleep(0.03)
            return sent

        bot = SimpleNamespace(
            get_business_connection=AsyncMock(return_value=info),
            send_message=AsyncMock(side_effect=slow_send),
        )

        @asynccontextmanager
        async def fake_bot():
            yield bot

        monkeypatch.setattr("services.business_reply.telegram_bot", fake_bot)
        key = str(uuid4())
        result = await asyncio.gather(
            *[send_business_reply(77, chat.id, 1, "Synthetic PG reply", key) for _ in range(2)]
        )
        assert any(r["status"] == "sent" for r in result)
        bot.send_message.assert_awaited_once()
        assert await BusinessReplyAttempt.filter(user_id=77, request_id=key).count() == 1

        # Cancel while delivery is in progress, then simulate a process restart.
        # The reservation must have committed before the send transaction began.
        crash_key = str(uuid4())
        bot.send_message.side_effect = asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await send_business_reply(77, chat.id, 1, "Synthetic crash attempt", crash_key)
        assert (
            await BusinessReplyAttempt.get(user_id=77, request_id=crash_key)
        ).status == "reserved"
        await Tortoise.close_connections()
        await Tortoise.init(config=config)
        status = await send_business_reply(77, chat.id, 1, "Synthetic crash attempt", crash_key)
        assert status["status"] == "unknown" and status["error_code"] == "delivery_pending"
        assert bot.send_message.await_count == 2
    finally:
        await Tortoise.close_connections()
