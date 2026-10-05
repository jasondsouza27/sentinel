import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from url_ml_fixtures import HAS_ML,fixture_psl,small_run

@unittest.skipUnless(HAS_ML,"Optional URL ML environment is not installed")
class ArtifactTests(unittest.TestCase):
    def setUp(self):
        try: from sentinel.url_ml import artifacts
        except ImportError: self.fail("Immutable model artifact feature is missing")
        from sentinel.url_ml.urls import UrlParser
        from sentinel.url_ml.contracts import DatasetError
        self.api,self.Error=artifacts,DatasetError
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.psl=fixture_psl(self.root); self.parser=UrlParser(self.psl)
        self.run=small_run(self.parser); self.out=self.root / "model with spaces"

    def test_export_reload_after_source_removal_and_no_overwrite(self):
        import numpy as np
        from sentinel.url_ml.training import raw_scores
        manifest=self.api.export_artifact(self.run,self.parser,self.out,"fixture-v1")
        before=raw_scores(self.run.selection.model,["HTTPS://a.com:443/A?Token=X"])
        self.psl.unlink()
        loaded=self.api.load_artifact(self.out)
        after=raw_scores(loaded.selection.model,["HTTPS://a.com:443/A?Token=X"])
        np.testing.assert_allclose(before,after,atol=1e-6)
        self.assertEqual(loaded.selection.raw_threshold,self.run.selection.raw_threshold)
        self.assertEqual(manifest["labels"],{"0":"legitimate_url","1":"phishing_url"})
        with self.assertRaises(self.Error): self.api.export_artifact(self.run,self.parser,self.out,"fixture-v1")

    def test_tampered_weights_and_suffix_checked_before_deserialization(self):
        self.api.export_artifact(self.run,self.parser,self.out,"fixture-v1")
        for name in ("pipeline.joblib","suffix.dat"):
            p=self.out / name; original=p.read_bytes(); p.write_bytes(original+b"tamper")
            with patch("joblib.load") as load,self.assertRaises(self.Error): self.api.load_artifact(self.out)
            load.assert_not_called(); p.write_bytes(original)

    def test_bad_schema_dependencies_threshold_and_paths_checked_first(self):
        self.api.export_artifact(self.run,self.parser,self.out,"fixture-v1")
        p=self.out / "manifest.json"; original=json.loads(p.read_text())
        variants=[]
        variants.append({**original,"schema":"future-v99"})
        variants.append({**original,"dependencies":{**original["dependencies"],"numpy":"0.0.0"}})
        variants.append({**original,"selected":{**original["selected"],"raw_threshold":2}})
        variants.append({**original,"files":{**original["files"],"../outside":"a"*64}})
        variants.append({**original,"files":{"pipeline.joblib":original["files"]["pipeline.joblib"]}})
        for variant in variants:
            p.write_text(json.dumps(variant))
            with patch("joblib.load") as load,self.assertRaises(self.Error): self.api.load_artifact(self.out)
            load.assert_not_called()

    def test_predict_cli_handles_paths_with_spaces(self):
        import subprocess,sys
        self.api.export_artifact(self.run,self.parser,self.out,"fixture-v1")
        result=subprocess.run([sys.executable,"-m","sentinel.url_ml.cli","predict","--artifact",str(self.out),"--url","https://example.org/"],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout); self.assertEqual(data["state"],"complete")
        self.assertNotIn("probability",data)

if __name__=="__main__": unittest.main()
