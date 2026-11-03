from httpx import ASGITransport, AsyncClient
import pytest
from pydantic import ValidationError
from unittest.mock import Mock
import os
import subprocess
import shutil
import sys
from pathlib import Path
import hashlib
from datetime import timedelta
from asgiref.sync import sync_to_async
from django.utils import timezone

from config import Settings
from auth_project.startup import check_auth_migrations

from main import app
from services.auth_transport import auth_http_client


async def test_django_routes_and_mcp_discovery_coexist():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8081") as client:
        discovery = await client.get("/.well-known/oauth-authorization-server")
        protected = await client.get("/.well-known/oauth-protected-resource/mcp")
        auth = await client.get("/api/auth/me/")
        introspection = await client.post("/oauth/introspect", data={"token": "invalid"})
        mcp = await client.post("/mcp", json={})

    assert discovery.status_code == 200
    assert discovery.json()["issuer"] == "http://localhost:8081/"
    assert protected.status_code == 200
    assert auth.status_code == 401
    assert introspection.status_code == 401
    assert mcp.status_code == 401


async def test_local_introspection_still_requires_resource_server_credentials():
    async with auth_http_client() as client:
        response = await client.post("/oauth/introspect", data={"token": "invalid"})
    assert response.status_code == 401


async def test_development_auth_cors_allows_frontend():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8081") as client:
        response = await client.options(
            "/api/auth/telegram-auth/",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
        )
        actual = await client.get("/api/auth/me/", headers={"Origin": "http://localhost:5173"})
        untrusted = await client.get("/api/auth/me/", headers={"Origin": "https://attacker.example"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert actual.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in untrusted.headers
    from django.conf import settings as django_settings
    assert "http://localhost:5173" in django_settings.CSRF_TRUSTED_ORIGINS


def test_auth_make_targets_expand_network():
    root = Path(__file__).resolve().parents[1]
    if not shutil.which("make") or not (root / "envs/dev/env.op.example").exists():
        pytest.skip("Makefile validation requires make and the example env file")
    for target in ("auth-migrate", "auth-migration-status"):
        result = subprocess.run(
            ["make", "-n", target, "ENV_FILE=envs/dev/env.op.example"],
            cwd=root, capture_output=True, text=True, check=True,
        )
        assert "--network ${NETWORK:-flow_net}" in result.stdout


def test_remote_mode_starts_without_django_database(tmp_path):
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith("AUTH_DB_") and key != "DJANGO_SETTINGS_MODULE"
    }
    env.update({
        "AUTH_LOCAL_ASGI": "False",
        "AUTH_API_URL": "http://auth.example/api/auth",
        "OAUTH_INTROSPECTION_URL": "http://auth.example/oauth/introspect",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    })
    code = """
import asyncio
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
import main

assert 'auth_project.asgi' not in sys.modules
@asynccontextmanager
async def session():
    yield
main.mcp.session_manager.run = session
main.Tortoise.init = AsyncMock()
main.Tortoise.close_connections = AsyncMock()
bot = MagicMock()
bot.initialize = AsyncMock()
bot.start = AsyncMock()
bot.stop = AsyncMock()
bot.shutdown = AsyncMock()
bot.updater.start_polling = AsyncMock()
bot.updater.stop = AsyncMock()
main.create_bot_application = lambda: bot
async def run():
    async with main.lifespan(main.app):
        pass
asyncio.run(run())
bot.updater.start_polling.assert_awaited_once_with(allowed_updates=main.Update.ALL_TYPES, drop_pending_updates=False)
assert 'my_chat_member' in main.Update.ALL_TYPES
assert 'auth_project.asgi' not in sys.modules
assert 'auth_project.startup' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_auth_urls_require_an_explicit_transport_choice():
    with pytest.raises(ValidationError, match="Legacy auth URLs"):
        Settings(_env_file=None, AUTH_API_URL="https://old.example/api/auth")
    assert not Settings(
        _env_file=None, AUTH_API_URL="https://old.example/api/auth",
        OAUTH_INTROSPECTION_URL="https://old.example/oauth/introspect", AUTH_LOCAL_ASGI=False
    ).AUTH_LOCAL_ASGI
    with pytest.raises(ValidationError, match="Remote auth requires explicit URLs"):
        Settings(_env_file=None, AUTH_LOCAL_ASGI=False)
    assert Settings(
        _env_file=None, OAUTH_INTROSPECTION_URL="https://old.example/oauth/introspect",
        AUTH_LOCAL_ASGI=True
    ).AUTH_LOCAL_ASGI


def test_startup_rejects_pending_auth_migrations(monkeypatch):
    import auth_project.startup as startup

    executor = Mock()
    executor.migration_plan.return_value = [("users", "0001_initial")]
    monkeypatch.setattr(startup, "MigrationExecutor", lambda connection: executor)
    monkeypatch.setattr(startup, "connection", Mock(settings_dict={"ENGINE": "postgresql"}))
    with pytest.raises(RuntimeError, match="missing migrations"):
        check_auth_migrations()


def test_startup_does_not_create_missing_sqlite_database(monkeypatch, tmp_path):
    import auth_project.startup as startup

    path = tmp_path / "missing.sqlite3"
    monkeypatch.setattr(
        startup, "connection",
        Mock(settings_dict={"ENGINE": "django.db.backends.sqlite3", "NAME": str(path)}),
    )
    with pytest.raises(RuntimeError, match="does not exist"):
        check_auth_migrations()
    assert not path.exists()


def test_auth_database_cannot_fall_back_to_bot_database(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith("AUTH_DB_")}
    env.update({
        "DB_ENGINE": "postgresql", "DB_NAME": "bot_database",
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    })
    result = subprocess.run(
        [sys.executable, "-c", "import auth_project.settings"],
        env=env, cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "Set AUTH_DB_ENGINE" in result.stderr


@pytest.mark.django_db(transaction=True)
async def test_local_token_verification_preserves_audience_scopes_and_revocation():
    from config import settings
    from mcp_server import AuthServiceTokenVerifier
    from services.security import verify_token
    from users.models import OAuthAccessToken, OAuthClient, User

    def create_token():
        user = User.objects.create_user(username="integration-user", tg_user_id=100001)
        client = OAuthClient.objects.create(client_id="integration-client", client_name="Test")
        return OAuthAccessToken.objects.create(
            token_digest=hashlib.sha256(b"integration-token").hexdigest(),
            client=client, user=user, resource=settings.MCP_RESOURCE_URI,
            scope="mentions:read", expires_at=timezone.now() + timedelta(minutes=5),
        )

    token = await sync_to_async(create_token)()
    verifier = AuthServiceTokenVerifier()
    identity = await verify_token("integration-token")
    mcp_identity = await verifier.verify_token("integration-token")
    assert identity is not None and identity.scopes == ["mentions:read"]
    assert mcp_identity is not None and mcp_identity.scopes == ["mentions:read"]
    token.resource = "https://wrong.example/mcp"
    await sync_to_async(token.save)()
    assert await verify_token("integration-token") is None
    assert await verifier.verify_token("integration-token") is None
    token.resource = settings.MCP_RESOURCE_URI
    token.revoked_at = timezone.now()
    await sync_to_async(token.save)()
    assert await verifier.verify_token("integration-token") is None
