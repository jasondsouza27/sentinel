import copy
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

class V3ContractTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api=importlib.import_module("sentinel.url_v3.contracts")
        except ImportError:
            self.fail("URL v3 contracts are not implemented")
        from sentinel.url_ml.contracts import DatasetError
        self.Error=DatasetError
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def config_path(self, value):
        path=self.root/"config.json"; path.write_text(json.dumps(value),encoding="utf-8")
        return path

    def test_config_admits_declared_study_and_rejects_changed_boundaries(self):
        config=self.api.load_config(Path("configs/url-ml-v3.json"))
        self.assertEqual(config["schema"],"url-ml-config-v3")
        self.assertEqual(config["training"]["native_threads"],4)
        self.assertEqual(config["training"]["max_peak_bytes"],8589934592)
        self.assertEqual(config["split"]["development_max_rows"],200000)
        mutations=[
            lambda c:c.update(schema="url-ml-config-v2"),
            lambda c:c.update(extra="shadow"),
            lambda c:c["training"].update(native_threads=True),
            lambda c:c["split"].update(seed=42.0),
            lambda c:c["acquisition"].update(max_received_body_bytes=16777217),
            lambda c:c["acquisition"].update(allow_hosts=["evil.example"]),
            lambda c:c["sources"]["mendeley"].update(sha256="0"*64),
            lambda c:c["sources"]["mendeley"].update(label_map={"legitimate":1,"phishing":0}),
            lambda c:c["support"].update(benign_min_query=29),
        ]
        for mutate in mutations:
            changed=copy.deepcopy(config); mutate(changed)
            with self.subTest(changed=changed),self.assertRaises(self.Error):
                self.api.load_config(self.config_path(changed))

    def test_provenance_requires_parent_anchors_and_named_digests(self):
        from sentinel.url_ml.provenance import validate_provenance
        value={"provenance_schema":"url-provenance-v3","seed":42}
        fields=("source_catalog_sha256","dataset_manifest_sha256","derived_sha256",
                "psl_sha256","parser_code_sha256","protocol_sha256","config_sha256",
                "parent_v2_protocol_sha256","protected_domains_sha256")
        value.update({key:"a"*64 for key in fields})
        validate_provenance(value,stage="development")
        for key in fields:
            missing=dict(value); missing.pop(key)
            with self.subTest(key=key),self.assertRaises(self.Error):
                validate_provenance(missing,stage="development")
        invalid={**value,"source_sha256":"b"*64}
        with self.assertRaises(self.Error): validate_provenance(invalid,stage="development")
        from sentinel.url_ml.splits import manifest_hash
        training={"seed":42}
        artifact={**value,"split_manifest_sha256":"c"*64,"calibration_ids_sha256":"d"*64,
                  "training_config":training,"training_config_sha256":manifest_hash(training)}
        validate_provenance(artifact,stage="artifact")
        artifact["training_config"]={"seed":43}
        with self.assertRaises(self.Error): validate_provenance(artifact,stage="artifact")

    def test_v3_and_v2_configs_are_not_interchangeable(self):
        from sentinel.url_v2.contracts import load_config as load_v2
        with self.assertRaises(self.Error): load_v2(Path("configs/url-ml-v3.json"))
        with self.assertRaises(self.Error): self.api.load_config(Path("configs/url-ml-v2.json"))

    def test_stdlib_contracts_keep_application_dependency_free(self):
        code="import sys; import sentinel.url_v3.contracts; import sentinel.server; assert not any(x in sys.modules for x in ('pyarrow','numpy','sklearn','tldextract'))"
        result=subprocess.run([sys.executable,"-S","-c",code],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
