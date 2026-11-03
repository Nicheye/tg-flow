import json
import logging
import os
from datetime import UTC, datetime, timedelta

import httpx
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import (
    TransportSecurityMiddleware as MCPTransportSecurityMiddleware,
)
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl
from starlette.requests import Request
from telegram import Bot

from config import settings
from models import ChatMessage, MentionedMessage, UserChatSubscription
from schemas import MentionWithLink
from services.auth_transport import auth_http_client, auth_url
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
from services.mention_context import mention_context_messages
from services.security import TokenPayload, protected_resource_metadata_url, verify_token

logger = logging.getLogger(__name__)

READ_SCOPE = "mentions:read"
WRITE_SCOPE = "mentions:write"
WRITE_TOOLS = frozenset(("archive_mention", "reply_to_mention", "mark_chat_read", "reply_to_chat_message"))


class AuthServiceTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with auth_http_client() as client:
                response = await client.post(
                    auth_url(settings.OAUTH_INTROSPECTION_URL, "/oauth/introspect"),
                    data={"token": token},
                    auth=(
                        settings.MCP_INTROSPECTION_CLIENT_ID,
                        settings.MCP_INTROSPECTION_CLIENT_SECRET,
                    ),
                )
            if response.status_code != 200:
                logger.warning("OAuth introspection failed with status %s", response.status_code)
                return None
            payload = response.json()
        except (httpx.RequestError, ValueError):
            logger.exception("OAuth introspection request failed")
            return None

        if not isinstance(payload, dict):
            return None
        audience = payload.get("aud") or payload.get("resource")
        if not payload.get("active") or audience != settings.MCP_RESOURCE_URI:
            return None
        try:
            subject = str(int(payload["sub"]))
            scopes = payload.get("scope", "")
            if not isinstance(scopes, str):
                return None
        except (KeyError, TypeError, ValueError):
            return None
        return AccessToken(
            token=token,
            client_id=payload.get("client_id", "unknown"),
            scopes=scopes.split(),
            expires_at=payload.get("exp"),
            resource=audience,
            subject=subject,
            claims={"user_id": int(subject)},
        )


