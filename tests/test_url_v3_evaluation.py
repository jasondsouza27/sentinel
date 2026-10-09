import copy
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError,UrlRow
from sentinel.url_v2.storage import read_json,write_json,manifest_hash
from url_v3_fixtures import small_v3_research

class V3EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory(); base=Path(cls.shared.name)
        cls.research,cls.original,cls.cfg,cls.parser=small_v3_research(base/"study")
        from sentinel.url_v3.artifacts import export_v3_artifact
        cls.artifact=base/"artifact"; export_v3_artifact(cls.research,cls.parser,cls.artifact,"synthetic")
    @classmethod
    def tearDownClass(cls): cls.shared.cleanup()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        study=self.root/"study"; shutil.copytree(self.original.study_root,study)
        self.splits=replace(copy.deepcopy(self.original),root=study/"protocol",audit_root=study/"audited",study_root=study)
    def test_legitimate_queries_only_have_fp_denominator_and_component_uncertainty(self):
        from sentinel.url_v3.evaluation import legitimate_query_metrics
        rows=tuple(UrlRow(str(i),"https://x.example/","https://x.example/page?q="+str(i),0,"domain:"+str(i),"fixture") for i in range(4))
        result=legitimate_query_metrics(rows,[.1,.9,.2,.3],.5,["a","b","c","d"])
        self.assertEqual(result["rows"],4); self.assertEqual(result["false_positives"],1)
        self.assertEqual(result["false_positive_rate"],.25); self.assertEqual(result["components"],4)
        self.assertEqual(result["bootstrap"]["replicates"],1000); self.assertEqual(result["bootstrap"]["seed"],42)
        self.assertNotIn("recall",result); self.assertNotIn("f1",result)
        self.assertIn("exploratory_small_support",result["limitations"])
        constant=legitimate_query_metrics(rows,[.1]*4,.5,["a","b","c","d"])
        self.assertIn("constant_bootstrap_outcomes",constant["limitations"])
        extra=UrlRow("phish","https://x/","https://x.example/?q=phish",1,"domain:x","fixture")
        self.assertEqual(legitimate_query_metrics(rows+(extra,),[.1,.9,.2,.3,1.],.5,["a","b","c","d","x"])["rows"],4)
    def test_frozen_two_track_comparisons_do_not_fit_or_choose_thresholds(self):
        from sentinel.url_v3.evaluation import evaluate_v3,publish_evaluation
        with patch("sentinel.url_ml.training.fit_candidate",side_effect=AssertionError("no fitting")),patch(
                   "sentinel.url_ml.metrics.choose_threshold",side_effect=AssertionError("no threshold selection")):
            report=evaluate_v3(self.splits,self.cfg,self.parser,self.artifact)
        self.assertEqual(report["schema"],"url-final-evaluation-v3")
        self.assertEqual(report["status"],"complete"); self.assertEqual(set(report["tracks"]),{"primary","supplemental"})
        for name,track in report["tracks"].items():
            self.assertEqual(set(track["metrics"]),{"char_tfidf","lexical_hgb","phase0_rules","format_only"})
            for model,points in track["metrics"].items():
                self.assertEqual(set(points),{"0.05","0.01"})
                if model in ("char_tfidf","lexical_hgb"):
                    self.assertEqual(points["0.05"]["raw_threshold"],self.research.run.selection.report["sensitivity"][model]["0.05"]["raw_threshold"])
            self.assertIn("legitimate_queries",track["subgroups"]); self.assertIn("source",track["subgroups"])
            self.assertEqual(track["temporal"]["status"],"unavailable")
        self.assertEqual(report["bootstrap"],{"unit":"domain_connected_component","replicates":1000,"seed":42})
        self.assertIn("observed_tree_rss_peak_bytes",report["fit_resources"][0])
        out=self.root/"public"; publish_evaluation(report,out)
        self.assertTrue((out/"model-card.md").is_file())
        with self.assertRaises(DatasetError): publish_evaluation(report,out)
        for private in ({"note":"https://secret.example/?token=SECRET"},{"case_id":"0"*64},{"note":"0"*64},{"note":"C:\\Users\\private\\data"}):
            bad={**report,**private}
            with self.assertRaises(DatasetError): publish_evaluation(bad,self.root/"blocked")
        serialized=(out/"evaluation.json").read_text()
        self.assertNotIn("case_id",serialized); self.assertNotIn("https://",serialized); self.assertNotIn(str(self.root),serialized)
        with patch("sentinel.url_ml.training.raw_scores",side_effect=AssertionError("completed report must replay without scoring")):
            self.assertEqual(evaluate_v3(self.splits,self.cfg,self.parser,self.artifact),report)
        private=self.splits.study_root/"runs"
        manifests=list(private.glob("evaluation-*/manifest.json")); self.assertEqual(len(manifests),1)
        self.assertEqual(read_json(manifests[0])["artifact_manifest_sha256"],report["artifact_manifest_sha256"])
    def test_first_score_failure_preserves_access_identical_resume_and_refit_refusal(self):
        from sentinel.url_v3.evaluation import evaluate_v3
        from sentinel.url_v3.access import assert_unscored
        from sentinel.url_v3.training import train_v3
        def fail(*args,**kwargs):
            with self.assertRaisesRegex(DatasetError,"final_protocol_already_accessed"): assert_unscored(self.splits)
            raise RuntimeError("https://secret.example/?signature=SECRET C:\\Users\\private\\data")
        with patch("sentinel.url_ml.training.raw_scores",side_effect=fail):
            with self.assertRaises(DatasetError): evaluate_v3(self.splits,self.cfg,self.parser,self.artifact)
        receipt=next((self.splits.study_root/"final-access").glob("*.json"))
        self.assertEqual(read_json(receipt)["status"],"failed")
        changed=self.root/"changed"; shutil.copytree(self.artifact,changed)
        m=read_json(changed/"manifest.json"); m["version"]="changed"; write_json(changed/"manifest.json",m)
        with self.assertRaises(DatasetError): evaluate_v3(self.splits,self.cfg,self.parser,changed)
        with patch("sentinel.url_ml.training.fit_candidate") as fits:
            with self.assertRaisesRegex(DatasetError,"final_protocol_already_accessed"): train_v3(self.splits,self.cfg,self.parser)
            fits.assert_not_called()
        report=evaluate_v3(self.splits,self.cfg,self.parser,self.artifact)
        self.assertEqual(read_json(receipt)["status"],"complete"); self.assertEqual(report["status"],"complete")
        self.assertTrue(list((self.splits.study_root/"failed-runs").glob("*.json")))
        for path in (self.splits.study_root/"failed-runs").glob("*.json"):
            self.assertNotIn("SECRET",path.read_text())
    def test_changed_physical_or_memory_rows_fail_before_deserialization_or_scores(self):
        from sentinel.url_v3.evaluation import evaluate_v3
        bad=copy.deepcopy(self.splits); first=bad.tracks["primary"][0]; bad.tracks["primary"]=(replace(first,label=1-first.label),)+bad.tracks["primary"][1:]
        with patch("joblib.load") as load,patch("sentinel.url_ml.training.raw_scores") as score:
            with self.assertRaises(DatasetError): evaluate_v3(bad,self.cfg,self.parser,self.artifact)
            load.assert_not_called(); score.assert_not_called()
        with (self.splits.root/"owners.jsonl").open("a") as f: f.write("bad")
        with patch("joblib.load") as load:
            with self.assertRaises(DatasetError): evaluate_v3(self.splits,self.cfg,self.parser,self.artifact)
            load.assert_not_called()


    def test_interruption_after_private_report_seal_recovers_without_new_scores(self):
        from sentinel.url_v3.evaluation import evaluate_v3
        from sentinel.url_v3.access import finish_final_access as real_finish
        def interrupted(*args,**kwargs):
            if kwargs["status"]=="complete": raise OSError("interrupted after private seal")
            return real_finish(*args,**kwargs)
        with patch("sentinel.url_v3.evaluation.finish_final_access",side_effect=interrupted):
            with self.assertRaises(DatasetError): evaluate_v3(self.splits,self.cfg,self.parser,self.artifact)
        self.assertEqual(len(list((self.splits.study_root/"runs").glob("evaluation-*/manifest.json"))),1)
        with patch("sentinel.url_ml.training.raw_scores",side_effect=AssertionError("must recover sealed scores")):
            report=evaluate_v3(self.splits,self.cfg,self.parser,self.artifact)
        self.assertEqual(report["status"],"complete")
        receipt=next((self.splits.study_root/"final-access").glob("*.json"))
        self.assertEqual(read_json(receipt)["status"],"complete")

if __name__=="__main__": unittest.main()
