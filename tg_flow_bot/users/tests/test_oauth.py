import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest

from users.models import OAuthAuthorizationCode, OAuthClient


@pytest.fixture
def oauth_client(db):
    return OAuthClient.objects.create(
        client_id="test-public-client",
        client_name="Test MCP Client",
        redirect_uris=["http://127.0.0.1:49152/callback"],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
    )


def pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def authorize_user(api_client, user, oauth_client, settings, scope="mentions:read"):
    verifier, challenge = pkce_pair()
    api_client.force_login(user)
    response = api_client.get(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": oauth_client.client_id,
            "redirect_uri": oauth_client.redirect_uris[0],
            "scope": scope,
            "resource": settings.MCP_RESOURCE_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "secure-client-state",
        },
    )
    assert response.status_code == 200
    request_id = api_client.session["oauth_request"]["request_id"]
    decision = api_client.post(
        "/oauth/authorize/decision",
        {"request_id": request_id, "decision": "allow"},
    )
    assert decision.status_code == 302
    query = parse_qs(urlsplit(decision["Location"]).query)
    assert query["state"] == ["secure-client-state"]
    assert query["iss"] == [settings.OAUTH_ISSUER]
    return query["code"][0], verifier


def exchange_code(api_client, oauth_client, settings, code, verifier):
    return api_client.post(
        "/oauth/token",
        {
            "grant_type": "authorization_code",
            "client_id": oauth_client.client_id,
            "code": code,
            "redirect_uri": oauth_client.redirect_uris[0],
            "resource": settings.MCP_RESOURCE_URI,
            "code_verifier": verifier,
        },
    )


def start_browser_authorization(client, oauth_client, settings):
    _, challenge = pkce_pair()
    return client.get("/oauth/authorize", {
        "response_type": "code", "client_id": oauth_client.client_id,
        "redirect_uri": oauth_client.redirect_uris[0], "resource": settings.MCP_RESOURCE_URI,
        "scope": "mentions:read", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": "browser-fixture-state",
    })


