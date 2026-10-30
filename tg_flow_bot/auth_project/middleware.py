from ipaddress import ip_address

from django.conf import settings


class TrustedProxyMiddleware:
    """Discard forwarding claims unless the actual connecting peer is trusted."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            peer = ip_address(request.META.get("REMOTE_ADDR", ""))
            trusted = any(peer in network for network in settings.TRUSTED_PROXY_NETWORKS)
        except ValueError:
            trusted = False

        # Only accept one canonical value. Django otherwise accepts the first
        # entry of a comma-separated list, including merged duplicate headers.
        if not trusted or request.META.get("HTTP_X_FORWARDED_PROTO") not in ("http", "https"):
            request.META.pop("HTTP_X_FORWARDED_PROTO", None)
        return self.get_response(request)
