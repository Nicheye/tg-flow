from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    sqlite = db.capabilities.dialect == "sqlite"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if sqlite else "BIGSERIAL PRIMARY KEY"
    timestamp = "TIMESTAMP" if sqlite else "TIMESTAMPTZ"
    json = "JSON" if sqlite else "JSONB"
    return f"""
        CREATE TABLE IF NOT EXISTS "business_connections" (
            "id" {pk},
            "tg_user_id" BIGINT NOT NULL UNIQUE,
            "user_id" BIGINT NOT NULL,
            "connection_id" VARCHAR(255) NOT NULL UNIQUE,
            "is_enabled" BOOLEAN NOT NULL DEFAULT FALSE,
            "last_update_id" BIGINT NOT NULL DEFAULT -1,
            "retired_connection_ids" {json} NOT NULL DEFAULT '[]',
            "connected_at" {timestamp} NOT NULL,
            "updated_at" {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        ALTER TABLE "chats" ADD COLUMN "business_connection_id" BIGINT
            REFERENCES "business_connections" ("id") ON DELETE RESTRICT;
        ALTER TABLE "chats" ADD COLUMN "telegram_chat_id" BIGINT;
        CREATE UNIQUE INDEX "uid_business_chat_peer" ON "chats"
            ("business_connection_id", "telegram_chat_id");
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    # Private rows use internal IDs. Removing their ownership metadata would
    # make them unsafe to interpret; restore a backup instead of downgrading.
    raise RuntimeError(
        "Business ownership migration cannot be downgraded; restore a verified backup"
    )
