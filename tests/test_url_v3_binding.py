import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from url_v3_fixtures import synthetic_v2_root,hashes

class BindingTests(unittest.TestCase):
    def setUp(self):
        try: self.api=importlib.import_module("sentinel.url_v3.binding")
        except ImportError: self.fail("Read-only v2 binding is not implemented")
        from sentinel.url_ml.contracts import DatasetError
        self.Error=DatasetError
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.v2,self.config,self.parser=synthetic_v2_root(self.root)

    def test_failed_historical_gate_and_excluded_component_members_are_bound(self):
        before=hashes(self.v2)
        from sentinel.url_v2 import audit
        original=audit.new_directory
        def protect_input(target):
            if Path(target).resolve().is_relative_to(self.v2.resolve()):
                raise AssertionError("Validation wrote inside the read-only v2 root")
            return original(target)
        with patch("sentinel.url_v2.audit.new_directory",side_effect=protect_input):
            binding=self.api.bind_v2(self.v2,self.root/"study/binding",self.config,self.parser)
        self.assertEqual(binding.anchor_domains,("domain:final.example","domain:heldout.example","domain:linked.example"))
        expected={hashlib.sha256(url.encode()).hexdigest() for url in ("https://heldout.example/test","https://final.example/article?x=1")}
        self.assertEqual(set(binding.primary_owners),expected)
        self.assertEqual(before,hashes(self.v2))
        self.assertEqual(binding.manifest["historical_training_ready"],False)
        loaded=self.api.load_v2_binding(binding.root,self.config,self.parser)
        self.assertEqual(loaded.anchor_domains,binding.anchor_domains)

    def test_changed_projection_audit_or_ownership_never_loads(self):
        binding=self.api.bind_v2(self.v2,self.root/"study/binding",self.config,self.parser)
        for relative in ("sources/phreshphish/projection/observations.jsonl","audited/rows.jsonl","protocol/owners.jsonl"):
            path=self.v2/relative; before=path.read_bytes(); path.write_bytes(before+b"\n")
            try:
                with self.subTest(path=relative),self.assertRaises(self.Error):
                    self.api.load_v2_binding(binding.root,self.config,self.parser)
            finally: path.write_bytes(before)

    def test_rehashed_fabricated_anchor_list_is_not_verified_history(self):
        from sentinel.url_ml.source import sha256
        binding=self.api.bind_v2(self.v2,self.root/"study/binding",self.config,self.parser)
        path=binding.root/"anchors.jsonl"
        path.write_text(path.read_text(encoding="utf-8").replace("linked.example","rogue.example"),encoding="utf-8")
        manifest=json.loads((binding.root/"manifest.json").read_text(encoding="utf-8"))
        manifest["files"]["anchors.jsonl"]=sha256(path)
        manifest["protected_domains_sha256"]=sha256(path)
        (binding.root/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        with self.assertRaises(self.Error): self.api.load_v2_binding(binding.root,self.config,self.parser)

    def test_output_cannot_write_to_input_tree(self):
        before=hashes(self.v2)
        with self.assertRaises(self.Error):
            self.api.bind_v2(self.v2,self.v2/"binding",self.config,self.parser)
        self.assertEqual(before,hashes(self.v2))

    def test_initial_binding_rejects_rehashed_projection_with_different_observation(self):
        from sentinel.url_ml.source import sha256
        projection=self.v2/"sources/phreshphish/projection"
        path=projection/"observations.jsonl"
        lines=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        lines[0]["original_label"]="phish"
        path.write_text("".join(json.dumps(line,sort_keys=True)+"\n" for line in lines),encoding="utf-8")
        manifest=json.loads((projection/"manifest.json").read_text(encoding="utf-8"))
        manifest["files"]["observations.jsonl"]=sha256(path)
        (projection/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        with self.assertRaises(self.Error):
            self.api.bind_v2(self.v2,self.root/"study/binding",self.config,self.parser)
