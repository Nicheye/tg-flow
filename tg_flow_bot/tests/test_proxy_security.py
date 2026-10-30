from ipaddress import ip_network
from pathlib import Path

import pytest
from django.test import override_settings
from django.core.asgi import get_asgi_application
from httpx import ASGITransport, AsyncClient

import main


@pytest.mark.parametrize(
    ("peer", "headers", "expected"),
    [
        ("198.51.100.10", {"X-Forwarded-Proto": "https"}, 301),
        ("172.30.0.2", {"X-Forwarded-Proto": "https"}, 200),
        ("172.30.0.2", {"X-Forwarded-Proto": "http"}, 301),
        ("172.30.0.2", {"X-Forwarded-Proto": "https, http"}, 301),
        ("172.30.0.3", {"X-Forwarded-Proto": "https"}, 301),
    ],
)
async def test_django_only_trusts_forwarded_proto_from_configured_peer(peer, headers, expected, monkeypatch):
    with override_settings(
        SECURE_SSL_REDIRECT=True,
        TRUSTED_PROXY_NETWORKS=(ip_network("172.30.0.2/32"),),
    ):
        monkeypatch.setattr(main, "django_app", get_asgi_application())
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=(peer, 12345)),
            base_url="http://localhost:8081",
        ) as client:
            response = await client.get("/.well-known/oauth-authorization-server", headers=headers)
    assert response.status_code == expected
    if expected == 301:
        assert response.headers["location"].startswith("https://localhost:8081/")


async def test_default_trusts_no_peer_and_direct_tls_still_works(monkeypatch):
    with override_settings(SECURE_SSL_REDIRECT=True, TRUSTED_PROXY_NETWORKS=()):
        monkeypatch.setattr(main, "django_app", get_asgi_application())
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=("127.0.0.1", 12345)),
            base_url="http://localhost:8081",
        ) as client:
            spoofed = await client.get(
                "/.well-known/oauth-authorization-server", headers={"X-Forwarded-Proto": "https"}
            )
        async with AsyncClient(
            transport=ASGITransport(app=main.app, client=("198.51.100.10", 12345)),
            base_url="https://localhost:8081",
        ) as client:
            direct_tls = await client.get("/.well-known/oauth-authorization-server")
    assert spoofed.status_code == 301
    assert direct_tls.status_code == 200


def test_docker_server_preserves_connecting_peer():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert '"--no-proxy-headers"' in dockerfile
