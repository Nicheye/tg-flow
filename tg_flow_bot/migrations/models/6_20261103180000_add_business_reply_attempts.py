from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    sqlite = db.capabilities.dialect == "sqlite"
    pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if sqlite else "BIGSERIAL PRIMARY KEY"
    timestamp = "TIMESTAMP" if sqlite else "TIMESTAMPTZ"
    return f"""
        CREATE TABLE IF NOT EXISTS "business_reply_attempts" (
            "id" {pk},
            "user_id" BIGINT NOT NULL,
            "request_id" VARCHAR(36) NOT NULL,
            "chat_id" BIGINT NOT NULL REFERENCES "chats" ("id") ON DELETE RESTRICT,
            "target_message_id" BIGINT NOT NULL,
            "payload_hash" VARCHAR(64) NOT NULL,
            "connection_id" VARCHAR(255) NOT NULL,
            "status" VARCHAR(20) NOT NULL DEFAULT 'reserved',
            "telegram_message_id" BIGINT,
            "reply_attached" BOOLEAN NOT NULL DEFAULT FALSE,
            "error_code" VARCHAR(80),
            "created_at" {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updated_at" {timestamp} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT "uid_business_reply_user_request" UNIQUE ("user_id", "request_id")
        );
    """


async def downgrade(db: BaseDBAsyncClient) -> str:
    raise RuntimeError(
        "Reply attempt records prevent duplicate sends; do not downgrade or erase them"
    )
