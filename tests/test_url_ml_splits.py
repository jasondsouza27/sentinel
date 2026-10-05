import json
import tempfile
import unittest
from dataclasses import replace
from itertools import combinations
from pathlib import Path
from url_ml_fixtures import HAS_ML, sample_dataset

@unittest.skipUnless(HAS_ML, "Optional URL ML environment is not installed")
class SplitTests(unittest.TestCase):
    def setUp(self):
        try: from sentinel.url_ml import splits
        except ImportError: self.fail("Frozen domain split feature is missing")
        from sentinel.url_ml.contracts import DatasetError
        self.api,self.Error=splits,DatasetError
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.dataset=sample_dataset()

    def test_reproducible_complete_disjoint_and_reloaded(self):
        a=self.api.freeze_splits(self.dataset,self.root / "first")
        b=self.api.freeze_splits(self.dataset,self.root / "second")
        self.assertEqual(a.manifest,b.manifest)
        self.assertEqual(a,self.api.load_splits(self.dataset,self.root / "first"))
        self.assertEqual(sum(len(v) for v in a.partitions.values()),len(self.dataset.rows))
        for left,right in combinations(a.partitions.values(),2):
            self.assertFalse({r.domain_group for r in left} & {r.domain_group for r in right})
            self.assertFalse({r.url for r in left} & {r.url for r in right})
        for rows in a.partitions.values(): self.assertEqual({r.label for r in rows},{0,1})
        with self.assertRaises(self.Error): self.api.freeze_splits(self.dataset,self.root / "first")

    def test_infeasible_groups_no_random_row_fallback(self):
        from sentinel.url_ml.contracts import DatasetBundle
        tiny=sample_dataset(groups=1)
        with self.assertRaises(self.Error): self.api.freeze_splits(tiny,self.root / "tiny")
        same_group=DatasetBundle(tuple(replace(r,domain_group="domain:one.com") for r in self.dataset.rows),self.dataset.manifest)
        with self.assertRaises(self.Error): self.api.freeze_splits(same_group,self.root / "single")
        self.assertFalse((self.root / "single").exists())

    def test_assignment_and_source_tampering_rejected(self):
        from sentinel.url_ml.contracts import DatasetBundle
        out=self.root / "split"; self.api.freeze_splits(self.dataset,out)
        bad=DatasetBundle(self.dataset.rows,{**self.dataset.manifest,"source_sha256":"c"*64})
        with self.assertRaises(self.Error): self.api.load_splits(bad,out)
        p=out / "assignments.json"; m=json.loads(p.read_text()); m["test"].append(m["train"][0]); p.write_text(json.dumps(m))
        with self.assertRaises(self.Error): self.api.load_splits(self.dataset,out)

if __name__=="__main__": unittest.main()
