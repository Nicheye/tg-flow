import stat
import time

import pytest

from tgflow.client import ApiClient, ApiError
from tgflow.credentials import Credentials, CredentialStore
from tgflow.oauth_client import revoke_and_logout


def test_credential_store_uses_private_permissions(tmp_path):
    path = tmp_path / "config" / "tgflow" / "credentials.json"
    store = CredentialStore(path)
    credentials = Credentials(
        access_token="access",
        refresh_token="refresh",
        expires_at=1,
        scope="mentions:read",
        resource="https://api.example/mcp",
        issuer="https://auth.example/",
        client_id="client",
        token_endpoint="https://auth.example/oauth/token",
        revocation_endpoint="https://auth.example/oauth/revoke",
        api_url="https://api.example",
    )

    store.save(credentials)

    assert store.load() == credentials
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_api_client_rejects_mismatched_destination_before_sending(tmp_path):
    store = CredentialStore(tmp_path / "credentials.json")
    store.save(
        Credentials(
            access_token="access",
            refresh_token="refresh",
            expires_at=int(time.time()) + 3600,
            scope="mentions:read",
            resource="https://api.example/mcp",
            issuer="https://auth.example/",
            client_id="client",
            token_endpoint="https://auth.example/oauth/token",
            revocation_endpoint=None,
            api_url="https://attacker.example",
        )
    )

    with pytest.raises(ApiError, match="mismatched MCP and REST API origins"):
        await ApiClient(store).stats()


@pytest.mark.asyncio
async def test_logout_clears_credentials_even_with_invalid_revocation_url(tmp_path):
    store = CredentialStore(tmp_path / "credentials.json")
    store.save(
        Credentials(
            access_token="access",
            refresh_token="refresh",
            expires_at=int(time.time()) + 3600,
            scope="mentions:read",
            resource="https://api.example/mcp",
            issuer="https://auth.example/",
            client_id="client",
            token_endpoint="https://auth.example/oauth/token",
            revocation_endpoint="https://auth.example:invalid/oauth/revoke",
            api_url="https://api.example",
        )
    )

    await revoke_and_logout(store)

    assert store.load() is None
