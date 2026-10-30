from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import settings
from services.auth_transport import auth_http_client, auth_url

security = HTTPBearer(auto_error=False)


class TokenPayload:
    def __init__(
        self,
        user_id: int,
        tg_user_id: int | None = None,
        scopes: list[str] | None = None,
        client_id: str | None = None,
    ):
        self.user_id = user_id
        self.tg_user_id = tg_user_id
        self.scopes = scopes or []
        self.client_id = client_id


def protected_resource_metadata_url() -> str:
    resource = urlsplit(settings.MCP_RESOURCE_URI)
    path = resource.path.rstrip("/")
    return f"{resource.scheme}://{resource.netloc}/.well-known/oauth-protected-resource{path}"


async def verify_token(token: str) -> TokenPayload | None:
    """
    Verify JWT token via Auth Service.

    GET /api/auth/me/ with Authorization header
    """
    try:
        async with auth_http_client() as client:
            introspection = await client.post(
                auth_url(settings.OAUTH_INTROSPECTION_URL, "/oauth/introspect"),
                data={"token": token},
                auth=(
                    settings.MCP_INTROSPECTION_CLIENT_ID,
                    settings.MCP_INTROSPECTION_CLIENT_SECRET,
                ),
            )
            if introspection.status_code == 200:
                try:
                    oauth_data = introspection.json()
                except ValueError:
                    return None
                if not isinstance(oauth_data, dict):
                    return None
                if oauth_data.get("active"):
                    audience = oauth_data.get("aud") or oauth_data.get("resource")
                    if audience != settings.MCP_RESOURCE_URI:
                        return None
                    try:
                        user_id = int(oauth_data["sub"])
                        scope = oauth_data.get("scope", "")
                        if not isinstance(scope, str):
                            return None
                        return TokenPayload(
                            user_id=user_id,
                            scopes=scope.split(),
                            client_id=oauth_data.get("client_id"),
                        )
                    except (KeyError, TypeError, ValueError):
                        return None

            response = await client.get(
                auth_url(f"{settings.AUTH_API_URL}/me/", "/api/auth/me/"),
                headers={"Authorization": f"Bearer {token}"},
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                    if not isinstance(data, dict):
                        return None
                    return TokenPayload(
                        user_id=int(data["id"]),
                        tg_user_id=int(data["tg_user_id"]),
                        scopes=["mentions:read", "mentions:write"],
                        client_id="tg-flow-web",
                    )
                except (KeyError, TypeError, ValueError):
                    return None
            return None

    except httpx.RequestError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> TokenPayload:
    """
    FastAPI dependency to get current authenticated user.

    Usage:
        @app.get("/protected")
        async def protected(user: TokenPayload = Depends(get_current_user)):
            return {"user_id": user.user_id}
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={
                "WWW-Authenticate": (
                    f'Bearer resource_metadata="{protected_resource_metadata_url()}", '
                    'scope="mentions:read"'
                )
            },
        )

    token = credentials.credentials

    payload = await verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={
                "WWW-Authenticate": (
                    'Bearer error="invalid_token", '
                    f'resource_metadata="{protected_resource_metadata_url()}", '
                    'scope="mentions:read"'
                )
            },
        )

    return payload


def require_scopes(*required_scopes: str) -> Callable:
    async def dependency(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        missing = [scope for scope in required_scopes if scope not in user.scopes]
        if missing:
            scope_value = " ".join(required_scopes)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required scope: {scope_value}",
                headers={
                    "WWW-Authenticate": (
                        'Bearer error="insufficient_scope", '
                        f'scope="{scope_value}", '
                        f'resource_metadata="{protected_resource_metadata_url()}"'
                    )
                },
            )
        return user

    return dependency


get_current_user_read = require_scopes("mentions:read")
get_current_user_write = require_scopes("mentions:write")
