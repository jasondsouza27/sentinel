import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sentinel.server import create_server


class ServerTests(unittest.TestCase):
    def test_forbidden_post_consumes_bounded_body_before_response(self):
        # Closing with unread POST bytes can reset the connection on Windows,
        # hiding the intended HTTP 403 from the client.
        import io
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(port=0, db_path=Path(directory) / "cases.db")
            try:
                handler = object.__new__(server.RequestHandlerClass)
                body = b'{"message":"test"}'
                handler.server = server
                handler.command = "POST"
                handler.headers = {"Host": f"127.0.0.1:{server.server_port}",
                                   "Origin": "https://evil.example", "Content-Length": str(len(body))}
                handler.rfile = io.BytesIO(body)
                handler.connection = Mock()
                handler.connection.gettimeout.return_value = None
                read_positions = []
                handler._json = lambda status, result: read_positions.append(handler.rfile.tell())
                self.assertFalse(handler._guard())
                self.assertEqual(read_positions, [len(body)])
            finally:
                server.server_close()

    def test_analysis_is_not_saved_until_user_requests_it(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server("127.0.0.1", 0, Path(directory) / "cases.db")
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"

            def request(path, payload=None, method=None, origin=None):
                data = json.dumps(payload).encode() if payload is not None else None
                headers = {"Content-Type": "application/json"} if data else {}
                if origin:
                    headers["Origin"] = origin
                with urlopen(Request(base + path, data=data, headers=headers, method=method), timeout=3) as response:
                    return json.load(response)

            try:
                response = request("/api/analyze", {"message": "Pay a fee now"})
                self.assertIn("fraud", response)
                self.assertEqual(request("/api/cases"), [])
                extension_origin = "chrome-extension://" + "a" * 32
                preflight = Request(
                    base + "/api/analyze", method="OPTIONS",
                    headers={"Origin": extension_origin, "Access-Control-Request-Method": "POST"},
                )
                with urlopen(preflight, timeout=3) as allowed:
                    self.assertEqual(allowed.status, 204)
                    self.assertEqual(allowed.headers["Access-Control-Allow-Origin"], extension_origin)
                extension_result = request(
                    "/api/analyze",
                    {"message": "Pay a fee now", "url": "https://apply.example/fee"},
                    origin=extension_origin,
                )
                self.assertIn("fraud", extension_result)
                self.assertEqual(request("/api/cases"), [])
                saved = request("/api/cases", {"input": {"message": "Pay a fee now"}})
                self.assertEqual(len(request("/api/cases")), 1)
                request(f"/api/cases/{saved['id']}", method="DELETE")
                self.assertEqual(request("/api/cases"), [])
                with self.assertRaises(HTTPError) as error:
                    request("/api/analyze", {"message": "test"}, origin="https://evil.example")
                self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
