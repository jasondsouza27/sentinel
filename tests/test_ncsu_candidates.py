import csv
import hashlib
import importlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


class NcsuCandidateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("sentinel.ncsu_candidates"))
        self.builder = importlib.import_module("sentinel.ncsu_candidates").build_candidates

    def test_builds_diverse_unreviewed_candidates_without_touching_intake(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            output = root / "ncsu_candidates.csv"
            audit_path = root / "ncsu_candidates_audit.json"
            intake = root / "intake.csv"
            intake.write_text("case_id,message,url\n", encoding="utf-8")
            original_intake = intake.read_bytes()
            samples = [
                ("1", "Case alpha https://a.example/pay"),
                ("2", "Case beta https://b.example/pay"),
                ("3", "Case alpha https://a.example/pay"),
                ("4", "No link here"),
                ("5", "Two links https://x.example/a https://y.example/b"),
                ("6", "Case gamma https://a.example/other"),
                ("7", "Case delta https://c.example/pay"),
                ("8", "Repeated https://repeat.example/x and https://repeat.example/x"),
            ]
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["messageID", "objectID", "destination number", "message", "time", "error in time"])
                writer.writeheader()
                writer.writerows({"messageID": identifier, "objectID": str(index), "destination number": "private-phone",
                                  "message": message, "time": "", "error in time": ""}
                                 for index, (identifier, message) in enumerate(samples))

            audit = self.builder(source, output, audit_path, limit=2, seed=42)
            rows = read_rows(output)
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({row["url"].split("/")[2] for row in rows}), 2)
            self.assertEqual({row["channel"] for row in rows}, {"sms"})
            self.assertEqual({row["pair_evidence"] for row in rows}, {"in_message"})
            self.assertEqual({row["redaction_reviewed"] for row in rows}, {""})
            self.assertEqual({row["collection_basis"] for row in rows}, {""})
            self.assertTrue(all(row["url"] in row["message"] for row in rows))
            self.assertFalse(any("label" in row for row in rows))
            self.assertFalse(any("destination number" in row for row in rows))
            self.assertEqual(intake.read_bytes(), original_intake)
            self.assertEqual(audit["source_cases"], 8)
            self.assertEqual(audit["eligible_cases"], 4)
            self.assertEqual(audit["selected_cases"], 2)
            self.assertEqual(audit["excluded"]["no_link"], 1)
            self.assertEqual(audit["excluded"]["multiple_links"], 2)
            self.assertEqual(audit["excluded"]["duplicate_pair"], 1)
            self.assertEqual(audit["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(audit["output_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(json.loads(audit_path.read_text(encoding="utf-8")), audit)
            self.assertNotIn("Case alpha", audit_path.read_text(encoding="utf-8"))
            self.assertNotIn("private-phone", output.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                self.builder(source, output, audit_path, limit=2, seed=42)

    def test_rejects_missing_source_columns_and_intake_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            source.write_text("messageID,body\n1,Some text\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "message"):
                self.builder(source, root / "candidates.csv", limit=2)
            with self.assertRaisesRegex(ValueError, "intake.csv"):
                self.builder(source, root / "intake.csv", limit=2)
            self.assertFalse((root / "intake.csv").exists())

    def test_rejects_audit_path_that_aliases_candidate_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sub").mkdir()
            source = root / "source.csv"
            source.write_text("messageID,message\n1,Read https://one.example/pay\n", encoding="utf-8")
            output = root / "candidates.csv"
            alias = root / "sub" / ".." / "candidates.csv"
            with self.assertRaisesRegex(ValueError, "different"):
                self.builder(source, output, alias, limit=1)
            self.assertFalse(output.exists())

    def test_rejects_invalid_utf8_in_source_without_writing_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            output = root / "candidates.csv"
            source.write_bytes(b"messageID,message\n1,Read https://one.example/pay\xff\n")
            with self.assertRaises(UnicodeDecodeError):
                self.builder(source, output, limit=1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
