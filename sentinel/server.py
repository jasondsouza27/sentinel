"""Local-only HTTP API and static web client for Sentinel."""

import argparse
import csv
import json
import os
import re
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .analysis import analyze
from .scan import scan
from .storage import CaseStore


ROOT = Path(__file__).resolve().parent.parent
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/conversation.js": ("conversation.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/ui.js": ("ui.js", "text/javascript; charset=utf-8"),
    "/grain.svg": ("grain.svg", "image/svg+xml"),
    "/demo": ("demo.html", "text/html; charset=utf-8"),
    "/demo.js": ("demo.js", "text/javascript; charset=utf-8"),
    "/demo.css": ("demo.css", "text/css; charset=utf-8"),
    "/demo-kyc.svg": ("demo-kyc.svg", "image/svg+xml"),
    "/demo-refund.svg": ("demo-refund.svg", "image/svg+xml"),
    "/demo-library.svg": ("demo-library.svg", "image/svg+xml"),
    "/bot": ("bot.html", "text/html; charset=utf-8"),
    "/bot.js": ("bot.js", "text/javascript; charset=utf-8"),
    "/bot.css": ("bot.css", "text/css; charset=utf-8"),
    "/network": ("network.html", "text/html; charset=utf-8"),
    "/network.js": ("network.js", "text/javascript; charset=utf-8"),
    "/network.css": ("network.css", "text/css; charset=utf-8"),
}
MAX_JSON_BYTES = 200000
MAX_BOT_UPLOAD_BYTES = 3_000_000  # /api/bot/analyze only: uploaded post exports
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


