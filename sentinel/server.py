"""Local-only HTTP API and static web client for Sentinel."""

import argparse
import csv
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .analysis import analyze
from .storage import CaseStore


ROOT = Path(__file__).resolve().parent.parent
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


def load_phishing_feed(path):
    if not path:
        return None
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        rows = csv.DictReader(stream)
        if "url" not in (rows.fieldnames or []):
            raise ValueError("Phishing CSV needs a url column")
        return {
            row["url"].strip() for row in rows
            if row["url"].strip() and row.get("verified", "yes").lower() == "yes"
            and row.get("online", "yes").lower() == "yes"
        }


def create_server(host="127.0.0.1", port=8787, db_path=None, phishing_path=None, model_path=None, url_model_path=None):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Sentinel serves only on the local loopback address")
    store = CaseStore(db_path or ROOT / "data" / "cases.db")
    known_phishing = load_phishing_feed(phishing_path)
    model = json.loads(Path(model_path).read_text(encoding="utf-8")) if model_path else None

    url_model = None
    if url_model_path:
        from .url_ml.service import UrlModelService
        url_model = UrlModelService(Path(url_model_path))

    class Handler(BaseHTTPRequestHandler):
        server_version = "Sentinel/0.1"

        def log_message(self, format_string, *args):
            return

        def _allowed_origin(self):
            origin = self.headers.get("Origin", "")
            if not origin:
                return True
            local = {f"http://127.0.0.1:{self.server.server_port}",
                     f"http://localhost:{self.server.server_port}"}
            return origin in local or bool(EXTENSION_ORIGIN.fullmatch(origin))

        def _host_allowed(self):
            return self.headers.get("Host", "") in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }

        def _headers(self, status, content_type="application/json; charset=utf-8", length=0):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'")
            origin = self.headers.get("Origin", "")
            if origin and self._allowed_origin():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _json(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self._headers(status, length=len(body))
            self.wfile.write(body)

        def _read_json(self):
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("Invalid Content-Length") from error
            if size < 1 or size > 40000:
                raise ValueError("JSON body must be between 1 and 40000 bytes")
            try:
                return json.loads(self.rfile.read(size))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("Invalid JSON body") from error

        def _parts(self):
            return urlsplit(self.path).path.strip("/").split("/")

        def _guard(self):
            if not self._host_allowed() or not self._allowed_origin():
                self._json(HTTPStatus.FORBIDDEN, {"error": "Origin or host is not allowed"})
                return False
            return True

        def do_OPTIONS(self):
            if not self._guard():
                return
            self._headers(HTTPStatus.NO_CONTENT)

        def do_GET(self):
            if not self._guard():
                return
            path = urlsplit(self.path).path
            parts = self._parts()
            if path == "/api/health":
                health = {"status": "ok", "reputation_loaded": known_phishing is not None,
                          "research_model_loaded": model is not None}
                if url_model is not None:
                    health["url_model"] = url_model.health()
                return self._json(HTTPStatus.OK, health)
            if path == "/api/cases":
                return self._json(HTTPStatus.OK, store.list_cases())
            if len(parts) in (3, 4) and parts[:2] == ["api", "cases"]:
                case = store.get(parts[2])
                if not case:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "Case not found"})
                if len(parts) == 3:
                    return self._json(HTTPStatus.OK, case)
                if parts[3] == "report":
                    return self._json(HTTPStatus.OK, case)
            if path in STATIC:
                name, mime = STATIC[path]
                content = (ROOT / "web" / name).read_bytes()
                self._headers(HTTPStatus.OK, mime, len(content))
                return self.wfile.write(content)
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self):
            if not self._guard():
                return
            try:
                body = self._read_json()
                path = urlsplit(self.path).path
                parts = self._parts()
                if path == "/api/analyze":
                    return self._json(HTTPStatus.OK, analyze(body, known_phishing, model, url_model))
                if path == "/api/cases":
                    if not isinstance(body, dict) or not isinstance(body.get("input"), dict):
                        raise ValueError("Supply an input object")
                    result = analyze(body["input"], known_phishing, model, url_model)
                    return self._json(HTTPStatus.CREATED, store.save(body["input"], result))
                if len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] == "feedback":
                    if not isinstance(body, dict):
                        raise ValueError("Supply feedback details")
                    updated = store.feedback(parts[2], body.get("verdict"), body.get("note", ""))
                    return self._json(HTTPStatus.OK if updated else HTTPStatus.NOT_FOUND,
                                      {"updated": updated} if updated else {"error": "Case not found"})
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            except ValueError as error:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_DELETE(self):
            if not self._guard():
                return
            parts = self._parts()
            if len(parts) == 3 and parts[:2] == ["api", "cases"]:
                deleted = store.delete(parts[2])
                return self._json(HTTPStatus.OK if deleted else HTTPStatus.NOT_FOUND,
                                  {"deleted": deleted} if deleted else {"error": "Case not found"})
            return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description="Run the local Sentinel app")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", default=os.environ.get("SENTINEL_DB"))
    parser.add_argument("--phishing-feed", default=os.environ.get("SENTINEL_PHISHING_FEED"))
    parser.add_argument("--model", default=os.environ.get("SENTINEL_MODEL_PATH"))
    parser.add_argument("--url-model", default=os.environ.get("SENTINEL_URL_MODEL_PATH"))
    args = parser.parse_args()
    server = create_server(port=args.port, db_path=args.db, phishing_path=args.phishing_feed, model_path=args.model, url_model_path=args.url_model)
    print(f"Sentinel is running at http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
