import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2.storage import read_json,write_json,sha256,manifest_hash
from url_v3_fixtures import small_v3_research

class V3ArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory()
        cls.research,cls.splits,cls.cfg,cls.parser=small_v3_research(Path(cls.shared.name))
    @classmethod
    def tearDownClass(cls): cls.shared.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="sentinel v3 artifact "); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def test_v3_roundtrip_and_generic_pipeline_only(self):
        from sentinel.url_v3.artifacts import export_v3_artifact,load_v3_artifact
        from sentinel.url_ml.artifacts import load_artifact,REQUIRED_FILES
        from sentinel.url_ml.training import raw_scores
        import joblib
        output=self.root/"artifact"; m=export_v3_artifact(self.research,self.parser,output,"synthetic-v3")
        self.assertEqual(m["schema"],"url-artifact-v3")
        self.assertEqual(set(m["files"]),REQUIRED_FILES|{"protocol.json","diagnostic.json","diagnostic.joblib"})
        with patch("joblib.load",wraps=joblib.load) as loader:
            generic=load_artifact(output)
            self.assertEqual(loader.call_count,1); self.assertEqual(loader.call_args.args[0].name,"pipeline.joblib")
        loaded=load_v3_artifact(output); urls=["https://m0-1.example/article?q=1","https://m1-2.example/article?q=2"]
        self.assertEqual(raw_scores(generic.selection.model,urls).tolist(),raw_scores(self.research.run.selection.model,urls).tolist())
        self.assertEqual(raw_scores(loaded.format_model,urls).tolist(),raw_scores(self.research.format_model,urls).tolist())
        with self.assertRaises(DatasetError): export_v3_artifact(self.research,self.parser,output,"synthetic-v3")
        card=(output/"model-card.md").read_text()
        self.assertIn("Hannousse",card); self.assertIn("group-held-out",card); self.assertIn("No automatic activation",card)
    def test_all_integrity_schema_parent_and_sidecar_mutations_fail_before_deserialization(self):
        from sentinel.url_v3.artifacts import export_v3_artifact,load_v3_artifact
        from sentinel.url_ml.artifacts import load_artifact
        base=self.root/"base"; export_v3_artifact(self.research,self.parser,base,"synthetic")
        variants=("bytes","missing","extra","physical_extra","schema","provenance","config","threshold","parent","anchors",
                  "features","eligible","protocol_type","track_keys")
        for name in variants:
            out=self.root/name; shutil.copytree(base,out); m=read_json(out/"manifest.json")
            if name=="bytes": (out/"diagnostic.joblib").write_bytes(b"corrupt")
            if name=="missing": m["files"].pop("diagnostic.joblib")
            if name in ("extra","physical_extra"):
                (out/"extra.txt").write_text("unregistered")
                if name=="extra": m["files"]["extra.txt"]=sha256(out/"extra.txt")
            if name=="schema": m["schema"]="url-artifact-v2"
            if name=="provenance": m["provenance"]["provenance_schema"]="url-provenance-v2"
            if name=="config": m["provenance"]["training_config"]["seed"]=99
            if name=="threshold": m["selected"]["raw_threshold"]=True
            if name=="anchors": m["provenance"]["protected_domains_sha256"]="0"*64
            if name in ("features","eligible"):
                d=read_json(out/"diagnostic.json")
                d.update(feature_names=["source_id"]*4) if name=="features" else d.update(eligible_for_deployment=True)
                write_json(out/"diagnostic.json",d); m["files"]["diagnostic.json"]=sha256(out/"diagnostic.json")
            if name in ("parent","protocol_type","track_keys"):
                p=read_json(out/"protocol.json")
                if name=="parent": p["parent_v2_protocol_sha256"]="0"*64
                if name=="track_keys": p["tracks"]["external"]=p["tracks"].pop("supplemental")
                if name=="protocol_type": p=[]
                write_json(out/"protocol.json",p); m["files"]["protocol.json"]=sha256(out/"protocol.json")
                m["provenance"]["protocol_sha256"]=manifest_hash(p)
                s=read_json(out/"selection.json"); s["protocol_sha256"]=m["provenance"]["protocol_sha256"]
                write_json(out/"selection.json",s); m["files"]["selection.json"]=sha256(out/"selection.json")
            write_json(out/"manifest.json",m)
            for loader in (load_artifact,load_v3_artifact):
                with self.subTest(name=name,loader=loader.__name__),patch("joblib.load") as deserialize:
                    with self.assertRaises(DatasetError): loader(out)
                    deserialize.assert_not_called()
    def test_wrong_research_protocol_is_rejected_before_export(self):
        from sentinel.url_v3.artifacts import export_v3_artifact
        from sentinel.url_v2.contracts import ResearchRun
        p=copy.deepcopy(self.research.protocol); p["protected_domains_sha256"]="0"*64
        bad=ResearchRun(self.research.run,self.research.format_model,self.research.format_report,p)
        with self.assertRaises(DatasetError): export_v3_artifact(bad,self.parser,self.root/"never-created","synthetic")
        self.assertFalse((self.root/"never-created").exists())

if __name__=="__main__": unittest.main()
