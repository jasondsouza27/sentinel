import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sentinel.paired.service import PairedService


class PairedServiceTests(unittest.TestCase):
    def test_missing_or_research_artifact_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            service = PairedService(Path(temporary) / "missing")
            self.assertEqual(service.health()["state"], "unavailable")
            self.assertEqual(service.assess("Pay now", "https://example.com")["state"], "unavailable")
        with patch("sentinel.paired.artifacts.inspect_study_artifact", return_value={"release_status": "research_only"}):
            service = PairedService(Path("research"))
            self.assertEqual(service.assess("Pay now", "https://example.com")["category"], "not_assessed")
            self.assertEqual(service.assess("Pay now", "https://example.com")["unavailable_checks"],
                             ["The paired model is research-only and has not been approved for live warnings."])

    def test_missing_modality_and_malformed_url_are_explicit(self):
        service = PairedService(Path("missing"))
        self.assertIn("message", service.assess("", "https://example.com")["unavailable_checks"][0].lower())
        self.assertIn("url", service.assess("A request", "")["unavailable_checks"][0].lower())
        self.assertIn("url", service.assess("A request", "https://bad.com:broken/")["unavailable_checks"][0].lower())

    def test_tampered_artifact_or_missing_ml_package_cannot_break_rules(self):
        for failure in (ValueError("model.joblib changed"), ImportError("sklearn unavailable")):
            with self.subTest(failure=type(failure).__name__), \
                 patch("sentinel.paired.artifacts.inspect_study_artifact", side_effect=failure):
                service = PairedService(Path("artifact"))
                self.assertEqual(service.health()["state"], "unavailable")
                self.assertEqual(service.assess("Pay fee", "https://example.com")["state"], "unavailable")

    def test_mocked_approved_bundle_reports_separate_cautious_category(self):
        class FakeSelection:
            raw_threshold = .5
            candidate = object()

        class FakeBundle:
            metadata = {"release_status": "approved", "protocol_sha256": "a" * 64}
            selections = {"combined": FakeSelection()}

        with patch("sentinel.paired.artifacts.inspect_study_artifact", return_value=FakeBundle.metadata), \
             patch("sentinel.paired.artifacts.load_study_artifact", return_value=FakeBundle()), \
             patch("sentinel.paired.models.score_candidate", return_value=[.8]):
            result = PairedService(Path("approved")).assess("Pay a fee now", "https://example.com")
        self.assertEqual(result["state"], "available")
        self.assertEqual(result["category"], "review")
        self.assertNotIn("confidence", result)
        self.assertNotIn("safe", str(result).lower())
        self.assertTrue(any("payment" in item.lower() for item in result["evidence"]))


if __name__ == "__main__":
    unittest.main()