def create_server(host="127.0.0.1", port=8787, db_path=None, phishing_path=None, model_path=None,
                  url_model_path=None, paired_model_path=None, harm_model_path=None,
                  harm_neural_python=None, text_model_path=None, network_hub=None, network_share=False, bot_model_path=None,
                  bot_ml_research=False, bot_activity_model_path=None):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Sentinel serves only on the local loopback address")
    store = CaseStore(db_path or ROOT / "data" / "cases.db")
    known_phishing = load_phishing_feed(phishing_path)
    model = json.loads(Path(model_path).read_text(encoding="utf-8")) if model_path else None

    url_model = None
    if url_model_path:
        from .url_ml.service import UrlModelService
        url_model = UrlModelService(Path(url_model_path))
    paired_model = None
    if paired_model_path:
        from .paired.service import PairedService
        paired_model = PairedService(Path(paired_model_path))
    from .context_harm.service import HarmService
    from .optional_work import OptionalModelBudget
    from .assessment_receipts import SnapshotSigner
    harm_model = HarmService(harm_model_path, harm_neural_python)
    from .bot_detection.service import BadRequest as BotBadRequest, BotDetectionService
    bot_ml = None
    if bot_model_path:
        from .bot_detection.ml.model import BotProfileModel
        bot_ml = BotProfileModel(Path(bot_model_path), research_mode=bot_ml_research)
    bot_activity_ml = None
    if bot_activity_model_path:
        from .bot_detection.ml.model import BotProfileModel
        bot_activity_ml = BotProfileModel(Path(bot_activity_model_path), research_mode=bot_ml_research)
    bot_service = BotDetectionService(ml_model=bot_ml, ml_activity_model=bot_activity_ml)
    text_model = None
    if text_model_path:
        from .text_ml.service import TextModelService
        text_model = TextModelService(Path(text_model_path))
    network = None
    if network_hub:
        from .network.client import BackgroundNetwork, HttpTransport, NetworkClient
        network = BackgroundNetwork(NetworkClient(HttpTransport(network_hub), share=network_share,
                                                  state_path=ROOT / "data" / "network" / "client.json"))
    optional_budget = OptionalModelBudget()
    signer = SnapshotSigner(secrets.token_bytes(32))

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

        def _read_json(self, limit=MAX_JSON_BYTES):
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise ValueError("Invalid Content-Length") from error
            if size < 1 or size > limit:
                raise ValueError(f"JSON body must be between 1 and {limit} bytes")
            try:
                return json.loads(self.rfile.read(size), parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON is invalid")))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("Invalid JSON body") from error

        def _parts(self):
            return urlsplit(self.path).path.strip("/").split("/")

        def _guard(self):
            if not self._host_allowed() or not self._allowed_origin():
                # Drain a bounded, declared POST body before closing. Otherwise
                # Windows can reset the socket before the client reads HTTP 403.
                if self.command == "POST":
                    try:
                        size = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        size = 0
                    if 0 < size <= MAX_JSON_BYTES:
                        previous_timeout = self.connection.gettimeout()
                        self.connection.settimeout(1)
                        try:
                            self.rfile.read(size)
                        except OSError:
                            pass
                        finally:
                            self.connection.settimeout(previous_timeout)
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
                if paired_model is not None:
                    health["paired_model"] = paired_model.health()
                health["harm_model"] = harm_model.health()
                if text_model is not None:
                    health["text_model"] = text_model.health()
                if network is not None:
                    health["community_network"] = {**network.health(), "hub_url": network_hub}
                return self._json(HTTPStatus.OK, health)
            if path == "/api/cases":
                return self._json(HTTPStatus.OK, store.list_cases())
            if path == "/api/bot/platforms":
                return self._json(HTTPStatus.OK, bot_service.platforms())
            if path in ("/v1/stats", "/v1/campaigns"):
                # Read-only forward for the /network dashboard to the configured community hub.
                if not network_hub:
                    return self._json(HTTPStatus.SERVICE_UNAVAILABLE,
                                      {"error": "The community hub is not configured (start Sentinel with --network-hub)."})
                try:
                    from .network.client import HttpTransport
                    return self._json(HTTPStatus.OK, HttpTransport(network_hub)._call(path))
                except Exception:
                    return self._json(HTTPStatus.BAD_GATEWAY, {"error": "The community hub is not reachable."})
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
                path = urlsplit(self.path).path
                body = self._read_json(MAX_BOT_UPLOAD_BYTES if path == "/api/bot/analyze" else MAX_JSON_BYTES)
                parts = self._parts()
                if path == "/api/analyze":
                    result = analyze(body, known_phishing, model, url_model,
                        paired_model=paired_model, harm_model=harm_model, optional_budget=optional_budget,
                        text_model=text_model, network=network)
                    return self._json(HTTPStatus.OK, {**result, "assessment_receipt": signer.issue(body, result)})
                if path == "/api/community/report":
                    # The user recognised a scam; only its fingerprint leaves this computer, and only with sharing on.
                    if network is None:
                        raise ValueError("The community network is not configured")
                    text = body.get("text") if isinstance(body, dict) else None
                    if not isinstance(text, str) or not 10 <= len(text.strip()) <= 4000:
                        raise ValueError("Supply the message text (10-4000 characters)")
                    shared = network.report_manual(text.strip())
                    return self._json(HTTPStatus.ACCEPTED, {"shared": shared,
                        "note": "Fingerprint queued for the community hub." if shared else "Sharing is off; nothing was sent."})
                if path == "/api/bot/analyze":
                    return self._json(HTTPStatus.OK, bot_service.analyze(body))
                if path == "/api/scan":
                    # Rules only and never stored: auto-scan results are not cases.
                    return self._json(HTTPStatus.OK, scan(body, known_phishing, text_model, network))
                if path == "/api/cases":
                    if not isinstance(body, dict) or not isinstance(body.get("input"), dict):
                        raise ValueError("Supply an input object")
                    if "result" in body or "assessment_receipt" in body:
                        if not isinstance(body.get("result"), dict) or not isinstance(body.get("assessment_receipt"), str):
                            raise ValueError("Recheck this content: a signed reviewed result is required.")
                        signer.verify(body["assessment_receipt"], body["input"], body["result"])
                        result = body["result"]
                    else:
                        # Legacy input-only clients explicitly create a new assessment.
                        result = analyze(body["input"], known_phishing, model, url_model,
                            paired_model=paired_model, harm_model=harm_model, optional_budget=optional_budget,
                            text_model=text_model)
                    return self._json(HTTPStatus.CREATED, store.save(body["input"], result))
                if len(parts) == 4 and parts[:2] == ["api", "cases"] and parts[3] == "feedback":
                    if not isinstance(body, dict):
                        raise ValueError("Supply feedback details")
                    updated = store.feedback(parts[2], body.get("verdict"), body.get("note", ""))
                    return self._json(HTTPStatus.OK if updated else HTTPStatus.NOT_FOUND,
                                      {"updated": updated} if updated else {"error": "Case not found"})
                return self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            except BotBadRequest as error:
                return self._json(error.status, {"error": str(error), "code": error.code})
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

    server = ThreadingHTTPServer((host, port), Handler)
    server.harm_model = harm_model
    return server


def main():
    parser = argparse.ArgumentParser(description="Run the local Sentinel app")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", default=os.environ.get("SENTINEL_DB"))
    parser.add_argument("--phishing-feed", default=os.environ.get("SENTINEL_PHISHING_FEED"))
    parser.add_argument("--model", default=os.environ.get("SENTINEL_MODEL_PATH"))
    parser.add_argument("--url-model", default=os.environ.get("SENTINEL_URL_MODEL_PATH"))
    parser.add_argument("--paired-model", default=os.environ.get("SENTINEL_PAIRED_MODEL_PATH"))
    parser.add_argument("--harm-model", default=os.environ.get("SENTINEL_HARM_MODEL_PATH"))
    parser.add_argument("--harm-neural-python", default=os.environ.get("SENTINEL_HARM_NEURAL_PYTHON"))
    parser.add_argument("--text-model", default=os.environ.get("SENTINEL_TEXT_MODEL_PATH"),
                        help="Exported text-ml artifact folder (experimental learned scam-text model)")
    parser.add_argument("--network-hub", default=os.environ.get("SENTINEL_NETWORK_HUB"),
                        help="Community hub URL, e.g. http://127.0.0.1:8790 (matching only unless --network-share)")
    parser.add_argument("--network-share", action="store_true", default=os.environ.get("SENTINEL_NETWORK_SHARE") == "1",
                        help="Opt in to sharing anonymous fingerprints of messages Sentinel flags")
    parser.add_argument("--bot-model", default=os.environ.get("SENTINEL_BOT_MODEL_PATH"),
                        help="Trained bot-ml artifact folder (estimates are withheld unless it passed its release gate)")
    parser.add_argument("--bot-activity-model", default=os.environ.get("SENTINEL_BOT_ACTIVITY_MODEL_PATH"),
                        help="Trained activity bot-ml artifact folder (used when at least 20 posts are supplied)")
    parser.add_argument("--bot-ml-research", action="store_true", default=os.environ.get("SENTINEL_BOT_ML_RESEARCH") == "1",
                        help="Show a research-only bot model's estimate (labelled, never used in the classification)")
    args = parser.parse_args()
    server = create_server(port=args.port, db_path=args.db, phishing_path=args.phishing_feed,
                           model_path=args.model, url_model_path=args.url_model,
                           paired_model_path=args.paired_model, harm_model_path=args.harm_model,
                           harm_neural_python=args.harm_neural_python, text_model_path=args.text_model,
                           network_hub=args.network_hub, network_share=args.network_share,
                           bot_model_path=args.bot_model, bot_ml_research=args.bot_ml_research,
                           bot_activity_model_path=args.bot_activity_model)
    print(f"Sentinel is running at http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
