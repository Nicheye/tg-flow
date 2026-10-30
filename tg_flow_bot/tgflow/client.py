import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from .credentials import Credentials, CredentialStore


class ApiError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    def __init__(self, store: CredentialStore):
        self.store = store

    @staticmethod
    def _origin(url: str) -> tuple[str, str | None, int | None]:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname, port

    def _validate_destinations(self, credentials: Credentials) -> None:
        if self._origin(credentials.resource) != self._origin(credentials.api_url):
            raise ApiError(400, "Credential file has mismatched MCP and REST API origins")
        if self._origin(credentials.issuer) != self._origin(credentials.token_endpoint):
            raise ApiError(400, "Credential file has mismatched issuer and token endpoint origins")

    async def _refresh(self, credentials: Credentials) -> Credentials:
        self._validate_destinations(credentials)
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(
                credentials.token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": credentials.refresh_token,
                    "client_id": credentials.client_id,
                    "resource": credentials.resource,
                },
            )
        if response.status_code != 200:
            self.store.clear()
            raise ApiError(401, "Session expired. Run `tgflow auth login` again.")
        payload = response.json()
        refreshed = Credentials(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            expires_at=int(time.time()) + int(payload["expires_in"]),
            scope=payload.get("scope", credentials.scope),
            resource=credentials.resource,
            issuer=credentials.issuer,
            client_id=credentials.client_id,
            token_endpoint=credentials.token_endpoint,
            revocation_endpoint=credentials.revocation_endpoint,
            api_url=credentials.api_url,
        )
        self.store.save(refreshed)
        return refreshed

    async def credentials(self) -> Credentials:
        credentials = self.store.load()
        if credentials is None:
            raise ApiError(401, "Not signed in. Run `tgflow auth login`.")
        self._validate_destinations(credentials)
        if credentials.expires_at <= int(time.time()) + 30:
            credentials = await self._refresh(credentials)
        return credentials

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retry: bool = True,
    ) -> Any:
        credentials = await self.credentials()
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.request(
                method,
                f"{credentials.api_url.rstrip('/')}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {credentials.access_token}"},
            )
        if response.status_code == 401 and retry:
            await self._refresh(credentials)
            return await self.request(method, path, params=params, json=json, retry=False)
        if response.status_code >= 400:
            try:
                payload = response.json()
                message = payload.get("detail") or payload.get("error_description")
            except ValueError:
                message = None
            raise ApiError(
                response.status_code, str(message or f"API returned {response.status_code}")
            )
        if not response.content:
            return None
        return response.json()

    async def list_mentions(
        self,
        chat_id: int | None = None,
        include_archived: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "include_archived": include_archived,
            "limit": limit,
            "offset": offset,
        }
        if chat_id is not None:
            params["chat_id"] = chat_id
        return await self.request("GET", "/api/mentions/", params=params)

    async def stats(self) -> dict:
        return await self.request("GET", "/api/mentions/stats/")

    async def context(self, mention_id: int, before: int = 5, after: int = 5) -> dict:
        return await self.request(
            "GET",
            f"/api/mentions/{mention_id}/context",
            params={"before": before, "after": after},
        )

    async def archive(self, mention_id: int, archived: bool) -> dict:
        return await self.request(
            "PATCH",
            f"/api/mentions/{mention_id}",
            json={"is_archived": archived},
        )

    async def reply(self, mention_id: int, text: str) -> dict:
        return await self.request(
            "POST",
            f"/api/mentions/{mention_id}/reply",
            json={"text": text},
        )
