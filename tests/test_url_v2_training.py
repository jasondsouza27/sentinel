import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from url_ml_fixtures import HAS_ML
from url_v2_fixtures import synthetic_audit,small_protocol_config
from sentinel.url_ml.contracts import DatasetError

@unittest.skipUnless(HAS_ML,"requires ML runtime")
class V2TrainingTests(unittest.TestCase):
    def setUp(self):
        from sentinel.url_v2.protocol import freeze_protocol
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        audit,self.catalog,self.parser=synthetic_audit(self.root); self.config=small_protocol_config(self.parser)
        self.splits=freeze_protocol(audit,self.catalog,self.config,self.root/"protocol")
    def test_development_envelope_explicit_digest_meanings(self):
        from sentinel.url_v2.compat import development_bundle
        from sentinel.url_ml.provenance import validate_provenance
        from sentinel.url_v2.storage import manifest_hash
        bundle=development_bundle(self.splits)
        self.assertEqual(bundle.manifest["schema"],"url-development-envelope-v2")
        self.assertEqual(bundle.manifest["provenance"]["provenance_schema"],"url-provenance-v2")
        self.assertEqual(bundle.manifest["provenance"]["protocol_sha256"],manifest_hash(self.splits.manifest))
        self.assertNotIn("source_sha256",bundle.manifest["provenance"])
        validate_provenance(bundle.manifest["provenance"],stage="development")
        bad={**bundle.manifest["provenance"],"source_sha256":"a"*64}
        with self.assertRaises(DatasetError): validate_provenance(bad,stage="development")
    def test_fits_train_only_scores_validation_and_calibration_not_final(self):
        from sentinel.url_v2.training import train_v2
        from sentinel.url_ml import training as legacy
        config=json.loads(json.dumps(self.config)); c=config["training"]; c["char_tfidf"].update({"C":[1],"class_weight":[None],"max_features":200}); c["lexical_hgb"].update({"max_depth":[3],"learning_rate":[.1],"max_iter":5})
        from sentinel.url_v2.protocol import freeze_protocol
        from sentinel.url_v2.contracts import AuditBundle
        from sentinel.url_v2.storage import read_json
        audit=AuditBundle(self.root/"audited",read_json(self.root/"audited"/"manifest.json"))
        self.splits=freeze_protocol(audit,self.catalog,config,self.root/"training-protocol")
        fits=[]; scored=[]; original_fit=legacy.fit_candidate; original_scores=legacy.raw_scores
        def fit(rows,*args,**kwargs):
            fits.append({r.case_id for r in rows}); return original_fit(rows,*args,**kwargs)
        def scores(model,urls): scored.append(set(urls)); return original_scores(model,urls)
        with patch.object(legacy,"fit_candidate",side_effect=fit),patch.object(legacy,"raw_scores",side_effect=scores): research=train_v2(self.splits,config,self.parser)
        train={r.case_id for r in self.splits.development.partitions["train"]}; final={r.url for rows in self.splits.tracks.values() for r in rows}
        self.assertEqual(fits,[train,train,train]); self.assertFalse(any(urls & final for urls in scored))
        run=research.run; self.assertEqual(set(run.selection.branch_candidates),{"char_tfidf","lexical_hgb"})
        for entry in run.selection.report["sensitivity"].values(): self.assertEqual(set(entry),{"0.05","0.01"})
        self.assertNotIn("source_sha256",run.provenance); self.assertEqual(run.provenance["training_config_sha256"],hashlib.sha256(json.dumps(c,sort_keys=True,separators=(",",":")).encode()).hexdigest())
        self.assertEqual(research.format_report["feature_names"],["https","www_host","non_root_path","query_present"])
        self.assertNotIn("format_only",run.selection.branch_candidates)
        record=research.format_report["resources"]; self.assertEqual(record["native_threads"],4); self.assertNotEqual(record["pid"],os.getpid()); self.assertLessEqual(record["peak_bytes"],8589934592)
    def test_format_features_and_component_pilot_no_cut(self):
        from sentinel.url_v2.format_baseline import FormatTransformer,build_format_pipeline
        from sentinel.url_v2.training import component_pilot_rows
        transformer=FormatTransformer(self.parser)
        self.assertEqual(transformer.transform(["https://www.alpha.example/","http://other.example/article?q=1"]).tolist(),[[1,1,0,0],[0,0,1,1]])
        rows=component_pilot_rows(self.splits,maximum=8)
        chosen={self.splits.component_by_case[r.case_id] for r in rows}; train=self.splits.development.partitions["train"]
        self.assertEqual({r.case_id for r in rows},{r.case_id for r in train if self.splits.component_by_case[r.case_id] in chosen})
        self.assertLessEqual(len(rows),8)
        pipeline=build_format_pipeline("format_only",{},self.parser); self.assertEqual(pipeline.named_steps["classifier"].C,1)

if __name__=="__main__": unittest.main()
