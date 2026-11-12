"""HTTP service and live dashboard for the community hub (prototype: loopback only)."""

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .hub import Hub, RejectedReport

WEB = Path(__file__).resolve().parents[2] / "web"
STATIC = {"/": ("network.html", "text/html; charset=utf-8"),
          "/network.js": ("network.js", "text/javascript; charset=utf-8"),
          "/network.css": ("network.css", "text/css; charset=utf-8"),
          "/grain.svg": ("grain.svg", "image/svg+xml")}
MAX_BODY = 20000


def create_hub_server(hub, host="127.0.0.1", port=8790):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("The prototype hub serves only on loopback")

    def now():
        # A running simulation drives the clock; otherwise use wall-clock hours.
        clock = hub._meta("clock_hour")
        return float(clock) if clock is not None else time.time() / 3600

    class Handler(BaseHTTPRequestHandler):
        server_version = "SentinelHub/0.1"

        def log_message(self, *args):
            return

        def _send(self, status, body, content_type="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in STATIC:
                name, mime = STATIC[path]
                return self._send(HTTPStatus.OK, (WEB / name).read_bytes(), mime)
            if path == "/v1/challenge":
                return self._send(HTTPStatus.OK, {"challenge": hub.challenge, "pow_bits": hub.pow_bits})
            if path == "/v1/campaigns":
                return self._send(HTTPStatus.OK, {"hour": now(), "campaigns": hub.campaigns(now())})
            if path == "/v1/stats":
                return self._send(HTTPStatus.OK, hub.stats(now()))
            return self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    raise RejectedReport("invalid_body")
                body = json.loads(self.rfile.read(size))
                path = urlsplit(self.path).path
                if path == "/v1/register":
                    return self._send(HTTPStatus.CREATED, {"client_id": hub.register(now(), str(body.get("nonce", "")))})
                if path == "/v1/reports":
                    if not isinstance(body.get("fingerprint"), dict):
                        raise RejectedReport("invalid_fingerprint")
                    return self._send(HTTPStatus.ACCEPTED, {"cluster_id": hub.report(str(body.get("client_id")), body["fingerprint"], now())})
                if path == "/v1/disputes":
                    if not isinstance(body.get("fingerprint"), dict):
                        raise RejectedReport("invalid_fingerprint")
                    return self._send(HTTPStatus.ACCEPTED, {"cluster_id": hub.dispute(str(body.get("client_id")), body["fingerprint"], now())})
                return self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            except RejectedReport as error:
                status = HTTPStatus.TOO_MANY_REQUESTS if str(error) == "rate_limited" else HTTPStatus.BAD_REQUEST
                return self._send(status, {"error": str(error)})
            except (ValueError, json.JSONDecodeError):
                return self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})

    return ThreadingHTTPServer((host, port), Handler)
