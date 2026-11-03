from tortoise import fields
from tortoise.models import Model


class BusinessConnection(Model):
    """One durable owner, independent of Telegram connection ID rotations."""

    id = fields.BigIntField(pk=True)
    tg_user_id = fields.BigIntField(unique=True)
    user_id = fields.BigIntField()
    connection_id = fields.CharField(max_length=255, unique=True)
    is_enabled = fields.BooleanField(default=False)
    last_update_id = fields.BigIntField(default=-1)
    retired_connection_ids = fields.JSONField(default=list)
    connected_at = fields.DatetimeField()
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "business_connections"


class Chat(Model):
    id = fields.BigIntField(pk=True)
    chat_type = fields.CharField(max_length=50)
    title = fields.CharField(max_length=255, null=True)
    username = fields.CharField(max_length=255, null=True)
    photo_file_id = fields.CharField(max_length=255, null=True)
    business_connection = fields.ForeignKeyField(
        "models.BusinessConnection", related_name="chats", null=True, on_delete=fields.RESTRICT
    )
    telegram_chat_id = fields.BigIntField(null=True)
    bot_added_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    subscriptions: fields.ReverseRelation["UserChatSubscription"]
    messages: fields.ReverseRelation["ChatMessage"]
    mentioned_messages: fields.ReverseRelation["MentionedMessage"]

    class Meta:
        table = "chats"
        unique_together = (("business_connection", "telegram_chat_id"),)


class UserChatSubscription(Model):
    id = fields.BigIntField(pk=True)
    user_id = fields.BigIntField()
    chat = fields.ForeignKeyField("models.Chat", related_name="subscriptions")
    tg_user_id = fields.BigIntField()
    tg_username = fields.CharField(max_length=255, null=True)
    capture_mode = fields.CharField(max_length=20, default="mentions")
    capture_mode_changed_at = fields.DatetimeField(auto_now_add=True)
    subscribed_at = fields.DatetimeField(auto_now_add=True)
    read_through_message_id = fields.BigIntField(default=0)
    last_read_at = fields.DatetimeField(null=True)

    mentioned_messages: fields.ReverseRelation["MentionedMessage"]

    class Meta:
        table = "user_chat_subscriptions"
        unique_together = (("user_id", "chat"),)


class ChatMessage(Model):
    id = fields.BigIntField(pk=True)
    chat = fields.ForeignKeyField("models.Chat", related_name="messages")

    message_id = fields.BigIntField()
    from_user_id = fields.BigIntField()
    from_username = fields.CharField(max_length=255, null=True)
    text = fields.TextField(null=True)

    message_date = fields.DatetimeField()
    saved_at = fields.DatetimeField(auto_now_add=True)

    mentioned_messages: fields.ReverseRelation["MentionedMessage"]

    class Meta:
        table = "chat_messages"
        unique_together = (("chat", "message_id"),)


class MentionedMessage(Model):
    id = fields.BigIntField(pk=True)
    user_id = fields.BigIntField()
    chat = fields.ForeignKeyField("models.Chat", related_name="mentioned_messages")
    subscription = fields.ForeignKeyField(
        "models.UserChatSubscription", related_name="mentioned_messages", null=True
    )
    chat_message = fields.ForeignKeyField(
        "models.ChatMessage",
        related_name="mentioned_messages",
        null=True,
        source_field="chat_message_id",
    )

    message_id = fields.BigIntField()
    from_user_id = fields.BigIntField()
    from_username = fields.CharField(max_length=255, null=True)
    text = fields.TextField()

    message_date = fields.DatetimeField()
    saved_at = fields.DatetimeField(auto_now_add=True)
    is_archived = fields.BooleanField(default=False)

    class Meta:
        table = "mentioned_messages"


class BusinessReplyAttempt(Model):
    """Durable no-resend boundary for an explicitly approved outgoing reply."""

    id = fields.BigIntField(pk=True)
    user_id = fields.BigIntField()
    request_id = fields.CharField(max_length=36)
    chat = fields.ForeignKeyField("models.Chat", related_name="reply_attempts", on_delete=fields.RESTRICT)
    target_message_id = fields.BigIntField()
    payload_hash = fields.CharField(max_length=64)
    connection_id = fields.CharField(max_length=255)
    status = fields.CharField(max_length=20, default="reserved")
    telegram_message_id = fields.BigIntField(null=True)
    reply_attached = fields.BooleanField(default=False)
    error_code = fields.CharField(max_length=80, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "business_reply_attempts"
        unique_together = (("user_id", "request_id"),)
