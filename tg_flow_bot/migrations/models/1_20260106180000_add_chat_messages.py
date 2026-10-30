from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "chat_messages" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "message_id" BIGINT NOT NULL,
    "from_user_id" BIGINT NOT NULL,
    "from_username" VARCHAR(255),
    "text" TEXT,
    "message_date" TIMESTAMPTZ NOT NULL,
    "saved_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "chat_id" BIGINT NOT NULL REFERENCES "chats" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_chat_message_chat_id_9f05ac" UNIQUE ("chat_id", "message_id")
);
ALTER TABLE "mentioned_messages" ADD COLUMN IF NOT EXISTS "chat_message_id" BIGINT REFERENCES "chat_messages" ("id") ON DELETE SET NULL;
"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "mentioned_messages" DROP COLUMN IF EXISTS "chat_message_id";
DROP TABLE IF EXISTS "chat_messages";
"""
