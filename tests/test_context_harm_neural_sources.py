"""Pinned source admissions; all acquired bytes here are explicit fixtures."""
import copy
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from sentinel.context_harm.contracts import HarmError
from sentinel.context_harm.integrity import canonical_sha256

CATALOG = Path('output/research/context-harm-neural-package-catalog.json')
REVISION = '12040accade4e8a0f71eabdb258fecc2e7e948be'
FILES = ('model.safetensors','config.json','tokenizer.json','tokenizer_config.json','vocab.txt','LICENSE','README.md')


def model_fixture():
    contents = {name: ('SYNTHETIC ' + name).encode() for name in FILES}
    siblings = []
    for name, content in contents.items():
        blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        item = {'rfilename': name, 'size': len(content), 'blobId': blob}
        if name == 'model.safetensors':
            item['lfs'] = {'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}
        siblings.append(item)
    return {'sha': REVISION, 'id': 'distilbert/distilbert-base-uncased', 'siblings': siblings}, contents


class FakeResponse:
    def __init__(self, content, url, delay=0):
        self.body, self.url, self.delay = io.BytesIO(content), url, delay
        self.status, self.headers = 200, {'Content-Length': str(len(content))}
    def read(self, count):
        if self.delay:
            time.sleep(self.delay)
        return self.body.read(count)
    def geturl(self):
        return self.url
    def close(self):
        self.body.close()


class NeuralSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def module(self):
        try:
            return importlib.import_module('sentinel.context_harm.neural_sources')
        except ModuleNotFoundError:
            self.fail('pinned neural source admission is missing')

    def test_catalog_pins_all_twenty_six_wheels_and_offline_hash_installation(self):
        module = self.module()
        catalog = module.load_catalog(CATALOG)
        self.assertEqual(len(catalog['packages']), 26)
        self.assertEqual(canonical_sha256(catalog), '3258969ce816008b95fbeb16232f84687e5dbe5d628fd8c56aaad9b3abe994a0')
        lock = module.lock_text(catalog)
        self.assertEqual(len([line for line in lock.splitlines() if line and not line.startswith('#')]), 26)
        for package in catalog['packages']:
            self.assertIn(package['name'] + '==' + package['version'] + ' --hash=sha256:' + package['sha256'], lock)
        commands = module.installation_commands(Path('bootstrap-python.exe'), self.root/'.venv-harm-neural', self.root/'wheels', self.root/'neural.lock')
        self.assertIn('--no-index', commands[1])
        self.assertIn('--require-hashes', commands[1])
        self.assertIn('check', commands[2])
        self.assertNotIn('requirements-ml-win-py311.lock.txt', str(commands))

    def test_catalog_mutation_is_rejected_before_acquisition(self):
        module = self.module()
        value = json.loads(CATALOG.read_text())
        value['packages'][0]['sha256'] = '0' * 64
        path = self.root/'catalog.json'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(HarmError, 'neural_catalog_changed'):
            module.load_catalog(path)

    def test_changed_wheel_bytes_cannot_pass_verification(self):
        module = self.module()
        catalog = {'packages': [{'filename': 'fixture.whl', 'sha256': hashlib.sha256(b'original').hexdigest(), 'size_bytes': 8}]}
        (self.root/'fixture.whl').write_bytes(b'changed!')
        with self.assertRaisesRegex(HarmError, 'neural_wheel_changed'):
            module.verify_wheelhouse(self.root, catalog)

    def test_wrong_revision_and_unexpected_model_member_ownership_fail(self):
        module = self.module()
        metadata, _ = model_fixture()
        metadata['sha'] = 'main'
        with self.assertRaisesRegex(HarmError, 'neural_model_revision_changed'):
            module.model_metadata(metadata)
        metadata, _ = model_fixture()
        metadata['siblings'].append(copy.deepcopy(metadata['siblings'][0]))
        with self.assertRaisesRegex(HarmError, 'neural_model_metadata_invalid'):
            module.model_metadata(metadata)

    def test_changed_git_and_lfs_blob_bytes_are_rejected(self):
        module = self.module()
        metadata, contents = model_fixture()
        expected = module.model_metadata(metadata)
        for name, content in contents.items():
            (self.root/name).write_bytes(content)
        hashes = module.verify_model_members(self.root, expected)
        self.assertEqual(set(hashes), set(FILES))
        for name in ('model.safetensors', 'tokenizer.json'):
            original = (self.root/name).read_bytes()
            (self.root/name).write_bytes(b'x' * len(original))
            with self.assertRaisesRegex(HarmError, 'neural_model_blob_changed'):
                module.verify_model_members(self.root, expected)
            (self.root/name).write_bytes(original)

    def test_wheel_body_budget_and_deadline_remain_durable_on_failure(self):
        module = self.module()
        url = 'https://files.pythonhosted.org/fixture.whl'
        body = b'0123456789012345'
        catalog = {'packages': [{'name':'fixture','filename':'fixture.whl','url':url,'sha256':hashlib.sha256(body).hexdigest(),'size_bytes':len(body)}]}
        small = {'allow_hosts':['files.pythonhosted.org'],'deadline_seconds':10,'max_received_body_bytes':8,'max_attempts':1}
        with patch('sentinel.context_harm.transport.open_response', return_value=FakeResponse(body, url)):
            with self.assertRaisesRegex(HarmError, 'source_body_budget_exceeded'):
                module._download_wheels(self.root/'budget', catalog, limits=small)
        journal = json.loads((self.root/'budget/journal.json').read_text())
        self.assertEqual(journal['received_body_bytes'], 8)
        self.assertFalse((self.root/'budget/fixture.whl').exists())
        slow = {**small, 'max_received_body_bytes':100, 'deadline_seconds':.01}
        with patch('sentinel.context_harm.transport.open_response', return_value=FakeResponse(body, url, delay=.03)):
            with self.assertRaisesRegex(HarmError, 'source_deadline_exceeded'):
                module._download_wheels(self.root/'deadline', catalog, limits=slow)
        self.assertFalse((self.root/'deadline/fixture.whl').exists())

    def test_unavailable_protected_cohort_records_failure_without_network_or_wheels(self):
        module = self.module()
        with patch('sentinel.context_harm.transport.AcquisitionSession.fetch', side_effect=AssertionError('failed cohort downloads package/model bodies')):
            report = module.prepare_neural_sources(self.root, CATALOG)
        self.assertEqual((report['status'], report['reason']), ('neural_unavailable', 'protected_cohort_unavailable'))
        self.assertFalse(report['may_fit_full_candidate'])
        self.assertTrue((self.root/'neural-sources-unavailable.json').exists())
        self.assertFalse((self.root/'neural-sources').exists())

    def test_low_free_disk_rejects_before_first_wheel_body(self):
        module = self.module()
        with patch('shutil.disk_usage', return_value=type('Disk',(),{'free':12*1024**3-1})()):
            with self.assertRaisesRegex(HarmError, 'neural_disk_capacity_unavailable'):
                module.require_disk_capacity(self.root)


if __name__ == '__main__':
    unittest.main()
