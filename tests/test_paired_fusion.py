import json
import unittest
from pathlib import Path
from unittest.mock import patch

from sentinel.paired.models import LateFusionUnavailable, build_branch, fit_branch_candidates, fit_late_fusion, score_candidate
from sentinel.paired.protocol import connected_groups
from sentinel.url_ml.urls import UrlParser


class FusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = UrlParser(Path(__file__).resolve().parents[1] / "resources" / "url-v2-suffix.dat")

    def _rows(self, count=30):
        return [{"case_id": f"case-{i}", "message": f"uniquephrase{i} "
                 + ("official" if i % 2 == 0 else "urgent") + f" https://case{i}.example/path",
                 "url": f"https://case{i}.example/path", "label": str(i % 2), "campaign_group": ""}
                for i in range(count)]

    def test_every_fold_scores_unseen_cases_and_unseen_groups(self):
        rows = self._rows()
        original = __import__("sentinel.paired.models", fromlist=["_fit_monitored"])._fit_monitored
        calls = []

        def spy(subtrain, kind, params, parser, **kwargs):
            model = build_branch(kind, parser, params).fit(subtrain)
            calls.append((kind, {row["case_id"] for row in subtrain},
                          set(model.vectorizer.vocabulary_) if kind == "message" else set()))
            return model, {"status": "ok", "train_rows": len(subtrain), "peak_bytes": 1}

        with patch("sentinel.paired.models._fit_monitored", side_effect=spy):
            candidate = fit_late_fusion(rows, self.parser, {}, folds=5)
        self.assertEqual(candidate.kind, "late")
        self.assertEqual(len(candidate.fit_record["folds"]), 5)
        self.assertEqual(candidate.fit_record["out_of_fold_rows"], len(rows))
        for fold_index, fold in enumerate(candidate.fit_record["folds"]):
            message_call, url_call = calls[2 * fold_index:2 * fold_index + 2]
            self.assertEqual(message_call[1], url_call[1])
            holdout = {row["case_id"] for row in rows} - message_call[1]
            self.assertTrue(holdout)
            for row in rows:
                if row["case_id"] in holdout:
                    self.assertNotIn(f"uniquephrase{row['case_id'].split('-')[-1]}", message_call[2])
            groups = connected_groups(rows, self.parser)
            self.assertFalse({groups[case_id] for case_id in holdout}
                             & {groups[case_id] for case_id in message_call[1]})
        self.assertEqual(len(score_candidate(candidate, rows)), len(rows))
        self.assertNotIn("uniquephrase", json.dumps(candidate.fit_record))
        self.assertNotIn("case-", json.dumps(candidate.fit_record))

    def test_class_sparse_folds_are_unavailable_without_in_sample_fallback(self):
        rows = self._rows(5)
        for row in rows[:4]:
            row["label"] = "0"
        rows[4]["label"] = "1"
        with patch("sentinel.paired.models._fit_monitored") as fit:
            with self.assertRaisesRegex(LateFusionUnavailable, "late_fusion_unavailable"):
                fit_late_fusion(rows, self.parser, {}, folds=5)
            fit.assert_not_called()

    def test_candidate_grid_includes_late_when_groups_support_it(self):
        def local_fit(subtrain, kind, params, parser, **kwargs):
            return build_branch(kind, parser, params).fit(subtrain), {"status": "ok", "train_rows": len(subtrain), "peak_bytes": 1}

        with patch("sentinel.paired.models._fit_monitored", side_effect=local_fit):
            candidates = fit_branch_candidates(self._rows(), self.parser, {})
        self.assertEqual([candidate.kind for candidate in candidates["combined"]], ["early", "early", "late"])


if __name__ == "__main__":
    unittest.main()
