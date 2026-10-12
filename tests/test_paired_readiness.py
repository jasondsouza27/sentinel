import json
import tempfile
import unittest
from pathlib import Path

from paired_fixtures import complete_reviews, evidence_case, intake_case, read_csv, write_csv, write_intake
from sentinel.paired.contracts import EVIDENCE_FIELDS, StudyCriteria
from sentinel.paired.readiness import readiness_report


SMALL = StudyCriteria(min_total=8, min_per_class=4, min_test_per_class=1, min_test_domains=2)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _final(self, *, sources=None, months=None, channels=None, collected_months=None):
        rows = [intake_case(i, source=(sources or ["shared"] * 8)[i]) for i in range(8)]
        for i, row in enumerate(rows):
            row["message"] = f"Unique synthetic wording {i} {row['url']}"
            row["channel"] = (channels or ["sms", "email"] * 4)[i]
            if collected_months is not None:
                row["collected_on"] = f"2026-{collected_months[i]:02d}-01"
        write_intake(self.root, rows)
        labels = [i % 2 for i in range(8)]
        complete_reviews(self.root, labels, observed_months=months)
        return labels

    def test_empty_and_pending(self):
        write_intake(self.root, [])
        empty = readiness_report(self.root)
        self.assertEqual(empty["status"], "unavailable")
        self.assertEqual(empty["admitted_cases"], 0)
        write_intake(self.root, [intake_case(1)])
        pending = readiness_report(self.root)
        self.assertEqual(pending["status"], "pending_review")
        self.assertFalse(pending["claim_ready"])

    def test_reviewed_balanced_fixture_is_only_provisionally_eligible(self):
        self._final()
        report = readiness_report(self.root, SMALL)
        self.assertEqual(report["status"], "eligible_for_freeze")
        self.assertTrue(report["claim_ready"])
        self.assertEqual(report["class_counts"], {"0": 4, "1": 4})
        self.assertEqual(report["observation_dates"]["unknown"], 0)
        serialized = json.dumps(report)
        for secret in ("Unique synthetic", "https://", "case-0", "vault-0", "shared"):
            self.assertNotIn(secret, serialized)

    def test_production_target_remains_unavailable(self):
        self._final()
        report = readiness_report(self.root)
        self.assertEqual(report["status"], "unavailable")
        self.assertIn("insufficient_total", report["reasons"])
        self.assertIn("insufficient_class_0", report["reasons"])

    def test_source_confounds_class_and_channel_imbalance_is_reported(self):
        self._final(sources=["source-legit" if i % 2 == 0 else "source-phish" for i in range(8)],
                    channels=["sms"] * 8)
        report = readiness_report(self.root, SMALL)
        self.assertEqual(report["status"], "unavailable")
        self.assertIn("source_label_confounded", report["reasons"])
        self.assertEqual(report["channel_counts"], {"sms": 8})
        self.assertEqual(len(report["source_class_counts"]), 2)
        self.assertNotIn("source-legit", json.dumps(report))

    def test_period_confounds_and_unknown_dates_are_visible(self):
        self._final(months=[1 if i % 2 == 0 else 2 for i in range(8)])
        report = readiness_report(self.root, SMALL)
        self.assertIn("observation_period_confounded", report["reasons"])
        self.assertEqual(report["observation_dates"]["unknown"], 0)

    def test_collection_period_confounds_with_unknown_observation_dates(self):
        self._final(months=[None] * 8,
                    collected_months=[1 if i % 2 == 0 else 9 for i in range(8)])
        report = readiness_report(self.root, SMALL)
        self.assertEqual(report["status"], "unavailable")
        self.assertIn("collection_period_confounded", report["reasons"])
        self.assertEqual(report["observation_dates"], {"known": 0, "unknown": 8})
        self.assertEqual(report["collection_month_class_counts"]["2026-01"], {"0": 4, "1": 0})
        self.assertEqual(report["collection_month_class_counts"]["2026-09"], {"0": 0, "1": 4})

    def test_unknown_observation_dates_are_not_fabricated(self):
        self._final(months=[None, 1, 1, 1, 1, 1, 1, 1])
        report = readiness_report(self.root, SMALL)
        self.assertEqual(report["observation_dates"]["unknown"], 1)
        self.assertEqual(report["observation_dates"]["known"], 7)

    def test_missing_independent_legitimate_verification_is_unavailable(self):
        rows = [intake_case(i) for i in range(8)]
        for i, row in enumerate(rows):
            row["message"] = f"Unique wording {i} {row['url']}"
        write_intake(self.root, rows)
        from sentinel.paired.admission import finalize_study_reviews, prepare_study_reviews
        evidence = [evidence_case(i, kind="source_record" if i % 2 == 0 else "independent_threat_report") for i in range(8)]
        write_csv(self.root / "evidence_ledger.csv", evidence, EVIDENCE_FIELDS)
        prepare_study_reviews(self.root)
        for name, reviewer in (("reviewer_a", "a"), ("reviewer_b", "b")):
            reviews = read_csv(self.root / f"{name}.csv")
            for i, review in enumerate(reviews):
                review.update(reviewer_id=reviewer, review_label=str(i % 2), review_reason="Synthetic")
            write_csv(self.root / f"{name}.csv", reviews, tuple(reviews[0]))
        finalize_study_reviews(self.root)
        report = readiness_report(self.root, SMALL)
        self.assertIn("missing_legitimate_verification", report["reasons"])


if __name__ == "__main__":
    unittest.main()
