import json
import os
import tempfile
import unittest
from pathlib import Path
from url_ml_fixtures import HAS_ML,fixture_psl,sample_dataset

@unittest.skipUnless(HAS_ML,"Optional URL ML environment is not installed")
class TrainingTests(unittest.TestCase):
    def setUp(self):
        try: from sentinel.url_ml import training
        except ImportError: self.fail("Bounded URL model factories are missing")
        from sentinel.url_ml.urls import UrlParser
        self.api=training; self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.parser=UrlParser(fixture_psl(self.root))
        self.rows=sample_dataset(groups=12,parser=self.parser).rows

    def test_train_only_sparse_case_preserving_vocabulary(self):
        import numpy as np
        import scipy.sparse
        model=self.api.fit_pipeline(self.rows,"char_tfidf",{"C":1,"class_weight":None,"max_features":100},self.parser)
        matrix=model.named_steps["tfidf"].transform(["https://heldout.com/zzzzz"])
        self.assertTrue(scipy.sparse.issparse(matrix)); self.assertEqual(matrix.dtype,np.float32)
        self.assertLessEqual(matrix.shape[1],100)
        vocab=model.named_steps["tfidf"].vocabulary_
        self.assertNotIn("zzzzz",vocab)
        # A larger cap proves spelling preservation independently of top-feature ranking.
        full=self.api.fit_pipeline(self.rows,"char_tfidf",{"C":1},self.parser)
        self.assertIn("Token",full.named_steps["tfidf"].vocabulary_)
        self.assertFalse(full.named_steps["tfidf"].lowercase)

    def test_lexical_model_and_class_one_orientation(self):
        import numpy as np
        model=self.api.fit_pipeline(self.rows,"lexical_hgb",{"max_depth":3,"learning_rate":.1,"max_iter":5},self.parser)
        self.assertFalse(model.named_steps["classifier"].early_stopping)
        self.assertEqual(self.api.raw_scores(model,[self.rows[0].url]).shape,(1,))
        class Reversed:
            classes_=np.array([1,0])
            def predict_proba(self,urls): return np.array([[.8,.2] for u in urls])
        self.assertEqual(self.api.raw_scores(Reversed(),["x"])[0],.8)

    def test_grid_bound_and_separate_process_measurement(self):
        config=json.loads(Path("configs/url-ml-v1.json").read_text())
        grid=self.api.candidate_grid(config)
        self.assertEqual(sum(b=="char_tfidf" for b,p in grid),6)
        self.assertEqual(sum(b=="lexical_hgb" for b,p in grid),4)
        model,record=self.api.fit_candidate(self.rows,"char_tfidf",{"C":1},self.parser,native_threads=4)
        self.assertIsNotNone(model); self.assertNotEqual(record["pid"],os.getpid())
        self.assertGreater(record["peak_bytes"],0); self.assertEqual(record["native_threads"],4)
        self.assertEqual(record["status"],"ok")

    def test_pilot_uses_only_whole_training_groups(self):
        from sentinel.url_ml.splits import freeze_splits
        splits=freeze_splits(sample_dataset(groups=40,parser=self.parser),self.root / "splits")
        rows=self.api.pilot_rows(splits,maximum=20,seed=42)
        self.assertLessEqual(len(rows),20); self.assertEqual({r.label for r in rows},{0,1})
        ids={r.case_id for r in rows}; selected={r.domain_group for r in rows}
        train=splits.partitions["train"]
        self.assertTrue(ids <= {r.case_id for r in train})
        self.assertEqual(ids,{r.case_id for r in train if r.domain_group in selected})

if __name__=="__main__": unittest.main()
