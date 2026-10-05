import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sentinel.server import create_server


class ServerTests(unittest.TestCase):
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
