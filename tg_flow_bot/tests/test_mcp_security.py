from http import HTTPStatus

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AccessToken
from mcp.server.transport_security import TransportSecuritySettings

import main as bot_main
from mcp_server import ToolScopeMiddleware
from models import ChatMessage

app = bot_main.app


class StaticVerifier:
    def __init__(self, scopes: list[str]):
        self.scopes = scopes

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != "valid-token":
            return None
        return AccessToken(
            token=token,
            client_id="test-client",
            scopes=self.scopes,
            subject="1",
            resource="http://localhost:8081/mcp",
        )


async def success_app(scope, receive, send):
    await send(
        {
            "type": "http.response.start",
            "status": HTTPStatus.OK,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": b"{}"})


def secured_app(scopes: list[str]):
    return ToolScopeMiddleware(
        success_app,
        StaticVerifier(scopes),
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["localhost:*"],
            allowed_origins=["http://localhost:*"],
        ),
    )


@pytest.mark.asyncio
async def test_protected_resource_metadata_and_auth_challenge():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8081"
    ) as client:
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        unauthorized = await client.post("/mcp", json={})

    assert metadata.status_code == HTTPStatus.OK
    assert metadata.json()["resource"] == "http://localhost:8081/mcp"
    assert metadata.json()["authorization_servers"] == ["http://localhost:8081/"]
    assert metadata.json()["scopes_supported"] == ["mentions:read", "mentions:write"]
    assert unauthorized.status_code == HTTPStatus.UNAUTHORIZED
    challenge = unauthorized.headers["www-authenticate"]
    assert 'scope="mentions:read"' in challenge
    assert (
        'resource_metadata="http://localhost:8081/.well-known/oauth-protected-resource/mcp"'
        in challenge
    )


@pytest.mark.asyncio
async def test_transport_security_precedes_authentication():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8081"
    ) as client:
        invalid_origin = await client.post(
            "/mcp", json={}, headers={"Origin": "https://attacker.example"}
        )
        invalid_host = await client.post("/mcp", json={}, headers={"Host": "attacker.example"})

    assert invalid_origin.status_code == HTTPStatus.FORBIDDEN
    assert invalid_host.status_code == HTTPStatus.MISDIRECTED_REQUEST


@pytest.mark.asyncio
async def test_write_tool_returns_incremental_scope_challenge():
    middleware = secured_app(["mentions:read"])
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://localhost:8081"
    ) as client:
        response = await client.post(
            "/mcp",
            json={},
            headers={
                "Authorization": "Bearer valid-token",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "reply_to_mention",
            },
        )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"] == "insufficient_scope"
    assert 'scope="mentions:write"' in response.headers["www-authenticate"]


@pytest.mark.asyncio
async def test_read_request_requires_read_scope():
    middleware = secured_app(["mentions:write"])
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://localhost:8081"
    ) as client:
        response = await client.post(
            "/mcp", json={}, headers={"Authorization": "Bearer valid-token"}
        )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert 'scope="mentions:read"' in response.headers["www-authenticate"]


@pytest.mark.asyncio
async def test_valid_read_request_reaches_mcp_application():
    middleware = secured_app(["mentions:read"])
    async with AsyncClient(
        transport=ASGITransport(app=middleware), base_url="http://localhost:8081"
    ) as client:
        response = await client.post(
            "/mcp", json={}, headers={"Authorization": "Bearer valid-token"}
        )

    assert response.status_code == HTTPStatus.OK


@pytest.mark.asyncio
async def test_mcp_2026_07_28_lists_tools_and_enforces_full_chat_mode(
    monkeypatch, subscription
):
    owned_chat = await subscription.chat
    async def verify(token: str):
        return AccessToken(
            token=token,
            client_id="test-client",
            scopes=["mentions:read"],
            subject="1",
            resource="http://localhost:8081/mcp",
        )

    monkeypatch.setattr(bot_main.mcp_token_verifier, "verify_token", verify)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "test-client",
                    "version": "1.0",
                },
            }
        },
    }
    headers = {
        "Authorization": "Bearer valid-token",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": "tools/list",
    }

    async with bot_main.mcp.session_manager.run():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://localhost:8081"
        ) as client:
            response = await client.post("/mcp", json=payload, headers=headers)

            async def call_tool(name: str, arguments: dict):
                call_headers = {
                    **headers,
                    "Mcp-Method": "tools/call",
                    "Mcp-Name": name,
                }
                call_payload = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments,
                        "_meta": payload["params"]["_meta"],
                    },
                }
                return await client.post("/mcp", json=call_payload, headers=call_headers)

            subscriptions = await call_tool("list_chat_subscriptions", {})
            denied = await call_tool(
                "list_chat_messages", {"chat_id": subscription.chat_id}
            )
            invalid_limit = await call_tool(
                "list_chat_messages",
                {"chat_id": subscription.chat_id, "limit": 0},
            )
            not_owned = await call_tool("list_chat_messages", {"chat_id": -999999})

            subscription.capture_mode = "full"
            await subscription.save(update_fields=("capture_mode",))
            for message_id in (100, 200):
                await ChatMessage.create(
                    chat_id=subscription.chat_id,
                    message_id=message_id,
                    from_user_id=10,
                    text=f"visible full-feed message {message_id}",
                    message_date=subscription.capture_mode_changed_at,
                )
            allowed = await call_tool(
                "list_chat_messages", {"chat_id": subscription.chat_id}
            )
            paginated = await call_tool(
                "list_chat_messages",
                {"chat_id": subscription.chat_id, "before_message_id": 200},
            )

    assert response.status_code == HTTPStatus.OK
    tool_names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert tool_names == {
        "list_mentions",
        "list_chat_subscriptions",
        "list_chat_messages",
        "get_mention_stats",
        "get_mention_context",
        "archive_mention",
        "reply_to_mention",
    }
    assert denied.status_code == HTTPStatus.OK
    assert denied.json()["result"]["isError"] is True
    assert "Full-chat mode is not enabled" in str(denied.json())
    assert owned_chat.title in str(subscriptions.json())
    assert "limit must be between 1 and 200" in str(invalid_limit.json())
    assert "Chat subscription not found" in str(not_owned.json())
    assert allowed.status_code == HTTPStatus.OK
    assert not allowed.json()["result"].get("isError", False)
    assert "visible full-feed message 100" in str(allowed.json())
    assert "visible full-feed message 200" in str(allowed.json())
    assert "visible full-feed message 100" in str(paginated.json())
    assert "visible full-feed message 200" not in str(paginated.json())
