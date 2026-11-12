"""Minimal HTTPS client for official APIs: fixed host allowlist, no redirects to
other hosts, timeouts and a response-size cap. Secrets never appear in errors."""

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import UpstreamError

ALLOWED_HOSTS = {"www.googleapis.com", "www.reddit.com", "oauth.reddit.com"}
MAX_BYTES = 2_000_000
TIMEOUT = 10


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect becomes an HTTPError instead of being followed


_opener = urllib.request.build_opener(_NoRedirect)


def request_json(url, headers=None, data=None, opener=None):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise UpstreamError("blocked_host", "Refusing to contact a host outside the official API allowlist.")
    request = urllib.request.Request(url, data=data, headers={"Accept": "application/json", **(headers or {})})
    try:
        with (opener or _opener).open(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise UpstreamError("rate_limited", "The platform API rate limit was reached; try again later.") from None
        if error.code in (401, 403):
            raise UpstreamError("auth_failed", "The platform API rejected the configured credentials or quota.") from None
        if error.code == 404:
            raise UpstreamError("not_found", "The platform API did not find that account.") from None
        raise UpstreamError("api_error", f"The platform API returned HTTP {error.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpstreamError("network_error", "The platform API could not be reached.") from None
    if len(body) > MAX_BYTES:
        raise UpstreamError("response_too_large", "The platform API response was too large.")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise UpstreamError("api_error", "The platform API returned invalid data.") from None
