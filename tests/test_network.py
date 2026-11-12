import json
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sentinel.network.client import LocalTransport, NetworkClient
from sentinel.network.fingerprint import fingerprint, similarity
from sentinel.network.hub import Hub, RejectedReport
from sentinel.scan import scan

SCAM = "Dear customer, your SBI account will be blocked today. Update KYC at http://sbi-kyc.example.xyz/upd now"
REWORDED = "Dear user, ur SBI acc0unt will be bl0cked t0day. Update KYC at http://sbi-verify.example.top/x immediately"
OTHER = "Notes from today's lab are in the shared folder. The quiz moved to Thursday afternoon."


class FingerprintTests(unittest.TestCase):
    def test_variants_match_and_unrelated_messages_do_not(self):
        a, b, c = fingerprint(SCAM), fingerprint(REWORDED), fingerprint(OTHER)
        self.assertGreaterEqual(similarity(a["signature"], b["signature"]), 0.4)
        self.assertTrue(set(a["bands"]) & set(b["bands"]))
        self.assertLess(similarity(a["signature"], c["signature"]), 0.2)

    def test_disguises_are_folded(self):
        base = fingerprint(SCAM)["signature"]
        for disguised in (SCAM.replace("account", "a.c.c.o.u.n.t"), SCAM.replace("blocked", "bl0ck3d"),
                          SCAM.replace("customer", "custоmer")):
            self.assertGreaterEqual(similarity(base, fingerprint(disguised)["signature"]), 0.8, disguised)

    def test_fingerprint_contains_no_message_text_or_domain(self):
        fp = fingerprint(SCAM, "smishing", 0.97)
        dumped = json.dumps(fp).lower()
        for word in ("customer", "blocked", "update", "sbi-kyc", "example.xyz"):
            self.assertNotIn(word, dumped)
        self.assertEqual(fp["topics"], ["bank", "kyc", "urgency"])
        self.assertEqual(len(fp["domains"]), 1)
        self.assertEqual(fp["score_bucket"], 0.9)

    def test_too_little_text_has_no_fingerprint(self):
        self.assertIsNone(fingerprint("!!"))


class HubTests(unittest.TestCase):
    def setUp(self):
        self.hub = Hub(k=3, hourly_limit=5)
        self.clients = [self.hub.register(-48) for _ in range(6)]
        self.fp = fingerprint(SCAM, "smishing", 0.97)

    def test_publishes_only_after_k_distinct_reporters(self):
        self.hub.report(self.clients[0], self.fp, 1)
        self.hub.report(self.clients[0], self.fp, 1.1)  # same client twice counts once
        self.hub.report(self.clients[1], fingerprint(REWORDED, "smishing", 0.95), 1.2)
        self.assertEqual(self.hub.campaigns(2), [])
        self.hub.report(self.clients[2], self.fp, 1.3)
        campaigns = self.hub.campaigns(2)
        self.assertEqual(len(campaigns), 1)
        self.assertEqual(campaigns[0]["reporters"], 3)
        self.assertNotIn("text", json.dumps(campaigns[0]))

    def test_new_clients_count_half(self):
        fresh = [self.hub.register(10) for _ in range(4)]
        for client in fresh[:3]:
            self.hub.report(client, self.fp, 11)
        self.assertEqual(self.hub.campaigns(12), [])  # 3 x 0.5 < k
        for client in fresh[3:] + self.clients[:2]:
            self.hub.report(client, self.fp, 11.5)
        self.assertEqual(len(self.hub.campaigns(12)), 1)

    def test_rate_limit(self):
        texts = [f"Win a prize number {i} by calling the office before the weekend closes {i}" for i in range(6)]
        for text in texts[:5]:
            self.hub.report(self.clients[0], fingerprint(text), 3)
        with self.assertRaisesRegex(RejectedReport, "rate_limited"):
            self.hub.report(self.clients[0], fingerprint(texts[5]), 3.2)
        self.hub.report(self.clients[0], fingerprint(texts[5]), 4.5)  # next hour is fine

    def test_allowlisted_sender_is_held_and_reporters_lose_reputation(self):
        bank = "Your A/c XX1234 is debited for Rs 450.00 on 05-Jan by UPI ref 778812. Not you? Call the number on your card."
        self.hub.allow(fingerprint=fingerprint(bank))
        for client in self.clients[:3]:
            self.hub.report(client, fingerprint(bank.replace("1234", "9876"), "smishing", 0.95), 5)
        self.assertEqual(self.hub.campaigns(6), [])
        self.assertEqual(self.hub.stats(6)["clusters"], {"held_for_review": 1})
        reputation = self.hub.db.execute("SELECT reputation FROM clients WHERE id=?", (self.clients[0],)).fetchone()[0]
        self.assertEqual(reputation, 0.5)

    def test_disputes_withdraw_a_wrong_campaign(self):
        notice = "Reminder: the end-semester exam timetable is on the student portal. Hall tickets can be collected from the office."
        for client in self.clients[:3]:
            self.hub.report(client, fingerprint(notice, "spam", 0.92), 5)
        self.assertEqual(len(self.hub.campaigns(6)), 1)
        others = [self.hub.register(-48) for _ in range(3)]
        for client in others[:2]:
            self.hub.dispute(client, fingerprint(notice), 6)
        self.assertEqual(len(self.hub.campaigns(6)), 1)  # fewer than k disputes
        self.hub.dispute(others[2], fingerprint(notice), 6)
        self.assertEqual(self.hub.campaigns(7), [])
        self.assertEqual(self.hub.stats(7)["clusters"], {"disputed": 1})

    def test_invalid_reports_are_rejected(self):
        for bad in ({}, {**self.fp, "signature": [1, 2]}, {**self.fp, "bands": ["x"] * 32},
                    {**self.fp, "topics": ["a" * 40]}, {**self.fp, "category": "<script>"}):
            with self.assertRaises(RejectedReport):
                self.hub.report(self.clients[0], bad, 1)
        with self.assertRaisesRegex(RejectedReport, "unknown_client"):
            self.hub.report("nobody", self.fp, 1)

    def test_no_text_column_is_stored(self):
        columns = {c for cols in self.hub.stored_columns().values() for c in cols}
        self.assertFalse(columns & {"text", "message", "body", "sender", "url"})

    def test_proof_of_work_registration(self):
        hub = Hub(pow_bits=8)
        wrong = next(str(n) for n in range(1000) if not _solves(hub, str(n)))
        with self.assertRaisesRegex(RejectedReport, "proof_of_work_invalid"):
            hub.register(0, wrong)
        self.assertTrue(hub.register(0, hub.solve_pow()))


def _solves(hub, nonce):
    import hashlib
    return int.from_bytes(hashlib.sha256(f"{hub.challenge}:{nonce}".encode()).digest(), "big") >> 248 == 0


class ClientTests(unittest.TestCase):
    def test_match_after_sync_and_sharing_is_opt_in(self):
        hub = Hub(k=2, new_client_hours=0)
        clock = {"h": 0}
        transport = LocalTransport(hub, lambda: clock["h"])
        silent = NetworkClient(transport, share=False)
        self.assertIsNone(silent.report(SCAM, "smishing", 0.97))
        sharers = [NetworkClient(transport, share=True) for _ in range(2)]
        clock["h"] = 30
        for client in sharers:
            client.report(SCAM, "smishing", 0.97)
        self.assertIsNone(silent.match(REWORDED))  # feed not synced yet
        silent.sync()
        match = silent.match(REWORDED)
        self.assertEqual(match["reporters"], 2)
        self.assertIn("kyc", match["topics"])
        self.assertIsNone(silent.match(OTHER))


class FakeNetwork:
    def __init__(self, matched=True):
        self.matched, self.reports = matched, []

    def match(self, text):
        return {"campaign_id": 1, "reporters": 12, "topics": ["bank", "kyc"], "similarity": 0.6} if self.matched else None

    def report(self, text, category, score):
        self.reports.append((category, score))


class ScanIntegrationTests(unittest.TestCase):
    def test_campaign_match_adds_evidence_and_raises_severity(self):
        network = FakeNetwork()
        result = scan({"items": [{"id": "a", "text": "Please update your details at the office counter today"}]},
                      network=network)["results"][0]
        self.assertEqual(result["severity"], "review")
        self.assertIn("reported by 12 Sentinel users", result["evidence"][0])
        self.assertEqual(network.reports, [])  # not flagged by Sentinel itself -> nothing shared

    def test_rules_high_message_is_reported(self):
        network = FakeNetwork(matched=False)
        scan({"items": [{"id": "a", "text": "Pay the registration fee immediately", "url": "http://192.0.2.4/pay"}]},
             network=network)
        self.assertEqual(network.reports, [("rules", 0.9)])


class HubServerTests(unittest.TestCase):
    def test_http_flow(self):
        from sentinel.network.client import HttpTransport
        from sentinel.network.hub_server import create_hub_server
        hub = Hub(k=2, hourly_limit=1, new_client_hours=0)
        server = create_hub_server(hub, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            hub.set_clock(50)
            transport = HttpTransport(base)
            clients = [NetworkClient(transport, share=True) for _ in range(2)]
            for client in clients:
                client.report(SCAM, "smishing", 0.97)
            with self.assertRaises(HTTPError) as limited:
                clients[0].report(REWORDED + " extra words here", "smishing", 0.95)
            self.assertEqual(limited.exception.code, 429)
            reader = NetworkClient(transport)
            self.assertTrue(reader.sync())
            self.assertEqual(reader.match(SCAM)["reporters"], 2)
            with urlopen(base + "/v1/stats") as response:
                self.assertEqual(json.load(response)["reports"], 2)
            with urlopen(base + "/") as response:
                self.assertIn(b"Community Network", response.read())
            with self.assertRaises(HTTPError) as bad:
                urlopen(Request(base + "/v1/reports", data=b"{}", headers={"Content-Type": "application/json"}))
            self.assertEqual(bad.exception.code, 400)
        finally:
            server.shutdown(); server.server_close(); worker.join(3)


DATA = Path(__file__).resolve().parent.parent / "data" / "text-ml" / "dataset.jsonl"


@unittest.skipUnless(DATA.exists(), "text-ml dataset not prepared")
class SimulationSmokeTests(unittest.TestCase):
    def test_small_simulation(self):
        from sentinel.network.simulate import Config, run
        result = run(Config(users=600, campaigns=3, legit_broadcasts=3, hours=48, detector="rates",
                            min_campaign_size=150, max_campaign_size=400, seed=5))
        self.assertTrue(result["privacy"]["passed"])
        self.assertGreaterEqual(result["scam"]["model_plus_network_protection"], result["scam"]["model_only_protection"])
        self.assertEqual(result["legit"]["templates_published_as_campaigns"], [])
        self.assertGreater(result["campaigns"]["newly_published"], 0)


if __name__ == "__main__":
    unittest.main()