def test_web_session_uses_verified_jwt_subject_and_preserves_pending_consent(
    api_client, user, oauth_client, settings
):
    from rest_framework_simplejwt.tokens import RefreshToken

    assert start_browser_authorization(api_client, oauth_client, settings).status_code == 200
    pending = dict(api_client.session["oauth_request"])
    access = str(RefreshToken.for_user(user).access_token)
    response = api_client.post("/oauth/session/web", {"user_id": user.pk + 1},
                               format="json", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200
    assert api_client.session["_auth_user_id"] == str(user.pk)
    assert api_client.session["oauth_request"] == pending
    assert not OAuthAuthorizationCode.objects.exists(), "Login must not bypass consent"


@pytest.mark.parametrize("authorization", ["", "Bearer invalid-token"])
def test_web_session_rejects_missing_or_invalid_jwt(api_client, oauth_client, settings, authorization):
    start_browser_authorization(api_client, oauth_client, settings)
    response = api_client.post("/oauth/session/web", HTTP_AUTHORIZATION=authorization)
    assert response.status_code == 401
    assert "_auth_user_id" not in api_client.session


def test_web_session_requires_csrf(user, oauth_client, settings):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient(enforce_csrf_checks=True)
    start_browser_authorization(client, oauth_client, settings)
    access = str(RefreshToken.for_user(user).access_token)
    assert client.post("/oauth/session/web", HTTP_AUTHORIZATION=f"Bearer {access}").status_code == 403
    csrf = client.cookies["csrftoken"].value
    assert client.post("/oauth/session/web", HTTP_AUTHORIZATION=f"Bearer {access}",
                       HTTP_X_CSRFTOKEN=csrf).status_code == 200


def test_web_session_requires_pending_oauth_request(api_client, user):
    from rest_framework_simplejwt.tokens import RefreshToken

    access = str(RefreshToken.for_user(user).access_token)
    response = api_client.post("/oauth/session/web", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 400


def test_web_session_rejects_inactive_user(api_client, user, oauth_client, settings):
    from rest_framework_simplejwt.tokens import RefreshToken

    start_browser_authorization(api_client, oauth_client, settings)
    access = str(RefreshToken.for_user(user).access_token)
    user.is_active = False
    user.save()
    assert api_client.post("/oauth/session/web", HTTP_AUTHORIZATION=f"Bearer {access}").status_code == 401
    assert "_auth_user_id" not in api_client.session


def introspection_auth(settings):
    value = base64.b64encode(
        f"{settings.MCP_INTROSPECTION_CLIENT_ID}:{settings.MCP_INTROSPECTION_CLIENT_SECRET}".encode()
    ).decode()
    return f"Basic {value}"


def test_authorization_server_metadata(api_client, settings):
    response = api_client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.json()
    assert data["issuer"] == settings.OAUTH_ISSUER
    assert data["code_challenge_methods_supported"] == ["S256"]
    assert data["authorization_response_iss_parameter_supported"] is True
    assert data["client_id_metadata_document_supported"] is False


@pytest.mark.parametrize(
    ("redirect", "origin"),
    [
        ("https://chatgpt.com/connector_platform/oauth/callback?client=fixture", "https://chatgpt.com"),
        ("http://127.0.0.1:49152/callback", "http://127.0.0.1:49152"),
        ("http://[::1]:49152/callback", "http://[::1]:49152"),
    ],
)
def test_consent_csp_permits_only_the_registered_callback_origin(
    api_client, user, oauth_client, settings, redirect, origin
):
    oauth_client.redirect_uris = [redirect]
    oauth_client.save()
    api_client.force_login(user)
    _, challenge = pkce_pair()
    response = api_client.get("/oauth/authorize", {
        "response_type": "code", "client_id": oauth_client.client_id,
        "redirect_uri": redirect, "resource": settings.MCP_RESOURCE_URI,
        "scope": "mentions:read", "code_challenge": challenge,
        "code_challenge_method": "S256", "state": "fixture-state",
    })
    assert response.status_code == 200
    policy = re.search(
        r'http-equiv="Content-Security-Policy" content="([^"]+)"',
        response.content.decode(),
    ).group(1)
    assert policy.split("form-action ")[1] == f"'self' {origin}"


@pytest.mark.parametrize("redirect", [
    "https://example.com;form-action *;/callback",
    "https://example.com:invalid/callback",
])
def test_registration_rejects_invalid_csp_origins(api_client, redirect):
    response = api_client.post("/oauth/register", {
        "client_name": "Invalid origin", "redirect_uris": [redirect],
    }, format="json")
    assert response.status_code == 400


def test_dynamic_registration_accepts_loopback_public_client(db, api_client):
    response = api_client.post(
        "/oauth/register",
        data={
            "client_name": "CLI Test",
            "redirect_uris": ["http://127.0.0.1:54321/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["client_id"].startswith("tgflow_")
    assert "client_secret" not in response.json()


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://attacker.example/callback",
        "https://user:password@example.com/callback",
        "https://example.com/callback#fragment",
    ],
)
def test_dynamic_registration_rejects_unsafe_redirects(api_client, redirect_uri):
    response = api_client.post(
        "/oauth/register",
        data={"client_name": "Unsafe", "redirect_uris": [redirect_uri]},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"client_name": "Invalid", "redirect_uris": [{"uri": "https://example.com"}]},
        {
            "client_name": "Invalid",
            "redirect_uris": ["https://example.com/callback"],
            "grant_types": None,
        },
    ],
)
def test_dynamic_registration_rejects_malformed_metadata(api_client, payload):
    response = api_client.post("/oauth/register", data=payload, format="json")
    assert response.status_code == 400


def test_authorization_code_pkce_and_introspection(db, api_client, user, oauth_client, settings):
    code, verifier = authorize_user(
        api_client, user, oauth_client, settings, "mentions:read mentions:write"
    )
    response = exchange_code(api_client, oauth_client, settings, code, verifier)
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["scope"] == "mentions:read mentions:write"

    introspection = api_client.post(
        "/oauth/introspect",
        {"token": tokens["access_token"]},
        HTTP_AUTHORIZATION=introspection_auth(settings),
    )
    assert introspection.status_code == 200
    data = introspection.json()
    assert data["active"] is True
    assert data["sub"] == str(user.id)
    assert data["aud"] == settings.MCP_RESOURCE_URI


def test_authorization_code_is_single_use(db, api_client, user, oauth_client, settings):
    code, verifier = authorize_user(api_client, user, oauth_client, settings)
    assert exchange_code(api_client, oauth_client, settings, code, verifier).status_code == 200
    replay = exchange_code(api_client, oauth_client, settings, code, verifier)
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"
    assert OAuthAuthorizationCode.objects.get().consumed_at is not None


def test_pkce_verifier_mismatch_rejected(db, api_client, user, oauth_client, settings):
    code, _ = authorize_user(api_client, user, oauth_client, settings)
    wrong_verifier, _ = pkce_pair()
    response = exchange_code(api_client, oauth_client, settings, code, wrong_verifier)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_refresh_rotation_and_reuse_revokes_family(db, api_client, user, oauth_client, settings):
    code, verifier = authorize_user(api_client, user, oauth_client, settings)
    tokens = exchange_code(api_client, oauth_client, settings, code, verifier).json()
    refresh_request = {
        "grant_type": "refresh_token",
        "client_id": oauth_client.client_id,
        "refresh_token": tokens["refresh_token"],
        "resource": settings.MCP_RESOURCE_URI,
    }
    rotated = api_client.post("/oauth/token", refresh_request)
    assert rotated.status_code == 200
    rotated_tokens = rotated.json()
    assert rotated_tokens["refresh_token"] != tokens["refresh_token"]

    replay = api_client.post("/oauth/token", refresh_request)
    assert replay.status_code == 400
    assert replay.json()["error_description"] == "Refresh token reuse detected"

    introspection = api_client.post(
        "/oauth/introspect",
        {"token": rotated_tokens["access_token"]},
        HTTP_AUTHORIZATION=introspection_auth(settings),
    )
    assert introspection.json() == {"active": False}


def test_authorize_rejects_resource_mismatch(db, api_client, oauth_client):
    _, challenge = pkce_pair()
    response = api_client.get(
        "/oauth/authorize",
        {
            "response_type": "code",
            "client_id": oauth_client.client_id,
            "redirect_uri": oauth_client.redirect_uris[0],
            "scope": "mentions:read",
            "resource": "https://attacker.example/mcp",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "state",
        },
    )
    assert response.status_code == 302
    assert parse_qs(urlsplit(response["Location"]).query)["error"] == ["invalid_target"]


def test_introspection_requires_resource_server_auth(db, api_client):
    response = api_client.post("/oauth/introspect", {"token": "anything"})
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Basic realm="oauth-introspection"'


def test_introspection_rejects_malformed_basic_auth(db, api_client):
    response = api_client.post(
        "/oauth/introspect",
        {"token": "anything"},
        HTTP_AUTHORIZATION="Basic not-base64!",
    )
    assert response.status_code == 401
