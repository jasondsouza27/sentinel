import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from url_ml_fixtures import HAS_ML,small_run
from url_v2_fixtures import small_v2_research

@unittest.skipUnless(HAS_ML,"requires ML runtime")
class V2ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory(); cls.research,cls.splits,cls.config,cls.parser=small_v2_research(Path(cls.shared.name))
    @classmethod
    def tearDownClass(cls): cls.shared.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="sentinel artifact "); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
    def test_round_trip_generic_load_and_legacy_scores(self):
        from sentinel.url_v2.artifacts import export_v2_artifact,load_v2_artifact
        from sentinel.url_ml.artifacts import export_artifact,load_artifact,REQUIRED_FILES
        from sentinel.url_ml.training import raw_scores
        import joblib
        urls=["https://alpha.example/article?q=1","http://www.other.example/login"]
        output=self.root/"url-v2"; manifest=export_v2_artifact(self.research,self.parser,output,"fixture-v2")
        self.assertEqual(manifest["schema"],"url-artifact-v2"); self.assertEqual(set(manifest["files"]),REQUIRED_FILES|{"protocol.json","diagnostic.json","diagnostic.joblib"})
        with patch("joblib.load",wraps=joblib.load) as loader: generic=load_artifact(output); self.assertEqual(loader.call_count,1)
        loaded=load_v2_artifact(output)
        self.assertEqual(raw_scores(generic.selection.model,urls).tolist(),raw_scores(self.research.run.selection.model,urls).tolist())
        self.assertEqual(raw_scores(loaded.format_model,urls).tolist(),raw_scores(self.research.format_model,urls).tolist())
        with self.assertRaises(DatasetError): export_v2_artifact(self.research,self.parser,output,"fixture-v2")
        v1=small_run(self.parser); old=self.root/"legacy with spaces"; old_manifest=export_artifact(v1,self.parser,old,"fixture-v1")
        self.assertEqual(set(old_manifest["files"]),REQUIRED_FILES)
        self.assertEqual(raw_scores(load_artifact(old).selection.model,urls).tolist(),raw_scores(v1.selection.model,urls).tolist())
    def test_tampered_files_and_sidecar_meanings_fail_before_deserialization(self):
        from sentinel.url_v2.artifacts import export_v2_artifact,load_v2_artifact
        from sentinel.url_v2.storage import read_json,write_json,sha256
        variants=["bytes","features","protocol","config","schema","provenance_type","protocol_type"]
        for name in variants:
            with self.subTest(name=name):
                output=self.root/name; export_v2_artifact(self.research,self.parser,output,"fixture")
                manifest=read_json(output/"manifest.json")
                if name=="bytes": (output/"diagnostic.joblib").write_bytes(b"corrupt")
                if name=="features":
                    diagnostic=read_json(output/"diagnostic.json"); diagnostic["feature_names"]=["source_id"]*4; write_json(output/"diagnostic.json",diagnostic); manifest["files"]["diagnostic.json"]=sha256(output/"diagnostic.json")
                if name=="protocol":
                    protocol=read_json(output/"protocol.json"); protocol["source_catalog_sha256"]="0"*64; write_json(output/"protocol.json",protocol); manifest["files"]["protocol.json"]=sha256(output/"protocol.json")
                if name=="config": manifest["provenance"]["training_config"]["seed"]=99
                if name=="schema": manifest["schema"]="url-artifact-unknown"
                if name=="provenance_type": manifest["provenance"]=[]
                if name=="protocol_type":
                    write_json(output/"protocol.json",[]); manifest["files"]["protocol.json"]=sha256(output/"protocol.json")
                write_json(output/"manifest.json",manifest)
                with patch("joblib.load") as loader:
                    with self.assertRaises(DatasetError): load_v2_artifact(output)
                    loader.assert_not_called()
    def test_wrong_protocol_rejected_before_export(self):
        from sentinel.url_v2.artifacts import export_v2_artifact
        from sentinel.url_v2.contracts import ResearchRun
        wrong=copy.deepcopy(self.research.protocol); wrong["config_sha256"]="0"*64
        bad=ResearchRun(self.research.run,self.research.format_model,self.research.format_report,wrong)
        with self.assertRaises(DatasetError): export_v2_artifact(bad,self.parser,self.root/"wrong","fixture")
        self.assertFalse((self.root/"wrong").exists())

if __name__=="__main__": unittest.main()
