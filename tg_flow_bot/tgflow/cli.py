import asyncio
import json
from datetime import UTC, datetime
from typing import Annotated, Any

import typer

from .client import ApiClient, ApiError
from .credentials import CredentialStore
from .oauth_client import OAuthLoginError, login_with_browser, revoke_and_logout

app = typer.Typer(
    name="tgflow",
    help="Command-line and local MCP access to TG Flow mentions.",
    no_args_is_help=True,
)
auth_app = typer.Typer(help="Sign in and manage local OAuth credentials.", no_args_is_help=True)
mentions_app = typer.Typer(help="Read and triage Telegram mentions.", no_args_is_help=True)
mcp_app = typer.Typer(help="Run the local MCP stdio bridge.", no_args_is_help=True)
app.add_typer(auth_app, name="auth")
app.add_typer(mentions_app, name="mentions")
app.add_typer(mcp_app, name="mcp")


def _store() -> CredentialStore:
    return CredentialStore()


def _client() -> ApiClient:
    return ApiClient(_store())


def _output(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _run(coroutine):
    try:
        return asyncio.run(coroutine)
    except (ApiError, OAuthLoginError, RuntimeError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from error


@auth_app.command("login")
def auth_login(
    mcp_url: Annotated[
        str,
        typer.Option("--mcp-url", envvar="TGFLOW_MCP_URL", help="Canonical remote MCP URL."),
    ] = "http://localhost:8081/mcp",
    api_url: Annotated[
        str,
        typer.Option("--api-url", envvar="TGFLOW_API_URL", help="TG Flow REST API base URL."),
    ] = "http://localhost:8081",
    read_only: Annotated[
        bool,
        typer.Option("--read-only", help="Request only mentions:read."),
    ] = False,
) -> None:
    """Sign in through the OAuth 2.1 authorization-code flow with PKCE."""
    scopes = "mentions:read" if read_only else "mentions:read mentions:write"
    credentials = _run(login_with_browser(_store(), mcp_url, api_url, scopes))
    typer.echo(f"Signed in with scopes: {credentials.scope}")


@auth_app.command("logout")
def auth_logout() -> None:
    """Revoke the local refresh-token family and remove credentials."""
    _run(revoke_and_logout(_store()))
    typer.echo("Signed out.")


@auth_app.command("status")
def auth_status(
    verify: Annotated[
        bool,
        typer.Option("--verify/--no-verify", help="Call the API to verify or refresh the session."),
    ] = True,
) -> None:
    """Show local credential status without displaying any token."""
    credentials = _store().load()
    if credentials is None:
        typer.echo("Not signed in.")
        raise typer.Exit(1)
    result: dict[str, Any] = {
        "issuer": credentials.issuer,
        "resource": credentials.resource,
        "api_url": credentials.api_url,
        "scope": credentials.scope.split(),
        "expires_at": datetime.fromtimestamp(credentials.expires_at, UTC).isoformat(),
    }
    if verify:
        result["api"] = "ok"
        try:
            result["stats"] = _run(_client().stats())
        except typer.Exit:
            result["api"] = "unavailable"
            _output(result)
            raise
    _output(result)


@mentions_app.command("list")
def mentions_list(
    chat_id: Annotated[
        int | None, typer.Option("--chat-id", help="Filter by Telegram chat ID.")
    ] = None,
    include_archived: Annotated[
        bool, typer.Option("--include-archived", help="Include archived mentions.")
    ] = False,
    limit: Annotated[int, typer.Option(min=1, max=100)] = 20,
    offset: Annotated[int, typer.Option(min=0)] = 0,
) -> None:
    """List mentions newest first."""
    _output(_run(_client().list_mentions(chat_id, include_archived, limit, offset)))


@mentions_app.command("stats")
def mentions_stats() -> None:
    """Show unarchived and recent mention counts."""
    _output(_run(_client().stats()))


@mentions_app.command("context")
def mentions_context(
    mention_id: Annotated[int, typer.Argument(help="Mention ID.")],
    before: Annotated[int, typer.Option(min=0, max=50)] = 5,
    after: Annotated[int, typer.Option(min=0, max=50)] = 5,
) -> None:
    """Show messages before and after a mention."""
    _output(_run(_client().context(mention_id, before, after)))


@mentions_app.command("archive")
def mentions_archive(mention_id: Annotated[int, typer.Argument(help="Mention ID.")]) -> None:
    """Archive a mention."""
    _output(_run(_client().archive(mention_id, True)))


@mentions_app.command("restore")
def mentions_restore(mention_id: Annotated[int, typer.Argument(help="Mention ID.")]) -> None:
    """Restore an archived mention."""
    _output(_run(_client().archive(mention_id, False)))


@mentions_app.command("reply")
def mentions_reply(
    mention_id: Annotated[int, typer.Argument(help="Mention ID.")],
    text: Annotated[str, typer.Argument(help="Telegram reply text.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the send confirmation.")] = False,
) -> None:
    """Send a Telegram reply and archive the mention after success."""
    if not yes and not typer.confirm(f"Send this reply to mention {mention_id}?"):
        raise typer.Abort()
    _output(_run(_client().reply(mention_id, text)))


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Run the local MCP server over stdio using stored OAuth credentials."""
    if _store().load() is None:
        typer.echo("Error: run `tgflow auth login` first.", err=True)
        raise typer.Exit(1)
    from .stdio_server import run

    run()
