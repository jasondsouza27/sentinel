import json
import tempfile
import unittest
from pathlib import Path

from paired_fixtures import evidence_case, intake_case, read_csv, write_csv, write_intake
from sentinel.paired.admission import (
    EVIDENCE_FIELDS, finalize_study_reviews, prepare_study_reviews,
    validate_ledger, verify_finalized_study,
)


class PairedAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rows = [intake_case(1), intake_case(2)]
        write_intake(self.root, self.rows)
        self.evidence = [evidence_case(1), evidence_case(2)]
        write_csv(self.root / "evidence_ledger.csv", self.evidence, EVIDENCE_FIELDS)

    def _rewrite(self):
        write_csv(self.root / "evidence_ledger.csv", self.evidence, EVIDENCE_FIELDS)

    def test_ledger_requires_exact_ids_and_permission(self):
        self.assertEqual(len(validate_ledger(self.root, self.rows)), 2)
        self.evidence.pop()
        self._rewrite()
        with self.assertRaisesRegex(ValueError, "case_id"):
            validate_ledger(self.root, self.rows)
        self.evidence.append(evidence_case(2, basis="licensed_public"))
        self._rewrite()
        with self.assertRaisesRegex(ValueError, "permission_basis"):
            validate_ledger(self.root, self.rows)

    def test_ledger_checks_date_hash_and_licensed_provenance(self):
        self.evidence[0]["observed_on"] = "yesterday"
        self._rewrite()
        with self.assertRaisesRegex(ValueError, "observed_on"):
            validate_ledger(self.root, self.rows)
        self.evidence[0]["observed_on"] = ""
        self.evidence[0]["source_sha256"] = "bad"
        self._rewrite()
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            validate_ledger(self.root, self.rows)
        self.rows[0]["collection_basis"] = "licensed_public"
        write_intake(self.root, self.rows)
        self.evidence[0].update(permission_basis="licensed_public", source_sha256="", source_version="")
        self._rewrite()
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            validate_ledger(self.root, self.rows)

    def test_packet_has_opaque_pointers_but_not_source_label_or_verification_text(self):
        self.rows[0]["source_label"] = "phishing"
        write_csv(self.root / "intake.csv", self.rows, tuple(self.rows[0]))
        prepare_study_reviews(self.root)
        packet = (self.root / "case_packet.csv").read_text(encoding="utf-8")
        self.assertIn("ev-1", packet)
        self.assertIn("vault-1", packet)
        self.assertNotIn("phishing", packet)
        self.assertNotIn("source_label", packet)
        self.assertNotIn("record-1", packet)
        self.assertEqual(len(read_csv(self.root / "reviewer_a.csv")), 2)

    def test_ledger_or_packet_edit_blocks_finalize_before_publish(self):
        prepare_study_reviews(self.root)
        for name, reviewer in (("reviewer_a", "a"), ("reviewer_b", "b")):
            rows = read_csv(self.root / f"{name}.csv")
            for index, row in enumerate(rows):
                row.update(reviewer_id=reviewer, review_label=str(index), review_reason="Synthetic")
            write_csv(self.root / f"{name}.csv", rows, tuple(rows[0]))
        original = (self.root / "case_packet.csv").read_bytes()
        (self.root / "case_packet.csv").write_bytes(original + b"changed")
        with self.assertRaisesRegex(ValueError, "case_packet"):
            finalize_study_reviews(self.root)
        self.assertFalse((self.root / "final_pairs.csv").exists())
        (self.root / "case_packet.csv").write_bytes(original)
        self.evidence[0]["verification_ref"] = "vault-modified"
        self._rewrite()
        with self.assertRaisesRegex(ValueError, "evidence_ledger"):
            finalize_study_reviews(self.root)
        self.assertFalse((self.root / "final_pairs.csv").exists())

    def test_final_manifest_detects_later_changes(self):
        prepare_study_reviews(self.root)
        for name, reviewer in (("reviewer_a", "a"), ("reviewer_b", "b")):
            rows = read_csv(self.root / f"{name}.csv")
            for index, row in enumerate(rows):
                row.update(reviewer_id=reviewer, review_label=str(index), review_reason="Synthetic")
            write_csv(self.root / f"{name}.csv", rows, tuple(rows[0]))
        finalize_study_reviews(self.root)
        self.assertEqual(verify_finalized_study(self.root)["final_cases"], 2)
        self.assertEqual(json.loads((self.root / "study_final_manifest.json").read_text())["schema_version"], 1)
        (self.root / "case_packet.csv").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "case_packet"):
            verify_finalized_study(self.root)


if __name__ == "__main__":
    unittest.main()
