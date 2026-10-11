import unittest
from pathlib import Path

from sentinel.paired.models import build_branch, fit_branch_candidates, score_candidate
from sentinel.url_ml.urls import UrlParser


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = UrlParser(Path(__file__).resolve().parents[1] / "resources" / "url-v2-suffix.dat")

    def _rows(self):
        return [
            {"case_id": f"case-{i}", "message": ("official notice" if i % 2 == 0 else "urgent prize")
             + f" https://case{i}.example/check", "url": f"https://case{i}.example/check", "label": str(i % 2)}
            for i in range(12)
        ]

    def test_factories_have_fixed_bounded_model_contract(self):
        message = build_branch("message", self.parser, {"C": .5})
        url = build_branch("url", self.parser, {"max_depth": 3})
        early = build_branch("early", self.parser, {"C": 1.0})
        self.assertEqual(message.vectorizer.ngram_range, (1, 2))
        self.assertEqual(message.vectorizer.max_features, 30000)
        self.assertEqual(url.classifier.max_iter, 150)
        self.assertEqual(early.vectorizer.max_features, 30000)

    def test_all_branches_score_same_ordered_cases_and_keep_modalities_separate(self):
        rows = self._rows()
        fitted = fit_branch_candidates(rows, self.parser, {})
        self.assertEqual(set(fitted), {"message", "url", "combined"})
        self.assertEqual([len(fitted[key]) for key in ("message", "url", "combined")], [2, 2, 2])
        for candidates in fitted.values():
            for candidate in candidates:
                scores = score_candidate(candidate, rows)
                self.assertEqual(len(scores), len(rows))
                self.assertTrue(all(0 <= value <= 1 for value in scores))
                self.assertEqual(candidate.fit_record["train_rows"], len(rows))
        message = fitted["message"][0]
        url = fitted["url"][0]
        self.assertNotIn("case0", message.model.vectorizer.vocabulary_)
        altered_message = [{**row, "message": "entirely different words " + row["url"]} for row in rows]
        self.assertEqual(score_candidate(url, rows), score_candidate(url, altered_message))
        changed_url = [{**row, "url": "https://replacement.example/other"} for row in rows]
        self.assertEqual(score_candidate(message, rows), score_candidate(message, changed_url))
        with self.assertRaises(ValueError):
            score_candidate(message, [{**rows[0], "url": "not-a-url"}])


if __name__ == "__main__":
    unittest.main()
