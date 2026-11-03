from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from tortoise.transactions import in_transaction

from config import settings
from models import BusinessConnection, Chat, MentionedMessage, UserChatSubscription
from schemas import (
    BusinessReplyRequest,
    BusinessReplyResponse,
    CaptureModeUpdate,
    ChatMessageResponse,
    ChatReadRequest,
    ChatSubscriptionResponse,
    ChatUnreadResponse,
)
from services.business_access import owned_subscription, owns_subscription, source_metadata
from services.business_reply import (
    BusinessReplyError,
    get_business_reply_status,
    send_business_reply,
)
from services.chat_unread import (
    ChatUnreadError,
    list_unread,
    mark_read,
    unread_count,
    visible_messages,
)
from services.security import TokenPayload, get_current_user_read, get_current_user_write

router = APIRouter(prefix="/chats", tags=["chats"])

CAPTURE_MODES = {"mentions", "full", "disabled"}


async def _subscription_response(subscription):
    chat = await subscription.chat
    return ChatSubscriptionResponse(
        id=subscription.id,
        chat_id=subscription.chat_id,
        title=chat.title,
        username=chat.username,
        chat_type=chat.chat_type,
        **await source_metadata(chat),
        capture_mode=subscription.capture_mode,
        capture_mode_changed_at=subscription.capture_mode_changed_at,
        subscribed_at=subscription.subscribed_at,
        read_through_message_id=subscription.read_through_message_id,
        last_read_at=subscription.last_read_at,
        unread_count=await unread_count(subscription),
    )


@router.get("/{chat_id}/unread", response_model=ChatUnreadResponse)
async def get_unread_messages(
    chat_id: int,
    limit: int = Query(100, ge=1, le=200),
    after_message_id: int | None = Query(None, ge=0),
    through_message_id: int | None = Query(None, ge=0),
    capture_mode_changed_at: datetime | None = Query(None),
    user: TokenPayload = Depends(get_current_user_read),
):
    try:
        result = await list_unread(
            user.user_id,
            chat_id,
            limit,
            after_message_id,
            through_message_id,
            capture_mode_changed_at,
        )
    except ChatUnreadError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    result["messages"] = [ChatMessageResponse.model_validate(row) for row in result["messages"]]
    return result


@router.post("/{chat_id}/read", response_model=ChatSubscriptionResponse)
async def mark_chat_read(
    chat_id: int,
    payload: ChatReadRequest,
    user: TokenPayload = Depends(get_current_user_write),
):
    try:
        subscription = await mark_read(
            user.user_id, chat_id, payload.through_message_id, payload.capture_mode_changed_at
        )
    except ChatUnreadError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return await _subscription_response(subscription)


@router.get("/", response_model=list[ChatSubscriptionResponse])
async def get_my_chats(
    user: TokenPayload = Depends(get_current_user_read),
):
    subscriptions = (
        await UserChatSubscription.filter(user_id=user.user_id)
        .prefetch_related("chat")
        .order_by("-subscribed_at")
    )
    return [await _subscription_response(subscription) for subscription in subscriptions
            if await owns_subscription(subscription, user.user_id)]


@router.patch("/{chat_id}/mode", response_model=ChatSubscriptionResponse)
async def update_capture_mode(
    chat_id: int,
    payload: CaptureModeUpdate,
    user: TokenPayload = Depends(get_current_user_write),
):
    if payload.capture_mode not in CAPTURE_MODES:
        raise HTTPException(
            status_code=422, detail="capture_mode must be 'mentions', 'full', or 'disabled'"
        )

    async with in_transaction() as db:
        subscription = await owned_subscription(user.user_id, chat_id)
        if not subscription:
            raise HTTPException(status_code=404, detail="Chat subscription not found")
        chat = await subscription.chat
        if chat.business_connection_id is not None:
            # Serialize opt-out with ingestion and revocation on the owner row.
            await BusinessConnection.filter(id=chat.business_connection_id).using_db(db).select_for_update().first()
            if payload.capture_mode == "mentions":
                raise HTTPException(status_code=422, detail="Business chats support full or disabled capture")
            metadata = await source_metadata(chat)
            if payload.capture_mode == "full" and not metadata["connection_active"]:
                raise HTTPException(status_code=409, detail="Reconnect Telegram Business before enabling capture")

        if subscription.capture_mode != payload.capture_mode:
            subscription.capture_mode = payload.capture_mode
            subscription.capture_mode_changed_at = datetime.now(UTC)
            await subscription.save(update_fields=("capture_mode", "capture_mode_changed_at"))
        return await _subscription_response(subscription)


@router.get("/{chat_id}/messages", response_model=list[ChatMessageResponse])
async def get_chat_messages(
    chat_id: int,
    limit: int = Query(100, ge=1, le=200),
    before_message_id: int | None = Query(None),
    user: TokenPayload = Depends(get_current_user_read),
):
    subscription = await owned_subscription(user.user_id, chat_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Chat subscription not found")
    if subscription.capture_mode != "full":
        raise HTTPException(status_code=403, detail="Full-chat mode is not enabled for this chat")

    query = await visible_messages(subscription)
    if before_message_id is not None:
        query = query.filter(message_id__lt=before_message_id)
    messages = await query.order_by("-message_id").limit(limit)
    return [ChatMessageResponse.model_validate(message) for message in reversed(messages)]


@router.post("/{chat_id}/messages/{message_id}/reply", response_model=BusinessReplyResponse)
async def reply_to_chat_message(
    chat_id: int,
    message_id: int,
    payload: BusinessReplyRequest,
    user: TokenPayload = Depends(get_current_user_write),
):
    """The Send action explicitly authorizes sending from the connected account."""
    try:
        return await send_business_reply(user.user_id, chat_id, message_id, payload.text, payload.request_id)
    except BusinessReplyError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("/{chat_id}/reply-attempts/{request_id}", response_model=BusinessReplyResponse)
async def get_chat_reply_status(
    chat_id: int,
    request_id: UUID,
    user: TokenPayload = Depends(get_current_user_read),
):
    try:
        return await get_business_reply_status(user.user_id, chat_id, request_id)
    except BusinessReplyError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


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

    if chat.business_connection_id is not None or chat.chat_type == "private":
        # Internal app IDs must never be passed to Telegram for private chats.
        raise HTTPException(status_code=404, detail="Business chat photos are not available")

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
