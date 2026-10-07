import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from url_ml_fixtures import HAS_ML
from url_v2_fixtures import small_v2_research

@unittest.skipUnless(HAS_ML,"requires ML runtime")
class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared=tempfile.TemporaryDirectory(); cls.root=Path(cls.shared.name)
        cls.research,cls.splits,cls.config,cls.parser=small_v2_research(cls.root,include_external=False)
        from sentinel.url_v2.artifacts import export_v2_artifact,load_v2_artifact
        cls.artifact=cls.root/"artifact"; export_v2_artifact(cls.research,cls.parser,cls.artifact,"fixture"); cls.loaded=load_v2_artifact(cls.artifact)
    @classmethod
    def tearDownClass(cls): cls.shared.cleanup()
    def test_known_component_metrics_and_constant_bootstrap_disclosure(self):
        from sentinel.url_v2.evaluation import component_metrics
        report=component_metrics([0,0,1,1],[.1,.8,.9,.2],.5,["a","b","c","d"],probabilities=[.1,.8,.9,.2])
        self.assertEqual(report["confusion"],{"tn":1.,"fp":1.,"fn":1.,"tp":1.})
        self.assertEqual(report["fpr"],.5); self.assertAlmostEqual(report["pr_auc"],5/6); self.assertAlmostEqual(report["brier"],.325)
        self.assertEqual(report["bootstrap"]["unit"],"domain_connected_component"); self.assertEqual(report["bootstrap"]["replicates"],1000)
        constant=component_metrics([0,1]*4,[.1,.9]*4,.5,["a","a","b","b","c","c","d","d"])
        self.assertIn("constant_bootstrap_outcomes",constant["limitations"]); self.assertEqual(constant["intervals"]["recall"],[1.,1.])
    def test_frozen_evaluation_no_fit_or_threshold_choice_and_exclusive_public_output(self):
        from sentinel.url_v2.evaluation import evaluate_robustness,publish_evaluation
        with patch("sentinel.url_ml.training.fit_candidate",side_effect=AssertionError("fit called")),patch("sentinel.url_ml.metrics.choose_threshold",side_effect=AssertionError("threshold chosen")):
            report=evaluate_robustness(self.loaded,self.splits,self.artifact)
        self.assertEqual(report["schema"],"url-final-evaluation-v2")
        self.assertEqual(set(report["tracks"]["primary"]["metrics"]),{"char_tfidf","lexical_hgb","phase0_rules","format_only"})
        for model in report["tracks"]["primary"]["metrics"].values(): self.assertEqual(set(model),{"0.05","0.01"})
        self.assertIn("source",report["tracks"]["primary"]["subgroups"])
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"evaluation"; publish_evaluation(report,output)
            serialized=(output/"evaluation.json").read_text()
            self.assertNotIn("https://",serialized); self.assertNotIn(str(self.root),serialized); self.assertNotIn("case_id",serialized)
            self.assertTrue((output/"model-card.md").is_file())
            with self.assertRaises(DatasetError): publish_evaluation(report,output)
    def test_changed_assignments_rejected_before_prediction(self):
        from sentinel.url_v2.evaluation import evaluate_robustness
        from sentinel.url_v2.storage import read_json,write_json
        path=self.root/"protocol"/"assignments.json"; original=path.read_bytes(); values=read_json(path); values["train"].append(values["primary"][0]); write_json(path,values)
        try:
            with patch("sentinel.url_ml.training.raw_scores") as predictor:
                with self.assertRaises(DatasetError): evaluate_robustness(self.loaded,self.splits,self.artifact)
                predictor.assert_not_called()
        finally: path.write_bytes(original)
    def test_changed_in_memory_components_and_source_ownership_rejected(self):
        from dataclasses import replace
        from sentinel.url_v2.evaluation import evaluate_robustness
        altered=[replace(self.splits,component_by_case={key:key for key in self.splits.component_by_case}),
          replace(self.splits,sources_by_case={key:("invented-source",) for key in self.splits.sources_by_case})]
        for splits in altered:
            with self.subTest(splits=splits.root),patch("sentinel.url_ml.training.raw_scores",side_effect=AssertionError("prediction before integrity check")) as predictor:
                with self.assertRaises(DatasetError): evaluate_robustness(self.loaded,splits,self.artifact)
                predictor.assert_not_called()

    def test_v1_pruning_drops_component_linked_through_excluded_development_row(self):
        from sentinel.url_v2.evaluation import paired_rows,paired_differences
        from sentinel.url_v2.protocol import freeze_protocol
        from url_v2_fixtures import synthetic_audit,synthetic_observation,small_protocol_config
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            observations=[synthetic_observation(reference={"shard":"fixture","row":1},original_url="https://old.example/a?q=1",opaque_id="bridge"),
              synthetic_observation(reference={"shard":"fixture","row":2},original_url="https://new.example/a?q=1",opaque_id="bridge",original_partition="test")]
            audit,catalog,parser=synthetic_audit(root,observations); splits=freeze_protocol(audit,catalog,small_protocol_config(parser),root/"protocol")
            rows,blocked=paired_rows(splits.tracks["primary"],splits,{"domain:old.example"})
            self.assertEqual(rows,()); self.assertEqual(len(blocked),1)
        result=paired_differences([0,1]*4,[.1,.9]*4,.5,[.1,.9]*4,.5,["a","a","b","b","c","c","d","d"])
        self.assertEqual(result["intervals"]["f1"],[0.,0.]); self.assertEqual(result["point_difference"]["f1"],0.)

    def test_unavailable_external_metrics_null(self):
        from sentinel.url_v2.evaluation import evaluate_robustness
        report=evaluate_robustness(self.loaded,self.splits,self.artifact)
        self.assertEqual(report["tracks"]["external"]["status"],"unavailable")
        self.assertIsNone(report["tracks"]["external"]["metrics"])
        self.assertEqual(report["tracks"]["primary"]["temporal"]["status"],"unavailable")

if __name__=="__main__": unittest.main()
