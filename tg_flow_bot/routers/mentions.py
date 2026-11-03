import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from models import MentionedMessage
from schemas import (
    ChatMessageResponse,
    MentionContextResponse,
    MentionStats,
    MentionUpdateRequest,
    MentionWithLink,
    ReplyRequest,
    ReplyResponse,
)
from services.mention_context import mention_context_messages
from services.security import TokenPayload, get_current_user_read, get_current_user_write

router = APIRouter(prefix="/mentions", tags=["mentions"])
logger = logging.getLogger(__name__)


@router.get("/", response_model=list[MentionWithLink])
async def get_my_mentions(
    user: TokenPayload = Depends(get_current_user_read),
    chat_id: int | None = Query(None, description="Filter by chat ID"),
    include_archived: bool = Query(True, description="Include archived mentions"),
    limit: int = Query(50, ge=1, le=100, description="Max number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    Get all mentions for the authenticated user.
    Returns mentions sorted by message date (newest first).
    Includes chat title and username.

    Note: user_id in MentionedMessage is the internal auth service ID,
    not the Telegram user ID.
    """
    query = MentionedMessage.filter(user_id=user.user_id)

    if chat_id:
        query = query.filter(chat_id=chat_id)
    if not include_archived:
        query = query.filter(is_archived=False)

    # Prefetch related chat data
    mentions = (
        await query.prefetch_related("chat").order_by("-message_date").offset(offset).limit(limit)
    )

    return [
        MentionWithLink(
            id=m.id,
            user_id=m.user_id,
            chat_id=m.chat_id,
            message_id=m.message_id,
            from_user_id=m.from_user_id,
            from_username=m.from_username,
            text=m.text,
            message_date=m.message_date,
            subscription_id=m.subscription_id,
            saved_at=m.saved_at,
            link=MentionWithLink.generate_link(m.chat_id, m.message_id),
            chat_title=m.chat.title if m.chat else None,
            chat_username=m.chat.username if m.chat else None,
            is_archived=m.is_archived,
        )
        for m in mentions
    ]


@router.get("/stats/", response_model=MentionStats)
async def get_mention_stats(
    user: TokenPayload = Depends(get_current_user_read),
):
    total_mentions = await MentionedMessage.filter(user_id=user.user_id, is_archived=False).count()

    total_chats = (
        await MentionedMessage.filter(user_id=user.user_id, is_archived=False)
        .distinct()
        .values_list("chat_id", flat=True)
    )

    yesterday = datetime.now() - timedelta(hours=24)
    recent_mentions = await MentionedMessage.filter(
        user_id=user.user_id, is_archived=False, message_date__gte=yesterday
    ).count()

    return MentionStats(
        total_mentions=total_mentions,
        total_chats=len(set(total_chats)),
        recent_mentions=recent_mentions,
    )


@router.post("/{mention_id}/reply", response_model=ReplyResponse)
async def reply_to_mention(
    mention_id: int,
    reply: ReplyRequest,
    user: TokenPayload = Depends(get_current_user_write),
):
    from main import get_bot

    mention = await MentionedMessage.get_or_none(
        id=mention_id,
        user_id=user.user_id,
        is_archived=False,
    )

    if not mention:
        raise HTTPException(status_code=404, detail="Mention not found")

    chat = await mention.chat
    if chat.business_connection_id is not None or chat.chat_type == "private":
        raise HTTPException(status_code=403, detail="Business messages do not support mention replies")

    if not reply.text or not reply.text.strip():
        raise HTTPException(status_code=400, detail="Reply text cannot be empty")

    if len(reply.text) > 4096:
        raise HTTPException(status_code=400, detail="Reply text too long (max 4096 characters)")

    try:
        bot = get_bot()

        sent_message = await bot.bot.send_message(
            chat_id=mention.chat_id,
            text=reply.text.strip(),
            reply_to_message_id=mention.message_id,
        )

        # Archive mention after successful reply
        mention.is_archived = True
        await mention.save()

        return ReplyResponse(
            success=True,
            message_id=sent_message.message_id,
        )

    except Exception:
        logger.exception("Telegram reply failed for mention %s", mention.id)
        return ReplyResponse(
            success=False,
            error="Telegram could not send the reply",
        )


@router.patch("/{mention_id}", response_model=MentionWithLink)
async def update_mention(
    mention_id: int,
    payload: MentionUpdateRequest,
    user: TokenPayload = Depends(get_current_user_write),
):
    mention = (
        await MentionedMessage.filter(id=mention_id, user_id=user.user_id)
        .prefetch_related("chat")
        .first()
    )

    if not mention:
        raise HTTPException(status_code=404, detail="Mention not found")

    mention.is_archived = payload.is_archived
    await mention.save()

    return MentionWithLink(
        id=mention.id,
        user_id=mention.user_id,
        chat_id=mention.chat_id,
        message_id=mention.message_id,
        from_user_id=mention.from_user_id,
        from_username=mention.from_username,
        text=mention.text,
        message_date=mention.message_date,
        subscription_id=mention.subscription_id,
        saved_at=mention.saved_at,
        link=MentionWithLink.generate_link(mention.chat_id, mention.message_id),
        chat_title=mention.chat.title if mention.chat else None,
        chat_username=mention.chat.username if mention.chat else None,
        is_archived=mention.is_archived,
    )


@router.get("/{mention_id}/context", response_model=MentionContextResponse)
async def get_mention_context(
    mention_id: int,
    before: int = Query(5, ge=0, le=50),
    after: int = Query(5, ge=0, le=50),
    user: TokenPayload = Depends(get_current_user_read),
):
    mention = (
        await MentionedMessage.filter(id=mention_id, user_id=user.user_id)
        .prefetch_related("chat")
        .first()
    )

    if not mention:
        raise HTTPException(status_code=404, detail="Mention not found")

    before_messages, after_messages = await mention_context_messages(mention, before, after)

    return MentionContextResponse(
        mention=MentionWithLink(
            id=mention.id,
            user_id=mention.user_id,
            chat_id=mention.chat_id,
            message_id=mention.message_id,
            from_user_id=mention.from_user_id,
            from_username=mention.from_username,
            text=mention.text,
            message_date=mention.message_date,
            subscription_id=mention.subscription_id,
            saved_at=mention.saved_at,
            link=MentionWithLink.generate_link(mention.chat_id, mention.message_id),
            chat_title=mention.chat.title if mention.chat else None,
            chat_username=mention.chat.username if mention.chat else None,
            is_archived=mention.is_archived,
        ),
        before=[ChatMessageResponse.model_validate(m) for m in before_messages],
        after=[ChatMessageResponse.model_validate(m) for m in after_messages],
    )
