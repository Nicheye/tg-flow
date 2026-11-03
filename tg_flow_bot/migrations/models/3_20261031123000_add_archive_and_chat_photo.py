from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "mentioned_messages"
        ADD COLUMN IF NOT EXISTS "is_archived" BOOL NOT NULL DEFAULT FALSE;
        ALTER TABLE "chats"
        ADD COLUMN IF NOT EXISTS "photo_file_id" VARCHAR(255);
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "chats" DROP COLUMN IF EXISTS "photo_file_id";
        ALTER TABLE "mentioned_messages" DROP COLUMN IF EXISTS "is_archived";
    """
