import json

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .client import ApiClient, ApiError
from .credentials import CredentialStore


def create_stdio_server(store: CredentialStore | None = None) -> MCPServer:
    client = ApiClient(store or CredentialStore())
    server = MCPServer(
        name="tg-flow-local",
        title="TG Flow (local)",
        description="Local stdio bridge to the authenticated TG Flow API.",
        instructions=(
            "Use read tools to inspect mentions. Ask for confirmation before archive or reply actions."
        ),
        version="1.0.0",
    )

    async def invoke(call):
        try:
            return await call
        except ApiError as error:
            raise ToolError(str(error)) from error

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
        """List the signed-in user's mentions, newest first."""
        return await invoke(client.list_mentions(chat_id, include_archived, limit, offset))

    @server.tool(
        title="Mention statistics",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def get_mention_stats() -> dict:
        """Return unarchived mention, chat, and recent counts."""
        return await invoke(client.stats())

    @server.tool(
        title="Get mention context",
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
    )
    async def get_mention_context(mention_id: int, before: int = 5, after: int = 5) -> dict:
        """Get a mention and its neighboring Telegram messages."""
        return await invoke(client.context(mention_id, before, after))

    @server.tool(
        title="Archive or restore a mention",
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    )
    async def archive_mention(mention_id: int, archived: bool = True) -> dict:
        """Set the archived state of one mention."""
        return await invoke(client.archive(mention_id, archived))

    @server.tool(
        title="Reply to a mention",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def reply_to_mention(mention_id: int, text: str) -> dict:
        """Send a Telegram reply and archive the mention after success."""
        return await invoke(client.reply(mention_id, text))

    @server.resource(
        "tgflow://mentions/{mention_id}",
        name="mention",
        title="TG Flow mention",
        description="A mention with surrounding Telegram context.",
        mime_type="application/json",
    )
    async def mention_resource(mention_id: int) -> str:
        return json.dumps(await invoke(client.context(mention_id)), ensure_ascii=False)

    @server.prompt(title="Triage Telegram mentions")
    def triage_mentions(limit: int = 20) -> str:
        """Guide a safe review of recent mentions."""
        return (
            f"List up to {limit} unarchived mentions, summarize urgent items and likely actions, "
            "then ask before archiving anything or sending a Telegram reply."
        )

    return server


def run() -> None:
    create_stdio_server().run("stdio")
