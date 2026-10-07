import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

class V2ContractTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api=importlib.import_module('sentinel.url_v2.contracts')
            self.storage=importlib.import_module('sentinel.url_v2.storage')
        except ImportError:
            self.fail('V2 validated contracts and immutable storage are missing')
        from sentinel.url_ml.contracts import DatasetError
        self.Error=DatasetError
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=json.loads(Path('configs/url-ml-v2.json').read_text(encoding='utf-8'))

    def write_config(self, value):
        p=self.root/'config.json'; p.write_text(json.dumps(value),encoding='utf-8'); return p

    def test_configuration_rejects_unsafe_bounds_and_unknown_fields(self):
        good=self.api.load_config(self.write_config(self.config))
        self.assertEqual(good['projection']['batch_rows'],4096)
        self.assertEqual(good['split']['fractions'],{'train':.8,'validation':.1,'calibration':.1})
        for mutate in (
            lambda c:c['projection'].update(max_response_bytes=2147483649),
            lambda c:c['projection'].update(batch_rows=True),
            lambda c:c['projection'].update(allow_hosts=['evil.example']),
            lambda c:c['parser'].update(max_url_chars=2049),
            lambda c:c['sources']['phreshphish'].update(revision='moving-main'),
            lambda c:c.update(unknown='ignored'),
            lambda c:c['training'].update(native_threads=8),
            lambda c:c['split'].update(seed=True),
        ):
            bad=json.loads(json.dumps(self.config)); mutate(bad)
            with self.subTest(value=bad),self.assertRaises(self.Error):
                self.api.load_config(self.write_config(bad))

    def test_provenance_digest_meanings_and_invalid_source_labels(self):
        bad=json.loads(json.dumps(self.config))
        bad['sources']['phreshphish']['label_map']={'benign':1,'phish':0}
        with self.assertRaises(self.Error): self.api.load_config(self.write_config(bad))
        self.assertEqual(self.storage.manifest_hash({'b':2,'a':1}),
                         '43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777')
        with self.assertRaises((ValueError,self.Error)):
            self.storage.manifest_hash({'invalid':float('nan')})

    def test_exclusive_publication_hashes_content_and_rejects_paths(self):
        out=self.root/'immutable'
        manifest=self.storage.publish_jsonl_directory(out,{'rows.jsonl':[{'value':'Original'}]}, {'schema':'fixture'})
        self.assertEqual(json.loads((out/'rows.jsonl').read_text()),{'value':'Original'})
        self.assertEqual(manifest['files']['rows.jsonl'],self.storage.sha256(out/'rows.jsonl'))
        before=(out/'manifest.json').read_bytes()
        with self.assertRaises(self.Error):
            self.storage.publish_jsonl_directory(out,{'rows.jsonl':[]},{'schema':'fixture'})
        self.assertEqual((out/'manifest.json').read_bytes(),before)
        with self.assertRaises(self.Error):
            self.storage.publish_jsonl_directory(self.root/'other',{'../escape.jsonl':[{}]},{})
        self.assertFalse((self.root/'escape.jsonl').exists())

    def test_interrupted_publication_never_publishes_complete_manifest(self):
        def interrupted():
            yield {'row':1}
            raise ValueError('fixture interrupted')
        with self.assertRaises(ValueError):
            self.storage.publish_jsonl_directory(self.root/'incomplete',{'rows.jsonl':interrupted()},{})
        self.assertFalse((self.root/'incomplete').exists())
        self.assertFalse(list(self.root.glob('.pending-*')))

    def test_failure_records_are_unique_preserved_and_redacted(self):
        evidence={'stage':'projection','error_message':'GET https://us.aws.cdn.hf.co/a?signature=SECRET failed',
                  'attempts':[{'received':9,'start':4,'length':8}],'parameters':{'retry':3}}
        first=self.storage.save_failure(self.root,'projection',evidence)
        old=first.read_bytes(); second=self.storage.save_failure(self.root,'projection',evidence)
        self.assertNotEqual(first,second); self.assertEqual(first.read_bytes(),old)
        result=json.loads(old)
        self.assertEqual(result['attempts'][0]['received'],9)
        self.assertNotIn('SECRET',old.decode())
        self.assertEqual(result['parameters'],{'retry':3})

    def test_stdlib_import_does_not_load_optional_libraries(self):
        code="import json,sys; import sentinel.url_v2.contracts,sentinel.url_v2.storage; import sentinel.server; print(json.dumps(list(sys.modules)))"
        result=subprocess.run([sys.executable,'-S','-c',code],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        modules=json.loads(result.stdout)
        for name in ('pyarrow','numpy','sklearn','tldextract'): self.assertNotIn(name,modules)

if __name__=='__main__': unittest.main()
