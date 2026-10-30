import asyncio
import base64
import hashlib
import hmac
import ipaddress
import queue
import secrets
import socket
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .credentials import Credentials, CredentialStore


class OAuthLoginError(RuntimeError):
    pass


def _is_loopback_url(url: str) -> bool:
    try:
        return urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}
    except (TypeError, ValueError):
        return False


def _validate_url(url: str, *, allow_loopback: bool) -> None:
    if not isinstance(url, str):
        raise OAuthLoginError("OAuth discovery returned a non-string URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise OAuthLoginError("OAuth discovery returned an invalid URL") from error
    if not parsed.hostname or parsed.fragment or parsed.username or parsed.password:
        raise OAuthLoginError(
            "OAuth URLs must be absolute and cannot contain userinfo or fragments"
        )
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and allow_loopback and _is_loopback_url(url)
    ):
        raise OAuthLoginError("OAuth URLs must use HTTPS (loopback HTTP is development-only)")

    try:
        addresses = socket.getaddrinfo(parsed.hostname, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise OAuthLoginError(f"Could not resolve OAuth host: {parsed.hostname}") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        unsafe = (
            ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
        if unsafe and not (allow_loopback and ip.is_loopback):
            raise OAuthLoginError("OAuth discovery refused a private or reserved network address")


def _origin(url: str) -> tuple[str, str | None, int | None]:
    parsed = urlsplit(url)
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname, parsed.port or default_port


async def _get_json(url: str, *, allow_loopback: bool) -> dict:
    _validate_url(url, allow_loopback=allow_loopback)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.get(url, headers={"Accept": "application/json"})
    if response.is_redirect:
        raise OAuthLoginError("OAuth discovery redirects are not accepted")
    if response.status_code != 200:
        raise OAuthLoginError(f"OAuth discovery failed at {url} ({response.status_code})")
    try:
        payload = response.json()
    except ValueError as error:
        raise OAuthLoginError("OAuth discovery returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise OAuthLoginError("OAuth discovery metadata must be a JSON object")
    return payload


def _protected_resource_urls(resource: str) -> list[str]:
    parsed = urlsplit(resource)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    urls = [f"{origin}/.well-known/oauth-protected-resource{path}"]
    root = f"{origin}/.well-known/oauth-protected-resource"
    if root not in urls:
        urls.append(root)
    return urls


async def _discover(resource: str) -> tuple[dict, dict, bool]:
    allow_loopback = _is_loopback_url(resource)
    _validate_url(resource, allow_loopback=allow_loopback)
    protected_metadata = None
    last_error = None
    for metadata_url in _protected_resource_urls(resource):
        try:
            protected_metadata = await _get_json(metadata_url, allow_loopback=allow_loopback)
            break
        except OAuthLoginError as error:
            last_error = error
    if protected_metadata is None:
        raise last_error or OAuthLoginError("Protected resource metadata was not found")
    if protected_metadata.get("resource", "").rstrip("/") != resource.rstrip("/"):
        raise OAuthLoginError("Protected resource metadata identifies a different resource")

    authorization_servers = protected_metadata.get("authorization_servers")
    if (
        not isinstance(authorization_servers, list)
        or len(authorization_servers) != 1
        or not isinstance(authorization_servers[0], str)
    ):
        raise OAuthLoginError("Exactly one authorization server is required")
    issuer = authorization_servers[0]
    _validate_url(issuer, allow_loopback=allow_loopback)
    parsed = urlsplit(issuer)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    issuer_path = parsed.path.rstrip("/")
    metadata_urls = [f"{origin}/.well-known/oauth-authorization-server{issuer_path}"]
    if not issuer_path:
        metadata_urls.append(f"{origin}/.well-known/openid-configuration")

    server_metadata = None
    for metadata_url in metadata_urls:
        try:
            candidate = await _get_json(metadata_url, allow_loopback=allow_loopback)
        except OAuthLoginError:
            continue
        if candidate.get("issuer") == issuer:
            server_metadata = candidate
            break
    if server_metadata is None:
        raise OAuthLoginError("Authorization server metadata could not be validated")
    if "S256" not in server_metadata.get("code_challenge_methods_supported", []):
        raise OAuthLoginError("Authorization server does not advertise PKCE S256")
    for field in (
        "authorization_endpoint",
        "token_endpoint",
        "registration_endpoint",
        "revocation_endpoint",
    ):
        endpoint = server_metadata.get(field)
        if endpoint is None and field in {"registration_endpoint", "revocation_endpoint"}:
            continue
        _validate_url(endpoint, allow_loopback=allow_loopback)
        if _origin(endpoint) != _origin(issuer):
            raise OAuthLoginError(f"{field} must use the authorization server origin")
    return protected_metadata, server_metadata, allow_loopback


def _callback_server(result_queue: queue.Queue) -> tuple[HTTPServer, str]:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            result_queue.put({key: values[0] for key, values in query.items()})
            body = (
                b"<!doctype html><title>TG Flow connected</title>"
                b"<h1>TG Flow connected</h1><p>You can close this window.</p>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"
            )
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.timeout = 300
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    return server, redirect_uri


async def login_with_browser(
    store: CredentialStore,
    resource: str,
    api_url: str,
    scopes: str = "mentions:read mentions:write",
) -> Credentials:
    resource = resource.rstrip("/")
    api_url = api_url.rstrip("/")
    _, metadata, allow_loopback = await _discover(resource)
    _validate_url(api_url, allow_loopback=allow_loopback)
    if _origin(api_url) != _origin(resource):
        raise OAuthLoginError("The REST API and MCP resource must use the same origin")
    registration_endpoint = metadata.get("registration_endpoint")
    if not registration_endpoint:
        raise OAuthLoginError("Authorization server does not support dynamic client registration")
    _validate_url(registration_endpoint, allow_loopback=allow_loopback)

    result_queue: queue.Queue = queue.Queue(maxsize=1)
    callback_server, redirect_uri = _callback_server(result_queue)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        registration = await client.post(
            registration_endpoint,
            json={
                "client_name": "TG Flow CLI",
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "application_type": "native",
            },
        )
    if registration.status_code != 201:
        raise OAuthLoginError(f"Client registration failed ({registration.status_code})")
    try:
        registration_data = registration.json()
        client_id = registration_data["client_id"]
    except (KeyError, TypeError, ValueError) as error:
        raise OAuthLoginError("Client registration returned invalid metadata") from error
    if not isinstance(client_id, str) or not client_id:
        raise OAuthLoginError("Client registration returned an invalid client_id")

    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state = secrets.token_urlsafe(32)
    authorization_url = f"{metadata['authorization_endpoint']}?{
        urlencode(
            {
                'response_type': 'code',
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'scope': scopes,
                'resource': resource,
                'code_challenge': challenge,
                'code_challenge_method': 'S256',
                'state': state,
            }
        )
    }"

    if not webbrowser.open(authorization_url):
        print(f"Open this URL in a browser:\n{authorization_url}", file=sys.stderr)
    try:
        await asyncio.to_thread(callback_server.handle_request)
        try:
            callback = result_queue.get_nowait()
        except queue.Empty as error:
            raise OAuthLoginError("Authorization timed out") from error
    finally:
        callback_server.server_close()

    if callback.get("error"):
        raise OAuthLoginError(callback.get("error_description", callback["error"]))
    if not hmac.compare_digest(callback.get("state", ""), state):
        raise OAuthLoginError("OAuth state mismatch")
    expected_issuer = metadata["issuer"]
    if metadata.get("authorization_response_iss_parameter_supported") and not callback.get("iss"):
        raise OAuthLoginError("Authorization response did not include issuer identification")
    if callback.get("iss") and not hmac.compare_digest(callback["iss"], expected_issuer):
        raise OAuthLoginError("Authorization response issuer mismatch")
    if not callback.get("code"):
        raise OAuthLoginError("Authorization response did not include a code")

    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        token_response = await client.post(
            metadata["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": callback["code"],
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
                "resource": resource.rstrip("/"),
            },
        )
    if token_response.status_code != 200:
        raise OAuthLoginError(f"Token exchange failed ({token_response.status_code})")
    try:
        token_data = token_response.json()
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = int(token_data["expires_in"])
    except (KeyError, TypeError, ValueError) as error:
        raise OAuthLoginError("Token endpoint returned an invalid response") from error
    if not isinstance(access_token, str) or not isinstance(refresh_token, str) or expires_in <= 0:
        raise OAuthLoginError("Token endpoint returned invalid credentials")
    credentials = Credentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=int(time.time()) + expires_in,
        scope=token_data.get("scope", scopes),
        resource=resource,
        issuer=expected_issuer,
        client_id=client_id,
        token_endpoint=metadata["token_endpoint"],
        revocation_endpoint=metadata.get("revocation_endpoint"),
        api_url=api_url,
    )
    store.save(credentials)
    return credentials


async def revoke_and_logout(store: CredentialStore) -> None:
    credentials = store.load()
    try:
        if (
            credentials
            and credentials.revocation_endpoint
            and _origin(credentials.revocation_endpoint) == _origin(credentials.issuer)
        ):
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                await client.post(
                    credentials.revocation_endpoint,
                    data={
                        "token": credentials.refresh_token,
                        "token_type_hint": "refresh_token",
                        "client_id": credentials.client_id,
                    },
                )
    except (httpx.RequestError, TypeError, ValueError):
        pass
    finally:
        store.clear()
