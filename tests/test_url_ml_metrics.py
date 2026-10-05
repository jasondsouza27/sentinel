import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from url_ml_fixtures import HAS_ML,fixture_psl,sample_dataset

@unittest.skipUnless(HAS_ML,"Optional URL ML environment is not installed")
class MetricTests(unittest.TestCase):
    def setUp(self):
        try: from sentinel.url_ml import metrics
        except ImportError: self.fail("Grouped evaluation metrics are missing")
        self.api=metrics

    def test_counts_undefined_values_threshold_ties_and_budget(self):
        import numpy as np
        y=np.array([0,0,1,1]); scores=np.array([.1,.8,.7,.9])
        m=self.api.point_metrics(y,scores,.75)
        self.assertEqual(m["confusion"],{"tn":1,"fp":1,"fn":1,"tp":1})
        self.assertEqual(m["precision"],.5); self.assertEqual(m["recall"],.5); self.assertEqual(m["fpr"],.5)
        self.assertIsNone(self.api.choose_threshold(np.array([0,0,1]),np.array([.9,.9,.9])))
        threshold=self.api.choose_threshold(y,scores)
        self.assertEqual(threshold,.9)
        empty=self.api.point_metrics(y,scores,None)
        self.assertIsNone(empty["precision"]); self.assertIsNone(empty["brier"])
        self.assertEqual(empty["recall"],0)

    def test_missing_positive_class_has_null_class_metrics(self):
        import numpy as np
        m=self.api.point_metrics(np.array([0,0]),np.array([.1,.9]),.5)
        self.assertIsNone(m["f1"]); self.assertIsNone(m["recall"])
        self.assertIsNone(m["pr_auc"])

    def test_group_bootstrap_resamples_whole_groups_reproducibly(self):
        import numpy as np
        groups=np.array(["a","a","b","b","c","c","d","d"])
        weights=list(self.api.bootstrap_weights(groups,replicates=10,seed=42))
        self.assertEqual(len(weights),10)
        for w in weights:
            self.assertTrue(all(w[i]==w[i+1] for i in (0,2,4,6)))
            self.assertEqual(sum(w),8)
        again=list(self.api.bootstrap_weights(groups,replicates=10,seed=42))
        for a,b in zip(weights,again): np.testing.assert_equal(a,b)
        y=np.array([0,1]*4); scores=np.array([.1,.9]*4)
        report=self.api.grouped_metrics(y,scores,.5,groups,probabilities=scores,replicates=20)
        self.assertEqual(report["bootstrap"]["unit"],"domain_group")
        self.assertEqual(report["intervals"]["recall"],[1,1])
        self.assertEqual(len(report["reliability_bins"]),10)
        self.assertAlmostEqual(report["brier"],.01)
        insufficient=self.api.grouped_metrics(y[:2],scores[:2],.5,groups[:2],replicates=10)
        self.assertIsNone(insufficient["intervals"]["recall"])
        self.assertEqual(len(report["prevalence_scenarios"]),4)

    def test_selection_never_reads_test_and_calibration_is_separate(self):
        import json
        import numpy as np
        from sentinel.url_ml.urls import UrlParser
        from sentinel.url_ml.splits import freeze_splits
        from sentinel.url_ml.contracts import SplitBundle
        from sentinel.url_ml import training
        from sentinel.url_ml.calibration import fit_calibration
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); parser=UrlParser(fixture_psl(root))
            frozen=freeze_splits(sample_dataset(groups=80,parser=parser),root / "split")
            class Poison(dict):
                def __getitem__(self,key):
                    if key=="test": raise AssertionError("Test set read before freezing")
                    return super().__getitem__(key)
            splits=SplitBundle(Poison(frozen.partitions),frozen.manifest)
            config=json.loads(Path("configs/url-ml-v1.json").read_text())
            fits=[]; predictions=[]
            def fit(rows,branch,params,parser,*args,**kwargs):
                fits.append(tuple(r.case_id for r in rows))
                return object(),{"status":"ok","peak_bytes":1,"branch":branch,"params":params}
            def scores(model,urls):
                predictions.append(tuple(urls)); return np.array([.9 if "login-verify" in u else .1 for u in urls])
            with patch.object(training,"fit_candidate",side_effect=fit),patch.object(training,"raw_scores",side_effect=scores),patch("sentinel.url_ml.calibration.fit_calibration",wraps=fit_calibration) as calibrate:
                run=training.train_run(splits,config,parser)
            self.assertEqual(len(fits),10)
            self.assertTrue(all(ids==tuple(r.case_id for r in frozen.partitions["train"]) for ids in fits))
            validation=tuple(r.url for r in frozen.partitions["validation"])
            calibration=tuple(r.url for r in frozen.partitions["calibration"])
            self.assertEqual(predictions,[validation]*10+[calibration])
            self.assertEqual(calibrate.call_count,1)
            self.assertEqual(run.selection.raw_threshold,.9)

if __name__=="__main__": unittest.main()
