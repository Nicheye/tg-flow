from datetime import datetime

from pydantic import BaseModel, ConfigDict

# === Chat Schemas ===


class ChatBase(BaseModel):
    id: int
    chat_type: str
    title: str | None = None
    username: str | None = None


class ChatCreate(ChatBase):
    pass


class ChatResponse(ChatBase):
    bot_added_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# === Subscription Schemas ===


class SubscriptionBase(BaseModel):
    user_id: int
    chat_id: int
    tg_user_id: int
    tg_username: str | None = None


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionResponse(SubscriptionBase):
    id: int
    subscribed_at: datetime
    capture_mode: str

    model_config = ConfigDict(from_attributes=True)


# === MentionedMessage Schemas ===


class MentionBase(BaseModel):
    user_id: int
    chat_id: int
    message_id: int
    from_user_id: int
    from_username: str | None = None
    text: str
    message_date: datetime


class MentionCreate(MentionBase):
    subscription_id: int | None = None


class MentionResponse(MentionBase):
    id: int
    subscription_id: int | None = None
    saved_at: datetime
    is_archived: bool = False

    model_config = ConfigDict(from_attributes=True)


class MentionWithLink(MentionResponse):
    """Mention with generated Telegram link"""

    link: str
    chat_title: str | None = None
    chat_username: str | None = None

    @staticmethod
    def generate_link(chat_id: int, message_id: int) -> str:
        internal_id = str(chat_id).replace("-100", "")
        return f"https://t.me/c/{internal_id}/{message_id}"


# === ChatMessage Schemas ===


class ChatMessageResponse(BaseModel):
    id: int
    chat_id: int
    message_id: int
    from_user_id: int
    from_username: str | None = None
    text: str | None = None
    message_date: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSubscriptionResponse(BaseModel):
    id: int
    chat_id: int
    title: str | None = None
    username: str | None = None
    chat_type: str
    capture_mode: str
    capture_mode_changed_at: datetime
    subscribed_at: datetime


class CaptureModeUpdate(BaseModel):
    capture_mode: str


class MentionContextResponse(BaseModel):
    mention: MentionWithLink
    before: list[ChatMessageResponse]
    after: list[ChatMessageResponse]


# === User Schemas (from Auth Service) ===


class TelegramUser(BaseModel):
    tg_user_id: int
    tg_username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class AuthResponse(BaseModel):
    user_id: int
    access: str
    refresh: str
    created: bool


class ReplyRequest(BaseModel):
    text: str


class ReplyResponse(BaseModel):
    success: bool
    message_id: int | None = None
    error: str | None = None


class MentionUpdateRequest(BaseModel):
    is_archived: bool


class MentionStats(BaseModel):
    total_mentions: int
    total_chats: int
    recent_mentions: int
