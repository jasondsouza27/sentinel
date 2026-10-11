import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2.storage import manifest_hash,sha256,read_json,write_json
from url_v3_fixtures import synthetic_study

class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.splits,self.cfg,self.parser=synthetic_study(self.root)
    def test_verified_envelope_is_development_only_and_not_shared_mutable_state(self):
        from sentinel.url_v3.compat import development_bundle,verify_frozen_splits
        bundle=development_bundle(self.splits,self.cfg,self.parser)
        self.assertEqual(set(bundle.partitions),{"train","validation","calibration"})
        self.assertEqual(bundle.manifest["schema"],"url-development-envelope-v3")
        self.assertEqual(bundle.manifest["provenance"]["config_sha256"],manifest_hash(self.cfg))
        bundle.manifest["partitions"]["train"]["rows"]=-1
        verify_frozen_splits(self.splits,self.cfg,self.parser)
    def test_missing_roots_extra_keys_labels_urls_or_memory_owners_fail_before_learner(self):
        from sentinel.url_v3.compat import development_bundle
        variants=[replace(self.splits,root=None),replace(self.splits,audit_root=None),replace(self.splits,study_root=None)]
        other=copy.deepcopy(self.splits); other.tracks["external"]=(); variants.append(other)
        other=copy.deepcopy(self.splits); other.development.partitions["shadow"]=(); variants.append(other)
        for field,value in (("label",1-self.splits.development.partitions["train"][0].label),("url","https://substitute.example/")):
            other=copy.deepcopy(self.splits); rows=list(other.development.partitions["train"]); rows[0]=replace(rows[0],**{field:value})
            other.development.partitions["train"]=tuple(rows); variants.append(other)
        for mapping in ("sources_by_case","component_by_case"):
            other=copy.deepcopy(self.splits); values=getattr(other,mapping); values[next(iter(values))]=("wrong",) if mapping=="sources_by_case" else "0"*64; variants.append(other)
        for other in variants:
            with self.subTest(variant=len(other.tracks)),patch("sentinel.url_ml.training.fit_candidate") as learner:
                with self.assertRaises(DatasetError): development_bundle(other,self.cfg,self.parser)
                learner.assert_not_called()
    def test_all_physical_dependencies_and_config_or_parser_changes_are_rejected(self):
        from sentinel.url_v3.compat import verify_frozen_splits
        verify_frozen_splits(self.splits,self.cfg,self.parser)  # exercise any verified cache first
        paths=[self.root/"config.json",self.parser.psl_path,self.root/"binding/anchors.jsonl",
               self.root/"binding/primary-owners.jsonl",self.root/"sources/mendeley/observations.jsonl",
               self.root/"v2/sources/phreshphish/projection/observations.jsonl",
               self.root/"v2/audited/provenance.jsonl",self.root/"v2/protocol/owners.jsonl",
               self.root/"audited/rows.jsonl"]+[self.root/"protocol"/n for n in ("owners.jsonl","components.jsonl","assignments.json")]
        for path in paths:
            original=path.read_bytes()
            try:
                path.write_bytes(original+b"corruption")
                with self.subTest(path=path.name),self.assertRaises(DatasetError):
                    verify_frozen_splits(self.splits,self.cfg,self.parser)
            finally: path.write_bytes(original)
        changed=copy.deepcopy(self.cfg); changed["split"]["seed"]=43
        with self.assertRaises(DatasetError): verify_frozen_splits(self.splits,changed,self.parser)
    def test_rehashed_mutation_is_not_admitted_by_the_verified_cache(self):
        from sentinel.url_v3.compat import verify_frozen_splits
        verify_frozen_splits(self.splits,self.cfg,self.parser)
        path=self.root/"audited/rows.jsonl"; values=[json.loads(x) for x in path.read_text().splitlines()]
        values[0]["row"]["label"]=1-values[0]["row"]["label"]
        path.write_text("".join(json.dumps(x,sort_keys=True)+"\n" for x in values),encoding="utf-8")
        audit=read_json(self.root/"audited/manifest.json"); audit["files"]["rows.jsonl"]=sha256(path); write_json(self.root/"audited/manifest.json",audit)
        with self.assertRaises(DatasetError): verify_frozen_splits(self.splits,self.cfg,self.parser)
    def test_final_access_locks_protocol_and_only_identical_failed_evaluation_resumes(self):
        from sentinel.url_v3.access import study_guard,begin_final_access,finish_final_access,assert_unscored
        assert_unscored(self.splits)
        with study_guard(self.splits,stage="evaluate"):
            first=begin_final_access(self.splits,"a"*64,"b"*64)
            finish_final_access(self.splits,status="failed")
        with self.assertRaisesRegex(DatasetError,"final_protocol_already_accessed"): assert_unscored(self.splits)
        with study_guard(self.splits,stage="evaluate"):
            self.assertEqual(begin_final_access(self.splits,"a"*64,"b"*64)["protocol_sha256"],first["protocol_sha256"])
            with self.assertRaises(DatasetError): begin_final_access(self.splits,"c"*64,"b"*64)
            with self.assertRaises(DatasetError): begin_final_access(self.splits,"a"*64,"d"*64)
            finish_final_access(self.splits,status="complete",report_sha256="e"*64)
        with study_guard(self.splits,stage="evaluate"):
            with self.assertRaises(DatasetError): begin_final_access(self.splits,"a"*64,"b"*64)
        self.assertEqual(len(list((self.root/"final-access").glob("*.json"))),1)
    def test_unheld_access_and_concurrent_stage_guards_fail(self):
        from sentinel.url_v3.access import study_guard,begin_final_access
        with self.assertRaises(DatasetError): begin_final_access(self.splits,"a"*64,"b"*64)
        with study_guard(self.splits,stage="train"):
            with self.assertRaises(DatasetError):
                with study_guard(self.splits,stage="evaluate"): pass

    def test_cli_study_loader_primes_only_completed_semantic_verification(self):
        from sentinel.url_v3.compat import load_verified_study,development_bundle
        from sentinel.url_v3.binding import load_v2_binding as real_binding
        with patch("sentinel.url_v3.compat.load_v2_binding",wraps=real_binding) as binding:
            loaded=load_verified_study(self.root,self.cfg,self.parser)
            self.assertEqual(binding.call_count,1)
            with patch("sentinel.url_v3.compat.load_v2_binding",side_effect=AssertionError("duplicate semantic replay")):
                self.assertTrue(development_bundle(loaded,self.cfg,self.parser).partitions["train"])
        source=self.root/"sources/mendeley/observations.jsonl"
        with source.open("a",encoding="utf-8") as f: f.write("corruption")
        with self.assertRaises(DatasetError): development_bundle(loaded,self.cfg,self.parser)

if __name__=="__main__": unittest.main()
