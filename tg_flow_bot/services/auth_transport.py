import httpx

from config import settings


def auth_http_client() -> httpx.AsyncClient:
    if settings.AUTH_LOCAL_ASGI:
        from auth_project.asgi import application

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url=settings.OAUTH_ISSUER,
            timeout=settings.AUTH_API_TIMEOUT,
        )
    return httpx.AsyncClient(timeout=settings.AUTH_API_TIMEOUT)


def auth_url(remote_url: str, local_path: str) -> str:
    return local_path if settings.AUTH_LOCAL_ASGI else remote_url
