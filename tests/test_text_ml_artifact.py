"""Checks against the real exported artifact; skipped when it or the runtime is absent."""
import unittest
from pathlib import Path

from sentinel.text_ml.service import TextModelService

ARTIFACT = Path(__file__).resolve().parent.parent / "models" / "text-ml" / "v1"
ARTIFACT_V2 = ARTIFACT.parent / "v2"


class ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = TextModelService(ARTIFACT)
        if not cls.service.available:
            raise unittest.SkipTest(f"text-ml artifact unavailable: {cls.service.error}")

    def test_health_reports_version(self):
        self.assertEqual(self.service.health(), {"state": "ready", "model_version": "text-ml-v1",
                                                 "ensemble": "transformer", "release": "experimental"})

    def test_clear_scam_is_flagged_with_explanation(self):
        result = self.service.assess("Congratulations! You have won a 1000 prize. Text CLAIM to 80888 to collect")
        self.assertTrue(result["flagged"])
        self.assertIn(result["category"], ("spam", "smishing"))
        self.assertIn("CLAIM", [c["word"] for c in result["explanation"]])

    def test_ordinary_message_is_not_flagged(self):
        for text in ("Running ten minutes late, save me a seat please.",
                     "Notes from today's lab are in the shared folder. The quiz moved to Thursday afternoon."):
            self.assertFalse(self.service.assess(text)["flagged"], text)

    def test_probabilities_are_a_distribution(self):
        probabilities = self.service.predict(["hello there"])[0]["probabilities"]
        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=3)


class ArtifactV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = TextModelService(ARTIFACT_V2)
        if not cls.service.available:
            raise unittest.SkipTest(f"text-ml-v2 artifact unavailable: {cls.service.error}")

    def test_v2_is_the_calibration_selected_ensemble(self):
        health = self.service.health()
        self.assertEqual((health["model_version"], health["ensemble"]), ("text-ml-v2", "average"))

    def test_genuine_transactional_messages_are_not_flagged(self):
        for text in ("Rs.5000.00 credited to your a/c XX7730 by NEFT from RAHUL SHARMA on 04-Nov.",
                     "Your order of 2 items has been shipped and will arrive by Friday. Track it in the app."):
            self.assertFalse(self.service.assess(text)["flagged"], text)

    def test_kyc_phishing_is_flagged(self):
        result = self.service.assess("Your bank KYC has expired and your account will be frozen today. "
                                     "Update immediately at kyc-verify-bank.in-secure.top")
        self.assertTrue(result["flagged"])

    def test_tampered_lexical_member_is_refused(self):
        import shutil, tempfile
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "v2"
            shutil.copytree(ARTIFACT_V2, copy)
            with open(copy / "lexical.joblib", "ab") as stream:
                stream.write(b"tampered")
            self.assertEqual(TextModelService(copy).health()["reason"], "artifact_checksum_mismatch")


if __name__ == "__main__":
    unittest.main()
