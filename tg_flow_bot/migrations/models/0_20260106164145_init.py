from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "chats" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "chat_type" VARCHAR(50) NOT NULL,
    "title" VARCHAR(255),
    "username" VARCHAR(255),
    "bot_added_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS "user_chat_subscriptions" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "user_id" BIGINT NOT NULL,
    "tg_user_id" BIGINT NOT NULL,
    "tg_username" VARCHAR(255),
    "subscribed_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "chat_id" BIGINT NOT NULL REFERENCES "chats" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_user_chat_s_user_id_3768d4" UNIQUE ("user_id", "chat_id")
);
CREATE TABLE IF NOT EXISTS "mentioned_messages" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "user_id" BIGINT NOT NULL,
    "message_id" BIGINT NOT NULL,
    "from_user_id" BIGINT NOT NULL,
    "from_username" VARCHAR(255),
    "text" TEXT NOT NULL,
    "message_date" TIMESTAMPTZ NOT NULL,
    "saved_at" TIMESTAMPTZ NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "chat_id" BIGINT NOT NULL REFERENCES "chats" ("id") ON DELETE CASCADE,
    "subscription_id" BIGINT REFERENCES "user_chat_subscriptions" ("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """
