import csv
import json
import tempfile
import unittest
from pathlib import Path

from sentinel.datasets import build_assassin_pairs, extract_urls, domain_group


class DatasetTests(unittest.TestCase):
    def test_extracts_only_links_present_in_the_message(self):
        message = "Read https://help.example.co.uk/guide), then www.team.example.org/news."
        self.assertEqual(
            extract_urls(message),
            ["https://help.example.co.uk/guide", "http://www.team.example.org/news"],
        )
        self.assertEqual(extract_urls("Contact person@www.example.org by email"), [])
        self.assertEqual(domain_group("https://help.example.co.uk/guide"), "example.co.uk")
        self.assertEqual(domain_group("http://www.team.example.org/news"), "example.org")

    def test_import_keeps_real_pairs_and_audits_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "assassin.csv"
            output = Path(temporary) / "pairs.csv"
            audit_path = Path(temporary) / "audit.json"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["subject", "body", "label", "urls"])
                writer.writeheader()
                writer.writerows([
                    {"subject": "Welcome", "body": "Open https://news.example.org/start", "label": "0", "urls": "0"},
                    {"subject": "Offer", "body": "Pay at www.pay.example.co.uk/app now", "label": "1", "urls": "1"},
                    {"subject": "Hello", "body": "No link is here", "label": "0", "urls": "1"},
                    {"subject": "Welcome", "body": "Open https://news.example.org/start", "label": "0", "urls": "1"},
                    {"subject": "Roundup", "body": "See https://one.example/a and https://two.example/b", "label": "1", "urls": "1"},
                ])
            audit = build_assassin_pairs(source, output, audit_path)
            with output.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual([row["label"] for row in rows], ["0", "1"])
            self.assertEqual(rows[0]["url"], "https://news.example.org/start")
            self.assertEqual(rows[1]["domain_group"], "example.co.uk")
            self.assertEqual(audit["excluded"]["no_link_in_message"], 1)
            self.assertEqual(audit["excluded"]["duplicate_message"], 1)
            self.assertEqual(audit["excluded"]["multiple_links_in_message"], 1)
            self.assertEqual(audit["label_meaning"]["1"], "spam (not verified phishing)")
            self.assertNotIn("Open https", json.dumps(audit))
            self.assertEqual(json.loads(audit_path.read_text(encoding="utf-8")), audit)


if __name__ == "__main__":
    unittest.main()
