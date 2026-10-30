from tortoise import fields
from tortoise.models import Model


class Chat(Model):
    id = fields.BigIntField(pk=True)
    chat_type = fields.CharField(max_length=50)
    title = fields.CharField(max_length=255, null=True)
    username = fields.CharField(max_length=255, null=True)
    photo_file_id = fields.CharField(max_length=255, null=True)
    bot_added_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    subscriptions: fields.ReverseRelation["UserChatSubscription"]
    messages: fields.ReverseRelation["ChatMessage"]
    mentioned_messages: fields.ReverseRelation["MentionedMessage"]

    class Meta:
        table = "chats"


class UserChatSubscription(Model):
    id = fields.BigIntField(pk=True)
    user_id = fields.BigIntField()
    chat = fields.ForeignKeyField("models.Chat", related_name="subscriptions")
    tg_user_id = fields.BigIntField()
    tg_username = fields.CharField(max_length=255, null=True)
    capture_mode = fields.CharField(max_length=20, default="mentions")
    capture_mode_changed_at = fields.DatetimeField(auto_now_add=True)
    subscribed_at = fields.DatetimeField(auto_now_add=True)

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
