import csv
import json
import tempfile
import unittest
from pathlib import Path

from sentinel.research import _normalized, evaluate_dataset, evaluate_many, features, load_rows, predict, split_rows, train_models


class ResearchTests(unittest.TestCase):
    def test_split_groups_same_wording_with_different_embedded_urls(self):
        rows = [
            {"case_id": str(i), "message": f"Offer {i // 2} at https://site{i}.example/pay",
             "url": f"https://site{i}.example/pay", "label": str(i % 2),
             "domain_group": f"site{i}.example"}
            for i in range(20)
        ]
        self.assertEqual(_normalized(rows[0]["message"]), _normalized(rows[1]["message"]))
        for seed in range(30):
            train, test = split_rows(rows, seed)
            train_messages = {_normalized(row["message"]) for row in train}
            test_messages = {_normalized(row["message"]) for row in test}
            self.assertFalse(train_messages & test_messages)

    def test_split_keeps_cross_domain_campaign_together(self):
        rows = [
            {"case_id": str(i), "message": f"Unique case wording {i}",
             "url": f"https://site{i}.example/pay", "label": str(i % 2),
             "domain_group": f"site{i}.example",
             "campaign_group": "campaign-1" if i in (0, 1) else ""}
            for i in range(20)
        ]
        for seed in range(30):
            train, test = split_rows(rows, seed)
            train_ids = {row["case_id"] for row in train}
            test_ids = {row["case_id"] for row in test}
            self.assertEqual("0" in train_ids, "1" in train_ids)
            self.assertEqual("0" in test_ids, "1" in test_ids)

    def test_globally_unseen_tokens_do_not_change_prediction(self):
        rows = [
            {"case_id": "1", "message": "friendly meeting tomorrow " + " ".join(f"ordinary{i}" for i in range(40)), "url": "https://first.example/", "label": "0", "domain_group": "first.example"},
            {"case_id": "2", "message": "friendly lunch tomorrow", "url": "https://second.example/", "label": "0", "domain_group": "second.example"},
            {"case_id": "3", "message": "pay fee", "url": "https://third.example/", "label": "1", "domain_group": "third.example"},
        ]
        model = train_models(rows)["message"]
        unknowns = " ".join(f"unseen{i}" for i in range(30))
        self.assertEqual(predict(model, unknowns, "https://unseen.example/", "message"), 0)

    def test_message_features_do_not_contain_embedded_url_tokens(self):
        message = "Please read https://secret-bank.example/pay before noon"
        url = "https://secret-bank.example/pay"
        message_features = features(message, url, "message")
        combined_features = features(message, url, "combined")
        self.assertIn("m:please", message_features)
        self.assertNotIn("m:secret", message_features)
        self.assertNotIn("m:bank", message_features)
        self.assertNotIn("m:pay", message_features)
        self.assertNotIn("u:secret", message_features)
        self.assertIn("u:secret", combined_features)

    def test_split_groups_domains_from_all_embedded_links(self):
        rows = [
            {"case_id": str(i), "message": f"Case {i} https://extra{i}.example/path", "url": f"https://first{i}.example/path", "label": str(i % 2), "domain_group": f"first{i}.example"}
            for i in range(12)
        ]
        rows[0]["message"] += " https://shared.example/one"
        rows[1]["message"] += " https://shared.example/two"
        for seed in range(10):
            train, test = split_rows(rows, seed=seed)
            train_ids = {row["case_id"] for row in train}
            test_ids = {row["case_id"] for row in test}
            self.assertEqual("0" in train_ids, "1" in train_ids)
            self.assertEqual("0" in test_ids, "1" in test_ids)

    def test_group_split_prefers_class_balance_when_possible(self):
        rows = [
            {"case_id": str(i), "message": f"Example {i}", "url": f"https://site{i}.example/", "label": "0" if i < 50 else "1", "domain_group": f"site{i}.example"}
            for i in range(100)
        ]
        _, test = split_rows(rows, seed=3)
        self.assertEqual(len(test), 20)
        self.assertEqual(sum(row["label"] == "1" for row in test), 10)

    def test_split_keeps_domains_and_duplicate_messages_together(self):
        rows = [
            {"case_id": str(i), "message": f"Offer {i//2} now", "url": f"https://group{i//2}.example/{i}", "label": str(i % 2), "domain_group": f"group{i//2}.example"}
            for i in range(20)
        ]
        report = evaluate_dataset(rows, seed=9)
        self.assertEqual(report["split_overlap"]["domains"], 0)
        self.assertEqual(report["split_overlap"]["duplicate_messages"], 0)
        self.assertIn("combined", report["metrics"])
        self.assertIn("f1", report["metrics"]["combined"])

    def test_model_can_be_serialized_from_paired_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "pairs.csv"
            rows = [
                {"case_id": str(i), "message": "pay fee now" if i % 2 else "club meeting tomorrow", "url": f"https://{'pay' if i % 2 else 'campus'}{i}.example/", "label": str(i % 2), "domain_group": f"group{i}.example"}
                for i in range(12)
            ]
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            loaded = load_rows(csv_path)
            models = train_models(loaded)
            self.assertIn("combined", json.loads(json.dumps(models)))

    def test_held_out_set_contains_both_labels_when_groups_allow_it(self):
        sample = Path(__file__).resolve().parents[1] / "data" / "example_pairs.csv"
        report = evaluate_dataset(load_rows(sample), seed=42)
        counts = report["metrics"]["combined"]["confusion"]
        self.assertGreater(counts["tp"] + counts["fn"], 0)
        self.assertGreater(counts["tn"] + counts["fp"], 0)
        self.assertEqual(sum(report["class_balance"]["train"].values()), report["train_cases"])
        self.assertEqual(sum(report["class_balance"]["test"].values()), report["test_cases"])
        self.assertIn("macro_f1", report["metrics"]["combined"])

    def test_repeated_seed_report_keeps_each_run_and_metric_ranges(self):
        sample = Path(__file__).resolve().parents[1] / "data" / "example_pairs.csv"
        report = evaluate_many(load_rows(sample), seeds=[11, 23, 42])
        self.assertEqual([run["seed"] for run in report["runs"]], [11, 23, 42])
        self.assertEqual(report["summary"]["combined"]["f1"]["count"], 3)
        self.assertLessEqual(
            report["summary"]["combined"]["f1"]["min"],
            report["summary"]["combined"]["f1"]["max"],
        )


if __name__ == "__main__":
    unittest.main()
