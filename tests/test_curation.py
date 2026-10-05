import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sentinel.curation import _same_link, evaluate_locked, finalize_reviews, freeze_split, init_workspace, prepare_reviews
from sentinel.research import evaluate_fixed_split, load_rows


def write_csv(path, rows, fields=None):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def intake_row(number, evidence="in_message"):
    url = f"https://case{number}.example/check"
    return {
        "case_id": f"case-{number}",
        "message": f"Review this link {url}" if evidence == "in_message" else "Review this linked post",
        "url": url,
        "source_name": "Consented research example",
        "source_ref": f"consent-record-{number}",
        "campaign_group": "campaign-1" if number in (0, 1) else "",
        "channel": "social_dm",
        "collected_on": "2026-10-04",
        "collection_basis": "consented",
        "pair_evidence": evidence,
        "pair_note": "Link and text came from the same post" if evidence == "same_post" else "",
        "redaction_reviewed": "yes",
    }


class CurationTests(unittest.TestCase):
    def test_reviewed_cases_run_through_locked_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_workspace(root)
            cases = []
            for number in range(12):
                case = intake_row(number)
                case["message"] = f"Scenario {number} asks you to check {case['url']}"
                cases.append(case)
            write_csv(root / "intake.csv", cases)
            prepare_reviews(root)
            for name, reviewer in (("reviewer_a", "member-a"), ("reviewer_b", "member-b")):
                rows = read_csv(root / f"{name}.csv")
                for number, row in enumerate(rows):
                    row.update(reviewer_id=reviewer, review_label=str(number % 2), review_reason="Synthetic test label")
                if name == "reviewer_b":
                    rows[1]["review_label"] = "?"
                write_csv(root / f"{name}.csv", rows)
            write_csv(root / "adjudication.csv", [{"case_id": "case-1", "final_label": "1", "reason": "Synthetic resolution"}])
            audit = finalize_reviews(root)
            self.assertEqual(audit["final_cases"], 12)
            self.assertEqual(audit["adjudicated_cases"], 1)
            manifest = freeze_split(root, seed=42)
            report = evaluate_locked(root)
            self.assertEqual(report["test_cases"], manifest["test_cases"])
            self.assertEqual(report["split_overlap"], {"domains": 0, "duplicate_messages": 0, "campaigns": 0})

    def test_in_message_pair_requires_the_same_scheme_and_port(self):
        self.assertFalse(_same_link("http://example.com:8080/pay", "http://example.com:9090/pay"))
        self.assertFalse(_same_link("http://example.com/pay", "https://example.com/pay"))
        self.assertFalse(_same_link("https://example.com/pay", "https://example.com/pay/"))
        self.assertTrue(_same_link("https://example.com/pay", "https://example.com/pay"))

    def test_cli_explains_empty_intake_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            init_workspace(Path(temporary))
            result = subprocess.run(
                [sys.executable, "-m", "sentinel.curation", "prepare", temporary],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("intake.csv is empty", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_init_and_prepare_make_blind_review_sheets_without_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_workspace(root)
            self.assertEqual(read_csv(root / "intake.csv"), [])
            write_csv(root / "intake.csv", [intake_row(1), intake_row(2, "same_post")])
            summary = prepare_reviews(root)
            self.assertEqual(summary["cases"], 2)
            a = read_csv(root / "reviewer_a.csv")
            b = read_csv(root / "reviewer_b.csv")
            self.assertEqual(a, b)
            self.assertEqual([row["case_id"] for row in a], ["case-1", "case-2"])
            self.assertEqual(a[0]["review_label"], "")
            self.assertNotIn("source_name", a[0])
            self.assertNotIn("collection_basis", a[0])
            self.assertEqual(read_csv(root / "adjudication.csv"), [])
            self.assertEqual(json.loads((root / "review_manifest.json").read_text())["cases"], 2)

    def test_prepare_rejects_unpaired_or_unreviewed_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_workspace(root)
            row = intake_row(1)
            row["url"] = "https://other.example/not-in-message"
            write_csv(root / "intake.csv", [row])
            with self.assertRaisesRegex(ValueError, "not present"):
                prepare_reviews(root)
            self.assertFalse((root / "reviewer_a.csv").exists())
            row = intake_row(1, "same_post")
            row["redaction_reviewed"] = "no"
            write_csv(root / "intake.csv", [row])
            with self.assertRaisesRegex(ValueError, "redaction"):
                prepare_reviews(root)
            row = intake_row(1)
            row["channel"] = "unknown"
            write_csv(root / "intake.csv", [row])
            with self.assertRaisesRegex(ValueError, "channel"):
                prepare_reviews(root)
            row = intake_row(1, "same_post")
            row["url"] = "https://case1.example:bad/check"
            write_csv(root / "intake.csv", [row])
            with self.assertRaisesRegex(ValueError, r"HTTP\(S\) URL"):
                prepare_reviews(root)

    def test_finalize_requires_distinct_reviewers_and_adjudication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_workspace(root)
            write_csv(root / "intake.csv", [intake_row(1), intake_row(2), intake_row(3)])
            prepare_reviews(root)
            a = read_csv(root / "reviewer_a.csv")
            b = read_csv(root / "reviewer_b.csv")
            for index, row in enumerate(a):
                row.update(reviewer_id="member-a", review_label=["1", "0", "1"][index], review_reason="Independent review")
            for index, row in enumerate(b):
                row.update(reviewer_id="member-b", review_label=["1", "0", "0"][index], review_reason="Independent review")
            write_csv(root / "reviewer_a.csv", a)
            write_csv(root / "reviewer_b.csv", b)
            same_person = [dict(row, reviewer_id="member-a") for row in b]
            write_csv(root / "reviewer_b.csv", same_person)
            with self.assertRaisesRegex(ValueError, "different people"):
                finalize_reviews(root)
            write_csv(root / "reviewer_b.csv", b)
            with self.assertRaisesRegex(ValueError, "case-3"):
                finalize_reviews(root)
            self.assertFalse((root / "final_pairs.csv").exists())
            write_csv(root / "adjudication.csv", [{"case_id": "case-3", "final_label": "1", "reason": "Verified request for credentials"}])
            audit = finalize_reviews(root)
            pairs = read_csv(root / "final_pairs.csv")
            self.assertEqual([row["label"] for row in pairs], ["1", "0", "1"])
            self.assertEqual(pairs[0]["channel"], "social_dm")
            self.assertEqual(pairs[0]["reviewer_a_reason"], "Independent review")
            self.assertEqual(pairs[2]["adjudication_reason"], "Verified request for credentials")
            self.assertEqual(audit["agreement_cases"], 2)
            self.assertEqual(audit["adjudicated_cases"], 1)
            for name in ("intake", "reviewer_a", "reviewer_b", "adjudication", "final_pairs"):
                self.assertEqual(audit[f"{name}_sha256"], hashlib.sha256((root / f"{name}.csv").read_bytes()).hexdigest())
            self.assertEqual(audit["distinct_sources"], 1)
            self.assertNotIn("Review this link", json.dumps(audit))
            with self.assertRaisesRegex(FileExistsError, "final_pairs"):
                finalize_reviews(root)

    def test_freeze_creates_non_overlapping_immutable_split_for_fixed_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = []
            for number in range(12):
                item = intake_row(number)
                item["message"] = f"Review case {number} at {item['url']}"
                rows.append({
                    "case_id": item["case_id"], "message": item["message"],
                    "url": item["url"], "label": str(number % 2),
                    "domain_group": f"case{number}.example",
                })
            write_csv(root / "final_pairs.csv", rows)
            for name in ("intake", "reviewer_a", "reviewer_b", "adjudication"):
                (root / f"{name}.csv").write_text(f"fixture {name}\n", encoding="utf-8")
            original_pairs = (root / "final_pairs.csv").read_bytes()
            audit_hashes = {f"{name}_sha256": hashlib.sha256((root / f"{name}.csv").read_bytes()).hexdigest()
                            for name in ("intake", "reviewer_a", "reviewer_b", "adjudication", "final_pairs")}
            (root / "final_audit.json").write_text(json.dumps(audit_hashes), encoding="utf-8")
            review_path = root / "reviewer_a.csv"
            original_review = review_path.read_bytes()
            review_path.write_bytes(original_review + b"changed\n")
            with self.assertRaisesRegex(ValueError, "reviewer_a.csv changed"):
                freeze_split(root, seed=42)
            review_path.write_bytes(original_review)
            (root / "final_pairs.csv").write_bytes(original_pairs + b"\n")
            with self.assertRaisesRegex(ValueError, "after finalization"):
                freeze_split(root, seed=42)
            (root / "final_pairs.csv").write_bytes(original_pairs)
            manifest = freeze_split(root, seed=42)
            self.assertEqual(manifest["final_audit_sha256"], hashlib.sha256((root / "final_audit.json").read_bytes()).hexdigest())
            train = load_rows(root / "locked" / "train.csv")
            test = load_rows(root / "locked" / "test.csv")
            self.assertEqual(len(train) + len(test), 12)
            self.assertEqual(manifest["overlap"], {"domains": 0, "duplicate_messages": 0, "campaigns": 0})
            report = evaluate_fixed_split(train, test)
            self.assertEqual(report["split_type"], "locked")
            self.assertEqual(report["split_overlap"]["domains"], 0)
            test_path = root / "locked" / "test.csv"
            review_path.write_bytes(original_review + b"changed\n")
            with self.assertRaisesRegex(ValueError, "reviewer_a.csv changed"):
                evaluate_locked(root)
            review_path.write_bytes(original_review)
            original_test = test_path.read_bytes()
            test_path.write_bytes(original_test + b"\n")
            with self.assertRaisesRegex(ValueError, "test.csv changed"):
                evaluate_locked(root)
            test_path.write_bytes(original_test)
            saved = evaluate_locked(root)
            self.assertEqual(saved["dataset_sha256"], manifest["source_sha256"])
            self.assertEqual(saved["metrics"]["combined"]["confusion"]["tp"] + saved["metrics"]["combined"]["confusion"]["fn"], manifest["class_balance"]["test"]["1"])
            with self.assertRaises(FileExistsError):
                freeze_split(root, seed=7)
            with self.assertRaises(FileExistsError):
                evaluate_locked(root)


if __name__ == "__main__":
    unittest.main()
