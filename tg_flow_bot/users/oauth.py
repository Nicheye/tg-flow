import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import timedelta
from ipaddress import IPv6Address
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import login
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
)
from .serializers import TelegramAuthSerializer

READ_SCOPE = "mentions:read"
WRITE_SCOPE = "mentions:write"
ALLOWED_SCOPES = frozenset((READ_SCOPE, WRITE_SCOPE))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _random_token() -> str:
    return secrets.token_urlsafe(48)


def _scope_set(value: str) -> set[str]:
    return {scope for scope in value.split() if scope}


def _scope_string(scopes: set[str]) -> str:
    return " ".join(scope for scope in (READ_SCOPE, WRITE_SCOPE) if scope in scopes)


def _no_store(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _oauth_error(error: str, description: str, status: int = 400) -> JsonResponse:
    return _no_store(
        JsonResponse({"error": error, "error_description": description}, status=status)
    )


def _redirect_error(
    redirect_uri: str,
    error: str,
    description: str,
    state: str = "",
) -> HttpResponse:
    params = {"error": error, "error_description": description, "iss": settings.OAUTH_ISSUER}
    if state:
        params["state"] = state
    separator = "&" if "?" in redirect_uri else "?"
    return redirect(f"{redirect_uri}{separator}{urlencode(params)}")


def _is_loopback(hostname: str | None) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _redirect_csp_source(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Invalid redirect origin")
    host = parsed.hostname.encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{IPv6Address(host)}]"
    elif not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise ValueError("Invalid redirect hostname")
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{host}{port}"


def _valid_redirect_uri(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if (
            not parsed.scheme
            or not parsed.hostname
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            return False
        _redirect_csp_source(value)
        if parsed.scheme == "https":
            return True
        return parsed.scheme == "http" and _is_loopback(parsed.hostname)
    except ValueError:
        return False


def _client_ip(request: HttpRequest) -> str:
    return request.META.get("REMOTE_ADDR", "unknown")


def _registration_rate_limited(request: HttpRequest) -> bool:
    key = f"oauth-dcr:{_digest(_client_ip(request))}"
    if cache.add(key, 1, timeout=3600):
        return False
    try:
        return cache.incr(key) > 20
    except ValueError:
        cache.set(key, 1, timeout=3600)
        return False


def _authorization_request(
    request: HttpRequest,
) -> tuple[OAuthClient | None, dict, HttpResponse | None]:
    params = request.GET
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    state = params.get("state", "")
    client = OAuthClient.objects.filter(client_id=client_id, is_active=True).first()

    if client is None:
        return None, {}, _oauth_error("invalid_request", "Unknown or inactive client_id")
    if redirect_uri not in client.redirect_uris:
        return (
            client,
            {},
            _oauth_error("invalid_request", "redirect_uri does not exactly match registration"),
        )

    def fail(error: str, description: str) -> tuple[OAuthClient, dict, HttpResponse]:
        return client, {}, _redirect_error(redirect_uri, error, description, state)

    if params.get("response_type") != "code":
        return fail("unsupported_response_type", "Only response_type=code is supported")
    if params.get("code_challenge_method") != "S256":
        return fail("invalid_request", "PKCE code_challenge_method must be S256")

    challenge = params.get("code_challenge", "")
    if not 43 <= len(challenge) <= 128:
        return fail("invalid_request", "A valid PKCE code_challenge is required")

    resource = params.get("resource", "")
    if not hmac.compare_digest(resource, settings.MCP_RESOURCE_URI):
        return fail("invalid_target", "resource must identify the TG Flow MCP server")

    scopes = _scope_set(params.get("scope", READ_SCOPE))
    if READ_SCOPE not in scopes or not scopes.issubset(ALLOWED_SCOPES):
        return fail("invalid_scope", "Requested scopes are not supported")

    values = {
        "request_id": secrets.token_urlsafe(24),
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "resource": resource,
        "scope": _scope_string(scopes),
        "state": state,
        "code_challenge": challenge,
        "created_at": int(timezone.now().timestamp()),
    }
    return client, values, None


@require_GET
def authorization_server_metadata(request: HttpRequest) -> JsonResponse:
    issuer = settings.OAUTH_ISSUER
    base_url = issuer.rstrip("/")
    return JsonResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "registration_endpoint": f"{base_url}/oauth/register",
            "revocation_endpoint": f"{base_url}/oauth/revoke",
            "introspection_endpoint": f"{base_url}/oauth/introspect",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [READ_SCOPE, WRITE_SCOPE],
            "authorization_response_iss_parameter_supported": True,
            "client_id_metadata_document_supported": False,
        }
    )


@csrf_exempt
@require_POST
def register_client(request: HttpRequest) -> JsonResponse:
    if _registration_rate_limited(request):
        response = _oauth_error("temporarily_unavailable", "Registration rate limit exceeded", 429)
        response["Retry-After"] = "3600"
        return response

    if request.content_type != "application/json":
        return _oauth_error("invalid_client_metadata", "Content-Type must be application/json")
    try:
        payload = json.loads(request.body)
    except (TypeError, json.JSONDecodeError):
        return _oauth_error("invalid_client_metadata", "Request body must be valid JSON")
    if not isinstance(payload, dict):
        return _oauth_error("invalid_client_metadata", "Request body must be a JSON object")

    raw_client_name = payload.get("client_name")
    client_name = raw_client_name.strip() if isinstance(raw_client_name, str) else ""
    redirect_uris = payload.get("redirect_uris")
    grant_types = payload.get("grant_types", ["authorization_code", "refresh_token"])
    response_types = payload.get("response_types", ["code"])
    auth_method = payload.get("token_endpoint_auth_method", "none")

    if not client_name or len(client_name) > 255:
        return _oauth_error("invalid_client_metadata", "client_name is required")
    redirect_uris_valid = (
        isinstance(redirect_uris, list)
        and 1 <= len(redirect_uris) <= 10
        and all(isinstance(uri, str) for uri in redirect_uris)
        and len(set(redirect_uris)) == len(redirect_uris)
        and all(_valid_redirect_uri(uri) for uri in redirect_uris)
    )
    if not redirect_uris_valid:
        return _oauth_error(
            "invalid_redirect_uri",
            "redirect_uris must be unique HTTPS or loopback HTTP URLs without fragments",
        )
    if not isinstance(grant_types, list) or not all(
        isinstance(grant_type, str) for grant_type in grant_types
    ):
        return _oauth_error("invalid_client_metadata", "grant_types must be a string array")
    if set(grant_types) - {"authorization_code", "refresh_token"}:
        return _oauth_error("invalid_client_metadata", "Unsupported grant_type")
    if response_types != ["code"] or auth_method != "none":
        return _oauth_error(
            "invalid_client_metadata", "Only public authorization-code clients are supported"
        )

    client = OAuthClient.objects.create(
        client_id=f"tgflow_{secrets.token_urlsafe(24)}",
        client_name=client_name,
        redirect_uris=redirect_uris,
        grant_types=grant_types,
        response_types=response_types,
        token_endpoint_auth_method=auth_method,
    )
    return _no_store(
        JsonResponse(
            {
                "client_id": client.client_id,
                "client_id_issued_at": int(client.created_at.timestamp()),
                "client_name": client.client_name,
                "redirect_uris": client.redirect_uris,
                "grant_types": client.grant_types,
                "response_types": client.response_types,
                "token_endpoint_auth_method": client.token_endpoint_auth_method,
            },
            status=201,
        )
    )


@ensure_csrf_cookie
@require_GET
def authorize(request: HttpRequest) -> HttpResponse:
    client, values, error_response = _authorization_request(request)
    if error_response is not None:
        return error_response

    try:
        redirect_csp_source = _redirect_csp_source(values["redirect_uri"])
    except (ValueError, UnicodeError):
        return _oauth_error("invalid_request", "Registered redirect origin is invalid")
    request.session["oauth_request"] = values
    request.session.modified = True
    context = {
        "client": client,
        "scopes": values["scope"].split(),
        "redirect_uri": values["redirect_uri"],
        "redirect_csp_source": redirect_csp_source,
        "redirect_host": urlsplit(values["redirect_uri"]).hostname,
        "loopback_redirect": _is_loopback(urlsplit(values["redirect_uri"]).hostname),
        "request_id": values["request_id"],
        "telegram_bot_username": settings.TELEGRAM_BOT_USERNAME,
    }
    if request.user.is_authenticated:
        return _no_store(render(request, "oauth/consent.html", context))
    return _no_store(render(request, "oauth/login.html", context))


@csrf_protect
@require_POST
def authorize_decision(request: HttpRequest) -> HttpResponse:
    values = request.session.pop("oauth_request", None)
    if not values or not hmac.compare_digest(
        str(values.get("request_id", "")), request.POST.get("request_id", "")
    ):
        return _oauth_error("invalid_request", "Authorization request expired or does not match")
    if int(timezone.now().timestamp()) - int(values["created_at"]) > 600:
        return _oauth_error("invalid_request", "Authorization request expired")

    client = OAuthClient.objects.filter(client_id=values["client_id"], is_active=True).first()
    if client is None or values["redirect_uri"] not in client.redirect_uris:
        return _oauth_error("invalid_request", "OAuth client is no longer valid")
    if not request.user.is_authenticated:
        return _oauth_error("access_denied", "Authentication is required", 401)
    if request.POST.get("decision") != "allow":
        return _redirect_error(
            values["redirect_uri"], "access_denied", "The user denied the request", values["state"]
        )

    scopes = values["scope"].split()
    OAuthGrant.objects.update_or_create(
        user=request.user,
        client=client,
        defaults={"scopes": scopes},
    )
    raw_code = _random_token()
    OAuthAuthorizationCode.objects.create(
        code_digest=_digest(raw_code),
        client=client,
        user=request.user,
        redirect_uri=values["redirect_uri"],
        resource=values["resource"],
        scope=values["scope"],
        code_challenge=values["code_challenge"],
        expires_at=timezone.now()
        + timedelta(seconds=settings.OAUTH_AUTHORIZATION_CODE_LIFETIME_SECONDS),
    )
    params = {"code": raw_code, "iss": settings.OAUTH_ISSUER}
    if values["state"]:
        params["state"] = values["state"]
    separator = "&" if "?" in values["redirect_uri"] else "?"
    return redirect(f"{values['redirect_uri']}{separator}{urlencode(params)}")


@csrf_protect
@require_POST
def telegram_session(request: HttpRequest) -> JsonResponse:
    try:
        payload = json.loads(request.body)
    except (TypeError, json.JSONDecodeError):
        return JsonResponse({"detail": "Invalid JSON"}, status=400)
    serializer = TelegramAuthSerializer(data=payload)
    if not serializer.is_valid():
        return JsonResponse({"detail": serializer.errors}, status=400)
    login(
        request,
        serializer.validated_data["user"],
        backend="django.contrib.auth.backends.ModelBackend",
    )
    return JsonResponse({"ok": True})


@csrf_protect
@require_POST
def web_session(request: HttpRequest) -> JsonResponse:
    if not request.session.get("oauth_request"):
        return JsonResponse({"detail": "Start authorization from your MCP client first"}, status=400)
    try:
        identity = JWTAuthentication().authenticate(request)
    except AuthenticationFailed:
        identity = None
    if identity is None:
        return JsonResponse({"detail": "A valid website access token is required"}, status=401)
    user, _ = identity
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return JsonResponse({"ok": True})


def _issue_tokens(
    client: OAuthClient,
    user,
    resource: str,
    scope: str,
    family_id: uuid.UUID | None = None,
) -> dict:
    now = timezone.now()
    family = family_id or uuid.uuid4()
    raw_access = _random_token()
    raw_refresh = _random_token()
    OAuthAccessToken.objects.create(
        token_digest=_digest(raw_access),
        family_id=family,
        client=client,
        user=user,
        resource=resource,
        scope=scope,
        expires_at=now + timedelta(seconds=settings.OAUTH_ACCESS_TOKEN_LIFETIME_SECONDS),
    )
    OAuthRefreshToken.objects.create(
        token_digest=_digest(raw_refresh),
        family_id=family,
        client=client,
        user=user,
        resource=resource,
        scope=scope,
        expires_at=now + timedelta(seconds=settings.OAUTH_REFRESH_TOKEN_LIFETIME_SECONDS),
    )
    return {
        "access_token": raw_access,
        "refresh_token": raw_refresh,
        "token_type": "Bearer",
        "expires_in": settings.OAUTH_ACCESS_TOKEN_LIFETIME_SECONDS,
        "scope": scope,
    }


def _verify_pkce(verifier: str, challenge: str) -> bool:
    if not 43 <= len(verifier) <= 128:
        return False
    calculated = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return hmac.compare_digest(calculated.decode(), challenge)


@csrf_exempt
@require_POST
def token(request: HttpRequest) -> JsonResponse:
    grant_type = request.POST.get("grant_type", "")
    client = OAuthClient.objects.filter(
        client_id=request.POST.get("client_id", ""), is_active=True
    ).first()
    if client is None:
        return _oauth_error("invalid_client", "Unknown or inactive client", 401)

    if grant_type == "authorization_code":
        with transaction.atomic():
            code = (
                OAuthAuthorizationCode.objects.select_for_update()
                .select_related("user", "client")
                .filter(code_digest=_digest(request.POST.get("code", "")))
                .first()
            )
            now = timezone.now()
            if (
                code is None
                or code.consumed_at is not None
                or code.expires_at <= now
                or code.client_id != client.id
                or code.redirect_uri != request.POST.get("redirect_uri", "")
                or code.resource != request.POST.get("resource", "")
                or not _verify_pkce(request.POST.get("code_verifier", ""), code.code_challenge)
            ):
                return _oauth_error("invalid_grant", "Authorization code is invalid or expired")
            code.consumed_at = now
            code.save(update_fields=("consumed_at",))
            response_data = _issue_tokens(client, code.user, code.resource, code.scope)
        return _no_store(JsonResponse(response_data))

    if grant_type == "refresh_token":
        with transaction.atomic():
            refresh = (
                OAuthRefreshToken.objects.select_for_update()
                .select_related("user", "client")
                .filter(token_digest=_digest(request.POST.get("refresh_token", "")))
                .first()
            )
            now = timezone.now()
            if refresh is None or refresh.client_id != client.id:
                return _oauth_error("invalid_grant", "Refresh token is invalid")
            if refresh.used_at is not None or refresh.revoked_at is not None:
                OAuthRefreshToken.objects.filter(family_id=refresh.family_id).update(revoked_at=now)
                OAuthAccessToken.objects.filter(family_id=refresh.family_id).update(revoked_at=now)
                return _oauth_error("invalid_grant", "Refresh token reuse detected")
            if refresh.expires_at <= now:
                refresh.revoked_at = now
                refresh.save(update_fields=("revoked_at",))
                return _oauth_error("invalid_grant", "Refresh token has expired")
            if refresh.resource != request.POST.get("resource", ""):
                return _oauth_error("invalid_target", "resource does not match the token audience")

            requested_scopes = _scope_set(request.POST.get("scope", refresh.scope))
            if not requested_scopes.issubset(_scope_set(refresh.scope)):
                return _oauth_error("invalid_scope", "Refresh cannot increase token scope")
            refresh.used_at = now
            refresh.revoked_at = now
            refresh.save(update_fields=("used_at", "revoked_at"))
            response_data = _issue_tokens(
                client,
                refresh.user,
                refresh.resource,
                _scope_string(requested_scopes),
                family_id=refresh.family_id,
            )
        return _no_store(JsonResponse(response_data))

    return _oauth_error("unsupported_grant_type", "Unsupported grant_type")


def _valid_introspection_credentials(request: HttpRequest) -> bool:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode()
        client_id, client_secret = decoded.split(":", 1)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(
        client_id, settings.MCP_INTROSPECTION_CLIENT_ID
    ) and hmac.compare_digest(client_secret, settings.MCP_INTROSPECTION_CLIENT_SECRET)


@csrf_exempt
@require_POST
def introspect(request: HttpRequest) -> JsonResponse:
    if not _valid_introspection_credentials(request):
        response = _oauth_error("invalid_client", "Resource server authentication failed", 401)
        response["WWW-Authenticate"] = 'Basic realm="oauth-introspection"'
        return response

    access = (
        OAuthAccessToken.objects.select_related("user", "client")
        .filter(token_digest=_digest(request.POST.get("token", "")))
        .first()
    )
    now = timezone.now()
    if access is None or access.revoked_at is not None or access.expires_at <= now:
        return _no_store(JsonResponse({"active": False}))
    return _no_store(
        JsonResponse(
            {
                "active": True,
                "client_id": access.client.client_id,
                "sub": str(access.user_id),
                "scope": access.scope,
                "aud": access.resource,
                "resource": access.resource,
                "token_type": "Bearer",
                "iat": int(access.created_at.timestamp()),
                "exp": int(access.expires_at.timestamp()),
            }
        )
    )


@csrf_exempt
@require_POST
def revoke(request: HttpRequest) -> JsonResponse:
    client = OAuthClient.objects.filter(
        client_id=request.POST.get("client_id", ""), is_active=True
    ).first()
    if client is None:
        return _oauth_error("invalid_client", "Unknown or inactive client", 401)
    digest = _digest(request.POST.get("token", ""))
    now = timezone.now()
    refresh = OAuthRefreshToken.objects.filter(token_digest=digest, client=client).first()
    if refresh:
        OAuthRefreshToken.objects.filter(family_id=refresh.family_id).update(revoked_at=now)
        OAuthAccessToken.objects.filter(family_id=refresh.family_id).update(revoked_at=now)
    else:
        OAuthAccessToken.objects.filter(token_digest=digest, client=client).update(revoked_at=now)
    return _no_store(JsonResponse({}))
