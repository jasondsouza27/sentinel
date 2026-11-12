import json
import tempfile
import unittest
from pathlib import Path

from sentinel.analysis import analyze
from sentinel.scan import MAX_EXPLAINED, scan
from sentinel.text_ml import LABELS
from sentinel.text_ml.service import TextModelService
from sentinel.text_ml.source import clean_text, match_key, template_key
from sentinel.text_ml.splits import describe, make_splits

MANIFEST = {"schema": "sentinel.text_ml.artifact/1", "model_version": "text-ml-test", "labels": list(LABELS),
            "max_length": 128, "temperature": 1.0, "scam_threshold": 0.5, "files": {}, "release": "experimental"}


class FakeBackend:
    """Logits favour smishing for each 'prize'/'claim' word and spam for 'offer'."""
    calls = 0

    def logits(self, texts):
        FakeBackend.calls += len(texts)
        rows = []
        for text in texts:
            lower = text.lower()
            smish = 3.0 * (lower.count("prize") + lower.count("claim"))
            spam = 2.0 * lower.count("offer")
            rows.append([2.0, spam, smish])
        return rows


def service():
    return TextModelService(backend=FakeBackend(), manifest=dict(MANIFEST))


class SourceTests(unittest.TestCase):
    def test_normalization_keys(self):
        self.assertEqual(clean_text("  Hi there\n� "), "Hi there")
        self.assertEqual(match_key("WIN a prize!!"), match_key("win a prize"))
        self.assertEqual(template_key("Call 09061701461 to claim code KL341"),
                         template_key("Call 09061234567 to claim code KL999"))
        self.assertEqual(template_key("Visit www.win-big.com/abc now"), template_key("Visit http://other.example now"))
        self.assertNotEqual(template_key("see you at 5"), template_key("pay the fee at 5"))


class SplitTests(unittest.TestCase):
    def test_groups_never_cross_splits_and_classes_are_stratified(self):
        records = []
        for i in range(300):
            label = LABELS[i % 3]
            group = f"g{i // 2}"  # pairs share a template group
            records.append({"id": f"r{i}", "group": group, "label": label if i % 2 == 0 else records[-1]["label"]})
        splits = make_splits(records, seed=1)
        summary = describe(records, splits)
        self.assertEqual(sum(s["rows"] for s in summary.values()), 300)
        self.assertGreater(summary["train"]["rows"], summary["test"]["rows"])
        for name in ("calibration", "test"):
            self.assertEqual(set(summary[name]["labels"]), set(LABELS))
        self.assertEqual(make_splits(records, seed=1), splits)


class ServiceTests(unittest.TestCase):
    def test_flagged_message_gets_category_probability_and_explanation(self):
        result = service().assess("Claim your prize now at the office")
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["category"], "smishing")
        self.assertTrue(result["flagged"])
        self.assertGreater(result["calibrated_probability"], 0.5)
        words = [c["word"] for c in result["explanation"]]
        self.assertEqual(set(words[:2]), {"Claim", "prize"})
        first = result["explanation"][0]
        self.assertEqual("Claim your prize now at the office"[first["start"]:first["end"]], first["word"])

    def test_ham_message_is_not_flagged_or_explained(self):
        result = service().assess("See you at lunch tomorrow")
        self.assertFalse(result["flagged"])
        self.assertEqual(result["category"], "ham")
        self.assertEqual(result["explanation"], [])

    def test_empty_text_is_not_assessed(self):
        self.assertEqual(service().assess("  ")["state"], "not_assessed")

    def test_missing_or_tampered_artifact_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = TextModelService(Path(directory) / "none")
            self.assertEqual(missing.health()["state"], "unavailable")
            self.assertIn(missing.health()["reason"], ("artifact_not_found", "runtime_not_installed"))
            Path(directory, "model.onnx").write_bytes(b"weights")
            Path(directory, "manifest.json").write_text(json.dumps({**MANIFEST, "files": {"model.onnx": "0" * 64}}))
            tampered = TextModelService(Path(directory))
            self.assertEqual(tampered.health()["reason"], "artifact_checksum_mismatch")
            self.assertEqual(tampered.assess("claim prize")["state"], "unavailable")


