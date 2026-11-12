import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sentinel.scan import MAX_SCAN_ITEMS, link_text_mismatch, scan
from sentinel.server import create_server


class LinkMismatchTests(unittest.TestCase):
    def test_flags_text_naming_another_site(self):
        self.assertEqual(link_text_mismatch("www.bank.example/login", "https://bank-verify.example.net/x"),
                         "The link text shows bank.example but the link opens bank-verify.example.net.")

    def test_same_site_and_subdomains_are_not_mismatches(self):
        self.assertIsNone(link_text_mismatch("https://www.docs.example.org", "https://docs.example.org/a"))
        self.assertIsNone(link_text_mismatch("example.org", "https://help.example.org/page"))
        self.assertIsNone(link_text_mismatch("Read more", "https://other.example.com"))
        self.assertIsNone(link_text_mismatch("bank.example", "not a url"))


class ScanTests(unittest.TestCase):
    def results(self, *items):
        return {r["id"]: r for r in scan({"items": list(items)})["results"]}

    def test_severity_levels(self):
        results = self.results(
            {"id": "scam", "text": "Pay the registration fee immediately", "url": "http://192.0.2.5/pay"},
            {"id": "plain", "text": "The meeting moved to Thursday afternoon."},
            {"id": "one-word", "text": "Act now to reserve a seat at the community picnic."},
            {"id": "two", "text": "Urgent: send your verification code to keep the account."},
            {"id": "link", "text": "", "url": "https://login.bank-check.example.net", "link_text": "bank.example"},
            {"id": "abuse", "text": "you are worthless and everyone knows it"},
        )
        self.assertEqual(results["scam"]["severity"], "high")
        self.assertEqual(results["plain"]["severity"], "none")
        self.assertIsNone(results["plain"]["action"])
        self.assertEqual(results["one-word"]["severity"], "none")
        self.assertEqual(results["two"]["severity"], "review")
        self.assertEqual(results["link"]["severity"], "review")
        self.assertIn("bank.example", results["link"]["evidence"][0])
        self.assertEqual(results["abuse"]["severity"], "review")

    def test_mismatch_with_other_evidence_is_high(self):
        result = self.results({"id": "x", "text": "Enter your password here",
                               "url": "https://acct.example.net", "link_text": "paypal.example"})["x"]
        self.assertEqual(result["severity"], "high")
        self.assertTrue(result["action"].startswith("Avoid entering credentials"))

    def test_validation(self):
        for payload in ({}, {"items": []}, {"items": [{"text": "no id"}]}, {"items": [{"id": "a"}]},
                        {"items": [{"id": "a", "text": "x" * 4001}]}, {"items": ["text"]},
                        {"items": [{"id": str(i), "text": "t"} for i in range(MAX_SCAN_ITEMS + 1)]}):
            with self.assertRaises(ValueError):
                scan(payload)


class ScanEndpointTests(unittest.TestCase):
    def test_endpoint_scans_without_saving_and_allows_only_extension_origins(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(port=0, db_path=Path(directory) / "cases.db")
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"

            def post(origin):
                body = json.dumps({"items": [{"id": "a", "text": "Pay the fee now", "url": "http://192.0.2.1"}]})
                request = Request(base + "/api/scan", data=body.encode(),
                                  headers={"Content-Type": "application/json", "Origin": origin})
                with urlopen(request, timeout=3) as response:
                    return json.load(response), response.headers
            try:
                result, headers = post("chrome-extension://" + "a" * 32)
                self.assertEqual(result["results"][0]["severity"], "high")
                self.assertEqual(headers["Access-Control-Allow-Origin"], "chrome-extension://" + "a" * 32)
                with urlopen(base + "/api/cases", timeout=3) as response:
                    self.assertEqual(json.load(response), [])
                with self.assertRaises(HTTPError) as denied:
                    post("https://news.example")
                self.assertEqual(denied.exception.code, 403)
                with urlopen(base + "/demo", timeout=3) as response:
                    self.assertIn("text/html", response.headers["Content-Type"])
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=3)


class FalsePositiveTests(unittest.TestCase):
    """Legitimate notifications must not be marked; real requests and prize scams still are."""

    def test_legitimate_notifications_are_not_marked(self):
        legit = ["Dear Customer, Greetings from HDFC Bank! Rs.30.00 is debited from your account via UPI.",
                 "Your Go subscription payment failed. Update payment method.",
                 "482913 is the OTP for your login. Never share your OTP with anyone, including bank staff.",
                 "HDFC Bank never asks you to share your PIN or card details.",
                 "Your Vercel security code: 814168. We received a request to approve a sign in."]
        results = scan({"items": [{"id": str(i), "text": t} for i, t in enumerate(legit)]})["results"]
        self.assertEqual([r["severity"] for r in results], ["none"] * len(legit))

    def test_requests_and_prizes_are_still_evidence(self):
        from sentinel.analysis import analyze
        cases = {"Please share your OTP to continue": "password, code or card",
                 "Enter your UPI PIN to receive the money": "password, code or card",
                 "Pay the clearance fee of Rs 28,500 today": "payment or a fee",
                 "Congratulations! You have won a 1000 prize": "prize or win"}
        for text, phrase in cases.items():
            evidence = " ".join(analyze({"message": text})["fraud"]["evidence"])
            self.assertIn(phrase, evidence, text)


if __name__ == "__main__":
    unittest.main()