class ToolScopeMiddleware:
    def __init__(
        self,
        app,
        verifier: TokenVerifier,
        transport_security: TransportSecuritySettings,
    ):
        self.app = app
        self.verifier = verifier
        self.transport_security = MCPTransportSecurityMiddleware(transport_security)

    async def _error(
        self, scope, receive, send, status: int, error: str, description: str, required_scope: str
    ):
        metadata_url = protected_resource_metadata_url()
        challenge = (
            f'Bearer error="{error}", error_description="{description}", '
            f'resource_metadata="{metadata_url}", scope="{required_scope}"'
        )
        body = json.dumps({"error": error, "error_description": description}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                    (b"www-authenticate", challenge.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        transport_error = await self.transport_security.validate_request(
            Request(scope, receive=receive), is_post=True
        )
        if transport_error is not None:
            await transport_error(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("ascii", errors="ignore")
        scheme, separator, token = authorization.partition(" ")
        access_token = (
            await self.verifier.verify_token(token)
            if separator and scheme.lower() == "bearer" and token
            else None
        )
        if access_token is None:
            await self._error(
                scope,
                receive,
                send,
                401,
                "invalid_token",
                "Authentication required or access token invalid",
                READ_SCOPE,
            )
            return
        if READ_SCOPE not in access_token.scopes:
            await self._error(
                scope,
                receive,
                send,
                403,
                "insufficient_scope",
                "Read permission required for this MCP server",
                READ_SCOPE,
            )
            return

        method = headers.get(b"mcp-method", b"").decode("ascii", errors="ignore")
        tool_name = headers.get(b"mcp-name", b"").decode("ascii", errors="ignore")
        if method != "tools/call" or tool_name not in WRITE_TOOLS:
            await self.app(scope, receive, send)
            return

        if WRITE_SCOPE in access_token.scopes:
            await self.app(scope, receive, send)
            return

        await self._error(
            scope,
            receive,
            send,
            403,
            "insufficient_scope",
            "Write permission required for this tool",
            WRITE_SCOPE,
        )


async def _principal() -> TokenPayload:
    access_token = get_access_token()
    if access_token is not None:
        if access_token.resource != settings.MCP_RESOURCE_URI or not access_token.subject:
            raise ToolError("The access token is not valid for this MCP resource")
        return TokenPayload(
            user_id=int(access_token.subject),
            scopes=access_token.scopes,
            client_id=access_token.client_id,
        )

    local_token = os.environ.get("TGFLOW_ACCESS_TOKEN", "")
    if not local_token:
        raise ToolError(
            "Local stdio access requires TGFLOW_ACCESS_TOKEN. Run `tgflow auth login` first."
        )
    principal = await verify_token(local_token)
    if principal is None:
        raise ToolError("TGFLOW_ACCESS_TOKEN is invalid or expired")
    return principal


def _require_scope(principal: TokenPayload, scope: str) -> None:
    if scope not in principal.scopes:
        raise ToolError(f"Authorization requires the {scope} scope")


def _mention_dict(mention: MentionedMessage) -> dict:
    return {
        "id": mention.id,
        "chat_id": mention.chat_id,
        "chat_title": mention.chat.title if mention.chat else None,
        "chat_username": mention.chat.username if mention.chat else None,
        "message_id": mention.message_id,
        "from_user_id": mention.from_user_id,
        "from_username": mention.from_username,
        "text": mention.text,
        "message_date": mention.message_date.isoformat(),
        "saved_at": mention.saved_at.isoformat(),
        "is_archived": mention.is_archived,
        "link": MentionWithLink.generate_link(mention.chat_id, mention.message_id),
    }


def _message_dict(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "chat_id": message.chat_id,
        "message_id": message.message_id,
        "from_user_id": message.from_user_id,
        "from_username": message.from_username,
        "text": message.text,
        "message_date": message.message_date.isoformat(),
        "saved_at": message.saved_at.isoformat(),
    }


async def _get_owned_mention(user_id: int, mention_id: int) -> MentionedMessage:
    mention = (
        await MentionedMessage.filter(id=mention_id, user_id=user_id)
        .prefetch_related("chat")
        .first()
    )
    if mention is None:
        raise ToolError("Mention not found")
    return mention


def create_mcp_server() -> tuple[MCPServer, AuthServiceTokenVerifier]:
    verifier = AuthServiceTokenVerifier()
    server = MCPServer(
        name="tg-flow",
        title="TG Flow",
        description=(
            "Read, triage, and reply to Telegram mentions, or inspect chats whose owner enabled "
            "full-message capture."
        ),
        instructions=(
            "Use read tools to inspect mentions. Before archive or reply operations, explain the "
            "effect and obtain the user's confirmation. Never infer a mention ID from another user. "
            "For requested chat summaries, read all pages of a fixed unread snapshot, summarize "
            "successfully, then mark only its processed boundary read without an extra confirmation. "
            "Reading alone never marks read; failed summaries must not advance the checkpoint. "
            "Business private replies send from the user's account. Before reply_to_chat_message, "
            "show the exact recipient and text and get explicit user approval; only then pass confirmed=true."
        ),
        version="1.0.0",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.OAUTH_ISSUER),
            resource_server_url=AnyHttpUrl(settings.MCP_RESOURCE_URI),
            required_scopes=[READ_SCOPE],
        ),
    )

    @server.tool(
        title="List mentions",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def list_mentions(
        chat_id: int | None = None,
        include_archived: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """List the caller's mentions, newest first, with optional chat and archive filters."""
        principal = await _principal()
        _require_scope(principal, READ_SCOPE)
        if not 1 <= limit <= 100 or offset < 0:
            raise ToolError("limit must be 1-100 and offset must be non-negative")
        query = MentionedMessage.filter(user_id=principal.user_id)
        if chat_id is not None:
            query = query.filter(chat_id=chat_id)
        if not include_archived:
            query = query.filter(is_archived=False)
        mentions = (
            await query.prefetch_related("chat")
            .order_by("-message_date")
            .offset(offset)
            .limit(limit)
        )
        return [_mention_dict(mention) for mention in mentions]

    @server.tool(
        title="List chat capture modes",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def list_chat_subscriptions() -> list[dict]:
        """List the caller's Telegram chats and the capture mode enabled for each one."""
        principal = await _principal()
        _require_scope(principal, READ_SCOPE)
        subscriptions = (
            await UserChatSubscription.filter(user_id=principal.user_id)
            .prefetch_related("chat")
            .order_by("-subscribed_at")
        )
        return [
            {
                "chat_id": subscription.chat_id,
                "chat_title": subscription.chat.title,
                "chat_username": subscription.chat.username,
                "chat_type": subscription.chat.chat_type,
                **await source_metadata(subscription.chat),
                "capture_mode": subscription.capture_mode,
                "capture_mode_changed_at": subscription.capture_mode_changed_at.isoformat(),
                "read_through_message_id": subscription.read_through_message_id,
                "last_read_at": subscription.last_read_at.isoformat() if subscription.last_read_at else None,
                "unread_count": await unread_count(subscription),
            }
            for subscription in subscriptions
            if await owns_subscription(subscription, principal.user_id)
        ]

    @server.tool(
        title="List full chat messages",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def list_chat_messages(
        chat_id: int,
        limit: int = 100,
        before_message_id: int | None = None,
    ) -> list[dict]:
        """Read a complete chat feed when the caller has enabled full capture for that chat."""
        principal = await _principal()
        _require_scope(principal, READ_SCOPE)
        if not 1 <= limit <= 200:
            raise ToolError("limit must be between 1 and 200")
        subscription = await owned_subscription(principal.user_id, chat_id)
        if subscription is None:
            raise ToolError("Chat subscription not found")
        if subscription.capture_mode != "full":
            raise ToolError("Full-chat mode is not enabled for this chat")
        query = await visible_messages(subscription)
        if before_message_id is not None:
            query = query.filter(message_id__lt=before_message_id)
        messages = await query.order_by("-message_id").limit(limit)
        return [_message_dict(message) for message in reversed(messages)]

    @server.tool(
        title="List unread chat messages",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def list_unread_chat_messages(
        chat_id: int, limit: int = 100, after_message_id: int | None = None,
        through_message_id: int | None = None, capture_mode_changed_at: datetime | None = None,
    ) -> dict:
        """Read new messages since the caller's last summary checkpoint, without marking read.

        First page freezes snapshot_through_message_id. Read every page using that fixed
        through_message_id, next_after_message_id and capture_mode_changed_at. Summarize
        the requested messages successfully, then explicitly mark_chat_read through the
        snapshot boundary. For a partial summary mark only the last actually processed
        message, never the newest message at marking time. Failed summaries never mark.
        """
        principal = await _principal()
        _require_scope(principal, READ_SCOPE)
        try:
            result = await list_unread(principal.user_id, chat_id, limit, after_message_id,
                                       through_message_id, capture_mode_changed_at)
        except ChatUnreadError as error:
            raise ToolError(str(error)) from error
        result["messages"] = [_message_dict(row) for row in result["messages"]]
        result["capture_mode_changed_at"] = result["capture_mode_changed_at"].isoformat()
        return result

    @server.tool(
        title="Mark chat messages read",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                    idempotentHint=True, openWorldHint=False),
    )
    async def mark_chat_read(chat_id: int, through_message_id: int, capture_mode_changed_at: datetime) -> dict:
        """Advance the caller's local summary checkpoint through an observed message.

        Only after a successful requested summary, acknowledge its fully processed snapshot
        (or explicitly its last processed message). User-requested summary workflows may
        do this without an additional archive/reply confirmation. Never mark on failed or
        incomplete processing. This changes only the local unread checkpoint; it does not
        archive, delete, send messages, or change Telegram read receipts.
        """
        principal = await _principal()
        _require_scope(principal, WRITE_SCOPE)
        try:
            subscription = await mark_read(principal.user_id, chat_id, through_message_id,
                                           capture_mode_changed_at)
        except ChatUnreadError as error:
            raise ToolError(str(error)) from error
        return {
            "read_through_message_id": subscription.read_through_message_id,
            "last_read_at": subscription.last_read_at.isoformat() if subscription.last_read_at else None,
            "unread_count": await unread_count(subscription),
        }

    @server.tool(
        title="Mention statistics",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def get_mention_stats() -> dict:
        """Return unarchived mention, chat, and last-24-hours counts for the caller."""
        principal = await _principal()
        _require_scope(principal, READ_SCOPE)
        active = MentionedMessage.filter(user_id=principal.user_id, is_archived=False)
        total_mentions = await active.count()
        chat_ids = await active.distinct().values_list("chat_id", flat=True)
        recent_mentions = await active.filter(
            message_date__gte=datetime.now(UTC) - timedelta(hours=24)
        ).count()
        return {
            "total_mentions": total_mentions,
            "total_chats": len(set(chat_ids)),
            "recent_mentions": recent_mentions,
        }

    @server.tool(
        title="Get mention context",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def get_mention_context(
        mention_id: int,
        before: int = 5,
        after: int = 5,
    ) -> dict:
        """Get a mention plus neighboring messages in the same Telegram chat."""
        principal = await _principal()
        _require_scope(principal, READ_SCOPE)
        if not 0 <= before <= 50 or not 0 <= after <= 50:
            raise ToolError("before and after must each be between 0 and 50")
        mention = await _get_owned_mention(principal.user_id, mention_id)
        previous, following = await mention_context_messages(mention, before, after)

        return {
            "mention": _mention_dict(mention),
            "before": [_message_dict(message) for message in previous],
            "after": [_message_dict(message) for message in following],
        }

    @server.tool(
        title="Archive or restore a mention",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    )
    async def archive_mention(mention_id: int, archived: bool = True) -> dict:
        """Set the archived state of one mention owned by the caller."""
        principal = await _principal()
        _require_scope(principal, WRITE_SCOPE)
        mention = await _get_owned_mention(principal.user_id, mention_id)
        mention.is_archived = archived
        await mention.save(update_fields=("is_archived",))
        return _mention_dict(mention)

    @server.tool(
        title="Check private reply delivery",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                    openWorldHint=False),
    )
    async def get_chat_reply_status(chat_id: int, request_id: str) -> dict:
        """Read an existing reply attempt without sending or creating an attempt.

        Use after an uncertain response. A missing attempt is not proof of
        non-delivery if the original request may still be in flight. Check
        Telegram before approving a new attempt. This never retries delivery.
        """
        principal = await _principal()
        _require_scope(principal, READ_SCOPE)
        try:
            return await get_business_reply_status(principal.user_id, chat_id, request_id)
        except BusinessReplyError as error:
            raise ToolError(str(error)) from error

    @server.tool(
        title="Reply in a Business private chat",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                    idempotentHint=True, openWorldHint=True),
    )
    async def reply_to_chat_message(
        chat_id: int, message_id: int, text: str, request_id: str, confirmed: bool = False
    ) -> dict:
        """Send an explicitly approved reply FROM the connected Telegram account.

        Show the recipient and exact message text to the user and obtain approval
        before setting confirmed=true. Use the internal chat_id and a captured
        message_id. Generate a UUID request_id for this approved attempt and reuse
        it for every status retry: the same key never sends twice. Unknown delivery
        requires checking Telegram before the user approves any NEW attempt/key.
        Telegram requires reply permission and incoming activity in the last 24h.
        If the target disappeared Telegram may send a standalone message instead;
        inspect reply_attached. Never mark read or archive as part of this action.
        """
        principal = await _principal()
        _require_scope(principal, WRITE_SCOPE)
        if not confirmed:
            raise ToolError("Explicit user approval of the recipient and exact text is required")
        try:
            return await send_business_reply(principal.user_id, chat_id, message_id, text, request_id)
        except BusinessReplyError as error:
            raise ToolError(str(error)) from error

    @server.tool(
        title="Reply to a mention",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def reply_to_mention(
        mention_id: int, text: str, archive_after_reply: bool = True
    ) -> dict:
        """Send a Telegram reply to one unarchived mention owned by the caller."""
        principal = await _principal()
        _require_scope(principal, WRITE_SCOPE)
        reply_text = text.strip()
        if not reply_text or len(reply_text) > 4096:
            raise ToolError("Reply text must contain 1-4096 characters")
        mention = await _get_owned_mention(principal.user_id, mention_id)
        if mention.chat.business_connection_id is not None or mention.chat.chat_type == "private":
            raise ToolError("Business messages do not support replies through mention tools")
        if mention.is_archived:
            raise ToolError("Mention is archived")
        try:
            from main import get_bot

            try:
                bot_application = get_bot()
            except RuntimeError:
                bot_application = None
            if bot_application is not None:
                sent = await bot_application.bot.send_message(
                    chat_id=mention.chat_id,
                    text=reply_text,
                    reply_to_message_id=mention.message_id,
                )
            else:
                # Used only when the MCP server runs outside the combined FastAPI process.
                async with Bot(settings.BOT_TOKEN) as bot:
                    sent = await bot.send_message(
                        chat_id=mention.chat_id,
                        text=reply_text,
                        reply_to_message_id=mention.message_id,
                    )
        except Exception as error:
            logger.exception("Telegram reply failed for mention %s", mention.id)
            raise ToolError("Telegram could not send the reply") from error
        if archive_after_reply:
            mention.is_archived = True
            await mention.save(update_fields=("is_archived",))
        return {
            "success": True,
            "telegram_message_id": sent.message_id,
            "mention": _mention_dict(mention),
        }

    @server.resource(
        "tgflow://mentions/{mention_id}",
        name="mention",
        title="TG Flow mention",
        description="A caller-owned mention with surrounding Telegram message context.",
        mime_type="application/json",
    )
    async def mention_resource(mention_id: int) -> str:
        principal = await _principal()
        _require_scope(principal, READ_SCOPE)
        mention = await _get_owned_mention(principal.user_id, mention_id)
        return json.dumps(_mention_dict(mention), ensure_ascii=False)

    @server.prompt(title="Triage Telegram mentions")
    def triage_mentions(limit: int = 20) -> str:
        """Create a safe workflow for reviewing and triaging recent mentions."""
        return (
            f"List up to {limit} unarchived mentions, summarize urgent items and likely actions, "
            "then ask me before archiving anything or sending any Telegram reply."
        )

    return server, verifier