class EnsembleTests(unittest.TestCase):
    def test_average_ensemble_combines_both_members(self):
        class Lexical:
            def predict_proba(self, texts):
                return [[0.0, 0.0, 1.0] for _ in texts]  # always smishing
        svc = service()
        svc.lexical, svc.ensemble = Lexical(), "average"
        scores = svc.predict(["See you at lunch tomorrow"])[0]
        # transformer alone says ham (~0.78); averaged with a certain-smishing lexical model
        self.assertGreater(scores["probabilities"]["smishing"], 0.5)
        self.assertAlmostEqual(sum(scores["probabilities"].values()), 1.0, places=3)


class IntegrationTests(unittest.TestCase):
    def test_analyze_includes_learned_assessment(self):
        result = analyze({"message": "Claim your prize today"}, text_model=service())
        self.assertEqual(result["text_model"]["category"], "smishing")
        self.assertNotIn("text_model", analyze({"message": "Claim your prize today"}))

    def test_failing_model_does_not_break_analysis(self):
        class Broken:
            def assess(self, text):
                raise RuntimeError("boom")
        result = analyze({"message": "hello there"}, text_model=Broken())
        self.assertEqual(result["text_model"]["state"], "unavailable")
        self.assertIn("fraud", result)

    def test_scan_uses_model_and_bounds_explanations(self):
        items = [{"id": str(i), "text": f"Claim your prize number {i} today"} for i in range(MAX_EXPLAINED + 3)]
        items.append({"id": "ham", "text": "The library closes at six this evening."})
        items.append({"id": "offer", "text": "Special offer on phone plans this week only for members"})
        items.append({"id": "offer_link", "text": "Special offer on phone plans this week only for members http://offers.example/plans"})
        body = scan({"items": items}, text_model=service())
        results = {r["id"]: r for r in body["results"]}
        self.assertEqual(body["method"], "evidence rules + learned text model")
        self.assertEqual(results["0"]["severity"], "high")  # prize+claim -> high probability
        self.assertIn("learned text model", results["0"]["evidence"][0])
        self.assertEqual(results["ham"]["severity"], "none")
        # The SMS-trained model alone no longer marks text while scanning (it flagged ordinary
        # emails); with a link to back it up, it still does.
        self.assertEqual(results["offer"]["severity"], "none")
        self.assertFalse(results["offer"]["model"]["counted"])
        self.assertIn("backs up the model", results["offer"]["model"]["not_counted_reason"])
        self.assertEqual(results["offer_link"]["severity"], "review")
        self.assertTrue(results["offer_link"]["model"]["counted"])
        explained = [r for r in body["results"] if r["model"] and r["model"].get("explanation")]
        self.assertEqual(len(explained), MAX_EXPLAINED)

    def test_scan_without_model_is_rules_only(self):
        body = scan({"items": [{"id": "a", "text": "Claim your prize today please"}]})
        self.assertEqual(body["method"], "evidence rules")
        self.assertIsNone(body["results"][0]["model"])


class TrainingMetricTests(unittest.TestCase):
    def setUp(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy is only in the text-ml environment")

    def test_threshold_respects_target_fpr(self):
        import numpy as np
        from sentinel.text_ml.training import classification, threshold_for_fpr
        rng = np.random.default_rng(0)
        labels = np.array([0] * 200 + [2] * 50)
        ham = rng.dirichlet([8, 1, 1], 200)
        scam = rng.dirichlet([1, 1, 8], 50)
        probabilities = np.vstack([ham, scam])
        threshold = threshold_for_fpr(probabilities, labels, 0.01)
        report = classification(probabilities, labels, threshold)
        self.assertLessEqual(report["scam_vs_ham"]["false_positive_rate"], 0.01)
        self.assertEqual(sum(sum(row) for row in report["confusion_matrix"]["counts"]), 250)

    def test_temperature_reduces_overconfidence(self):
        import numpy as np
        from sentinel.text_ml.training import fit_temperature
        labels = np.array([0, 1] * 50)
        logits = np.array([[6.0, 0.0, 0.0] if i % 4 else [0.0, 6.0, 0.0] for i in range(100)])
        self.assertGreater(fit_temperature(logits, labels), 1.0)


if __name__ == "__main__":
    unittest.main()
