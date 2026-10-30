from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from config import settings
from models import Chat, ChatMessage, MentionedMessage, UserChatSubscription
from schemas import CaptureModeUpdate, ChatMessageResponse, ChatSubscriptionResponse
from services.security import TokenPayload, get_current_user_read, get_current_user_write

router = APIRouter(prefix="/chats", tags=["chats"])

CAPTURE_MODES = {"mentions", "full"}


@router.get("/", response_model=list[ChatSubscriptionResponse])
async def get_my_chats(
    user: TokenPayload = Depends(get_current_user_read),
):
    subscriptions = (
        await UserChatSubscription.filter(user_id=user.user_id)
        .prefetch_related("chat")
        .order_by("-subscribed_at")
    )
    return [
        ChatSubscriptionResponse(
            id=subscription.id,
            chat_id=subscription.chat_id,
            title=subscription.chat.title,
            username=subscription.chat.username,
            chat_type=subscription.chat.chat_type,
            capture_mode=subscription.capture_mode,
            capture_mode_changed_at=subscription.capture_mode_changed_at,
            subscribed_at=subscription.subscribed_at,
        )
        for subscription in subscriptions
    ]


@router.patch("/{chat_id}/mode", response_model=ChatSubscriptionResponse)
async def update_capture_mode(
    chat_id: int,
    payload: CaptureModeUpdate,
    user: TokenPayload = Depends(get_current_user_write),
):
    if payload.capture_mode not in CAPTURE_MODES:
        raise HTTPException(status_code=422, detail="capture_mode must be 'mentions' or 'full'")

    subscription = (
        await UserChatSubscription.filter(user_id=user.user_id, chat_id=chat_id)
        .prefetch_related("chat")
        .first()
    )
    if not subscription:
        raise HTTPException(status_code=404, detail="Chat subscription not found")

    if subscription.capture_mode != payload.capture_mode:
        subscription.capture_mode = payload.capture_mode
        subscription.capture_mode_changed_at = datetime.now(UTC)
        await subscription.save(update_fields=("capture_mode", "capture_mode_changed_at"))
    return ChatSubscriptionResponse(
        id=subscription.id,
        chat_id=subscription.chat_id,
        title=subscription.chat.title,
        username=subscription.chat.username,
        chat_type=subscription.chat.chat_type,
        capture_mode=subscription.capture_mode,
        capture_mode_changed_at=subscription.capture_mode_changed_at,
        subscribed_at=subscription.subscribed_at,
    )


@router.get("/{chat_id}/messages", response_model=list[ChatMessageResponse])
async def get_chat_messages(
    chat_id: int,
    limit: int = Query(100, ge=1, le=200),
    before_message_id: int | None = Query(None),
    user: TokenPayload = Depends(get_current_user_read),
):
    subscription = await UserChatSubscription.get_or_none(
        user_id=user.user_id,
        chat_id=chat_id,
    )
    if not subscription:
        raise HTTPException(status_code=404, detail="Chat subscription not found")
    if subscription.capture_mode != "full":
        raise HTTPException(status_code=403, detail="Full-chat mode is not enabled for this chat")

    query = ChatMessage.filter(
        chat_id=chat_id,
        saved_at__gte=subscription.capture_mode_changed_at,
    )
    if before_message_id is not None:
        query = query.filter(message_id__lt=before_message_id)
    messages = await query.order_by("-message_id").limit(limit)
    return [ChatMessageResponse.model_validate(message) for message in reversed(messages)]


@router.get("/{chat_id}/photo")
async def get_chat_photo(
    chat_id: int,
    user: TokenPayload = Depends(get_current_user_read),
):
    """
    Proxy a chat photo without exposing the bot token in a redirect URL.
    Returns 404 if chat has no photo.
    """
    chat = await Chat.get_or_none(id=chat_id)

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    authorized = await UserChatSubscription.exists(user_id=user.user_id, chat_id=chat_id)
    if not authorized:
        authorized = await MentionedMessage.exists(user_id=user.user_id, chat_id=chat_id)
    if not authorized:
        raise HTTPException(status_code=404, detail="Chat not found")

    if not chat.photo_file_id:
        raise HTTPException(status_code=404, detail="Chat has no photo")

    # Get file path from Telegram
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getFile",
            params={"file_id": chat.photo_file_id},
        )

        if response.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to get file from Telegram")

        data = response.json()
        if not data.get("ok"):
            raise HTTPException(status_code=502, detail="Telegram API error")

        file_path = data.get("result", {}).get("file_path")
        if not isinstance(file_path, str) or not file_path:
            raise HTTPException(status_code=502, detail="Telegram returned an invalid file path")
        photo_url = f"https://api.telegram.org/file/bot{settings.BOT_TOKEN}/{file_path}"
        photo = await client.get(photo_url)
        if photo.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to download file from Telegram")

    return Response(
        content=photo.content,
        media_type=photo.headers.get("content-type", "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=300"},
    )
