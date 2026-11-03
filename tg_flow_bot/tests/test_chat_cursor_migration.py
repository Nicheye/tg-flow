"""Exercise additive SQLite cursor migration against an existing data file."""

import importlib
import sqlite3
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_sqlite_cursor_migration_preserves_legacy_rows_and_persists(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    migration = importlib.import_module("migrations.models.4_20261102120000_add_chat_read_cursor")
    dialect = SimpleNamespace(capabilities=SimpleNamespace(dialect="sqlite"))
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE user_chat_subscriptions
                (id INTEGER PRIMARY KEY, user_id BIGINT, chat_id BIGINT, capture_mode TEXT);
            CREATE TABLE mentioned_messages (id INTEGER PRIMARY KEY, text TEXT, is_archived BOOL);
            INSERT INTO user_chat_subscriptions VALUES(1, 99, -100, 'disabled');
            INSERT INTO mentioned_messages VALUES(1, 'historical mention', TRUE);
        """)
        db.executescript(await migration.upgrade(dialect))
        row = db.execute(
            "SELECT user_id, chat_id, capture_mode, read_through_message_id, last_read_at FROM user_chat_subscriptions"
        ).fetchone()
        assert row == (99, -100, "disabled", 0, None)
        db.execute(
            "UPDATE user_chat_subscriptions SET read_through_message_id=50, last_read_at='2026-11-02T12:00:00+00:00'"
        )
    # Reopening the DB simulates loss of all in-memory process/user context.
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT read_through_message_id, last_read_at FROM user_chat_subscriptions"
        ).fetchone() == (50, "2026-11-02T12:00:00+00:00")
        assert db.execute("SELECT text, is_archived FROM mentioned_messages").fetchone() == (
            "historical mention",
            1,
        )
