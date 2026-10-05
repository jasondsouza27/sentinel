import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from url_ml_fixtures import HAS_ML,fixture_psl,small_run

@unittest.skipUnless(HAS_ML,"Optional URL ML environment is not installed")
class ServiceTests(unittest.TestCase):
    def setUp(self):
        try: from sentinel.url_ml.service import UrlModelService
        except ImportError: self.fail("URL inference adapter is missing")
        from sentinel.url_ml.urls import UrlParser
        from sentinel.url_ml.artifacts import export_artifact
        self.api=UrlModelService; self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); parser=UrlParser(fixture_psl(self.root))
        self.artifact=self.root / "model"; self.run=small_run(parser)
        export_artifact(self.run,parser,self.artifact,"fixture-v1")

    def test_complete_unsupported_missing_and_uncalibrated(self):
        service=self.api(self.artifact)
        result=service.assess("https://User:Pass@xn--bcher-kva.de/A")
        self.assertEqual(result.state,"complete"); self.assertIn(result.decision,("phishing_flag","not_flagged"))
        self.assertNotIn("probability",result.to_dict()); self.assertNotIn("safe",result.decision)
        self.assertTrue(any("user information" in s for s in result.evidence))
        self.assertTrue(result.uncertainty); self.assertEqual(result.model_version,"fixture-v1")
        self.assertEqual(service.assess("ftp://example.org").state,"not_assessed")
        self.assertEqual(service.assess("").state,"not_assessed")
        missing=self.api(self.root / "missing")
        self.assertEqual(missing.assess("https://example.org/").state,"unavailable")
        self.assertEqual(missing.health()["state"],"unavailable")

    def test_corrupt_or_missing_dependency_never_deserializes(self):
        p=self.artifact / "pipeline.joblib"; p.write_bytes(b"corrupted")
        with patch("joblib.load") as load:
            service=self.api(self.artifact)
            self.assertEqual(service.assess("https://example.org/").state,"unavailable")
            load.assert_not_called()
        with patch("sentinel.url_ml.artifacts.load_artifact",side_effect=ImportError("missing optional dependencies")):
            self.assertEqual(self.api(self.artifact).health()["state"],"unavailable")

    def test_busy_gate_returns_retry_and_releases_after_error(self):
        service=self.api(self.artifact)
        service._gate.acquire()
        try:
            busy=service.assess("https://example.org/")
            self.assertEqual(busy.state,"unavailable"); self.assertIn("retry",busy.recommended_action.lower())
        finally: service._gate.release()
        with patch("sentinel.url_ml.training.raw_scores",side_effect=ValueError("failure")):
            self.assertEqual(service.assess("https://example.org/").state,"unavailable")
        self.assertEqual(service.assess("https://example.org/").state,"complete")

if __name__=="__main__": unittest.main()
