from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user_chat_subscriptions"
        ADD COLUMN IF NOT EXISTS "capture_mode" VARCHAR(20) NOT NULL DEFAULT 'mentions';
        ALTER TABLE "user_chat_subscriptions"
        ADD COLUMN IF NOT EXISTS "capture_mode_changed_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "user_chat_subscriptions" DROP COLUMN IF EXISTS "capture_mode_changed_at";
        ALTER TABLE "user_chat_subscriptions" DROP COLUMN IF EXISTS "capture_mode";
    """
