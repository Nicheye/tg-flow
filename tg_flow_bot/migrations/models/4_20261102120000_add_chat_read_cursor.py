from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    # SQLite supports the same additive columns, but not IF NOT EXISTS.
    if db.capabilities.dialect == "sqlite":
        return """
            ALTER TABLE "user_chat_subscriptions" ADD COLUMN "read_through_message_id" BIGINT NOT NULL DEFAULT 0;
            ALTER TABLE "user_chat_subscriptions" ADD COLUMN "last_read_at" TIMESTAMP;
        """
    return """
        ALTER TABLE "user_chat_subscriptions" ADD COLUMN IF NOT EXISTS "read_through_message_id" BIGINT NOT NULL DEFAULT 0;
        ALTER TABLE "user_chat_subscriptions" ADD COLUMN IF NOT EXISTS "last_read_at" TIMESTAMPTZ;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user_chat_subscriptions" DROP COLUMN "last_read_at";
        ALTER TABLE "user_chat_subscriptions" DROP COLUMN "read_through_message_id";
    """
