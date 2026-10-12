import json
import unittest
from unittest.mock import patch

from sentinel.paired.models import BranchCandidate
from sentinel.paired.evaluation import Selection, evaluate_branches, fit_calibrators, select_candidates


def rows(count=40):
    return [{"case_id": f"case-{i}", "label": str(i % 2),
             "message": "Synthetic", "url": f"https://case{i}.example/x",
             "source_name": "source", "channel": "sms"} for i in range(count)]


def candidate(kind, config_id):
    return BranchCandidate(kind, config_id, object(), {"peak_bytes": 123, "train_rows": 50})


class EvaluationTests(unittest.TestCase):
    def test_validation_selection_obeys_fpr_budget_and_ties(self):
        cohort = rows()
        candidates = {
            "message": (candidate("message", "m1"), candidate("message", "m2")),
            "url": (candidate("url", "u1"),),
            "combined": (candidate("early", "c1"), candidate("late", "c2")),
        }
        good = [.8 if row["label"] == "1" else .2 for row in cohort]
        bad = [.2 if row["label"] == "1" else .8 for row in cohort]
        scores = {"m1": good, "m2": good, "u1": bad, "c1": good, "c2": good}
        with patch("sentinel.paired.evaluation.score_candidate", side_effect=lambda item, subset: scores[item.config_id]):
            selected = select_candidates(candidates, cohort)
        self.assertEqual(selected["message"].candidate.config_id, "m1")
        self.assertEqual(selected["combined"].candidate.config_id, "c1")
        self.assertIsNone(selected["url"].raw_threshold)
        self.assertLessEqual(selected["message"].validation_report["fpr"], .05)
        self.assertEqual(selected["url"].validation_report["confusion"]["fp"], 0)

    def test_calibration_sparse_and_final_report_suppress_confidence(self):
        validation = rows(12)
        selections = {key: Selection(candidate(key, key), .5, {}) for key in ("message", "url", "combined")}
        score_map = {
            "message": [.7 if row["label"] == "1" else .3 for row in validation],
            "url": [.6 if row["label"] == "1" else .4 for row in validation],
            "combined": [.9 if row["label"] == "1" else .1 for row in validation],
        }
        with patch("sentinel.paired.evaluation.score_candidate", side_effect=lambda item, subset: score_map[item.config_id]):
            calibrators = fit_calibrators(selections, validation)
            report = evaluate_branches(selections, validation, calibrators,
                                       {row["case_id"]: f"group-{i}" for i, row in enumerate(validation)},
                                       replicates=40)
        self.assertEqual({calibration.status for calibration in calibrators.values()}, {"unavailable"})
        for branch in report["branches"].values():
            self.assertIsNone(branch["brier"])
            self.assertIsNone(branch["ece"])
            self.assertEqual(branch["rows"], 12)
        self.assertIn("combined_minus_message", report["paired_deltas"])
        self.assertIn("combined_minus_url", report["paired_deltas"])
        self.assertEqual(report["bootstrap"]["unit"], "connected_group")
        serialized = json.dumps(report)
        self.assertNotIn("case-", serialized)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("Synthetic", serialized)

    def test_identical_cases_required_across_branches(self):
        cohort = rows(4)
        selections = {key: Selection(candidate(key, key), .5, {}) for key in ("message", "url", "combined")}
        from sentinel.url_ml.contracts import Calibration
        calibrators = {key: Calibration("unavailable", None, None, None, {}) for key in selections}
        with patch("sentinel.paired.evaluation.score_candidate", side_effect=[[.1] * 4, [.1] * 3]):
            with self.assertRaises(ValueError):
                evaluate_branches(selections, cohort, calibrators,
                                  {row["case_id"]: row["case_id"] for row in cohort}, replicates=10)

    def test_paired_deltas_use_the_same_group_resamples(self):
        cohort = rows(20)
        selections = {key: Selection(candidate(key, key), .5, {}) for key in ("message", "url", "combined")}
        from sentinel.url_ml.contracts import Calibration
        calibrators = {key: Calibration("unavailable", None, None, None, {}) for key in selections}
        base = [.9 if row["label"] == "1" else .1 for row in cohort]
        message = base.copy()
        url = base.copy()
        message[1] = .1
        url[1] = .1
        url[3] = .1
        scores = {"message": message, "url": url, "combined": base}
        with patch("sentinel.paired.evaluation.score_candidate", side_effect=lambda item, subset: scores[item.config_id]):
            report = evaluate_branches(selections, cohort, calibrators,
                                       {row["case_id"]: f"g{i}" for i, row in enumerate(cohort)},
                                       replicates=100)
        self.assertGreater(report["paired_deltas"]["combined_minus_message"]["recall_delta"], 0)
        self.assertGreater(report["paired_deltas"]["combined_minus_url"]["recall_delta"], 0)
        self.assertIsNotNone(report["paired_deltas"]["combined_minus_message"]["recall_interval"])


if __name__ == "__main__":
    unittest.main()
