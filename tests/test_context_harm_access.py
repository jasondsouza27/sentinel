"""Synthetic frozen studies and durable final-access regression tests."""
import importlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from sentinel.context_harm.contracts import FrozenStudy, HarmCase, HarmCriteria, HarmError, ModelText
from sentinel.context_harm.integrity import canonical_sha256, publish_stage, read_json, sha256, write_json
from sentinel.context_harm.source import default_settings


def make_study(root, *, test=None, diagnostics=()):
    from sentinel.context_harm.protocol import implementation_hashes, serialize_case
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    parts = {}
    for name in ('train', 'validation', 'calibration'):
        parts[name] = tuple(HarmCase(f'{name}-{index}',
            ModelText('ordinary invented discussion' if index % 2 == 0 else 'you are stupid',
                      ('An invented preceding turn.',)), ('earlier-' + str(index),),
            f'{name}-thread-{index // 2}', index % 2,
            {'labels': ['Neutral'] if index % 2 == 0 else ['PersonDirectedAbuse'],
             'author_id': None, 'community': 'invented', 'coverage': {
                 'available_context_turns': 1, 'used_context_turns': 1}})
            for index in range(8))
    if test is None:
        test = tuple(HarmCase(f'test-{index}',
            ModelText('ordinary invented discussion' if index % 2 == 0 else 'you are stupid',
                      ('An invented preceding turn.',)), ('prior-' + str(index),),
            f'test-thread-{index // 2}', index % 2,
            {'labels': ['CounterSpeech'] if index % 2 == 0 else ['PersonDirectedAbuse'],
             'context_tags': ['PreviousContent'], 'author_id': None, 'community': 'invented',
             'coverage': {'available_context_turns': 1, 'used_context_turns': 1}})
            for index in range(24))
    parts.update(test=tuple(test), diagnostics=tuple(diagnostics))
    settings = default_settings()
    binding = {
        'schema_version': 1, 'task': 'english_directed_abuse', 'status': 'frozen',
        'synthetic': True, 'criteria': asdict(HarmCriteria(2, 1, 1, 1, 1, 1, 0.7)),
        'settings': settings, 'config_sha256': canonical_sha256(settings),
        'source': {'provenance': 'invented_fixture'}, 'code_hashes': implementation_hashes(),
        'case_hashes': {name: canonical_sha256([serialize_case(row) for row in rows])
                        for name, rows in parts.items()},
        'audit': {'status': 'ready', 'history': {}, 'purges': {}},
        'allocation': {'seed': 42, 'fractions': [0.7, 0.15, 0.15]},
        'models_trained': False, 'final_test_scored': False,
    }
    stage = root / 'stage'
    stage.mkdir()
    write_json(stage / 'study.json', binding)
    components = {name: {row.case_id: 'component-' + row.thread_id for row in rows}
                  for name, rows in parts.items()}
    write_json(stage / 'components.json', {
        'development': {case_id: group for name in ('train', 'validation', 'calibration')
                        for case_id, group in components[name].items()},
        'test': {**components['test'], **components['diagnostics']},
    })
    for name, rows in parts.items():
        with (stage / (name + '.jsonl')).open('x', encoding='utf-8') as stream:
            import json
            for row in rows:
                stream.write(json.dumps(serialize_case(row), sort_keys=True) + '\n')
    manifest = publish_stage(stage, root / 'v1',
                             {path.name: sha256(path) for path in stage.iterdir()})
    return FrozenStudy(root / 'v1', {key: value for key, value in manifest.items()
                                    if key != 'manifest_sha256'})


class AccessTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module('sentinel.context_harm.access')
        except ModuleNotFoundError as error:
            if error.name == 'sentinel.context_harm.access':
                self.fail('Durable harm final-access reservations are missing')
            raise
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = make_study(self.root / 'study')

    def identity(self, **changes):
        binding = read_json(self.study.path / 'study.json')
        identity = {
            'artifact_manifest_sha256': 'a' * 64,
            'implementation': self.api.execution_identity(),
            'selected_settings': {'target_cpu': {'raw_threshold': 0.5},
                                  'context_cpu': {'raw_threshold': 0.5}},
            'preprocessing': binding['settings']['context'],
            'cohorts': binding['case_hashes'],
            'coverage': {'cpu': 'full_primary', 'neural': 'unavailable'},
            'tokenizer_base_hashes': {},
            'bootstrap': {'seed': 42, 'replicates': 1000,
                          'unit': 'connected_test_thread_author_duplicate_component'},
            'output': str((self.root / 'public-report').resolve()),
        }
        identity.update(changes)
        return identity

    def test_reservation_is_durable_before_loading_and_identical_interruption_resumes(self):
        receipt = self.api.begin_final_access(self.study, self.identity())
        saved = read_json(self.study.path.parent / 'final-access.json')
        self.assertEqual(saved, receipt)
        self.assertEqual(receipt['status'], 'reserved')
        self.assertEqual(self.api.begin_final_access(self.study, self.identity()), receipt)
        rows = self.api.load_final_test(self.study, receipt)
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[0].case_id, 'test-0')

    def test_fabricated_or_modified_receipt_cannot_load_protected_cases(self):
        with self.assertRaises(HarmError):
            self.api.load_final_test(self.study, {'status': 'reserved'})
        receipt = self.api.begin_final_access(self.study, self.identity())
        forged = {**receipt, 'reservation_id': 'forged'}
        with self.assertRaises(HarmError):
            self.api.load_final_test(self.study, forged)
        self.assertNotEqual(read_json(self.study.path.parent / 'final-access.json'), forged)

    def test_different_identity_cannot_resume_or_change_frozen_selection(self):
        receipt = self.api.begin_final_access(self.study, self.identity())
        for altered in [self.identity(artifact_manifest_sha256='b' * 64),
                        self.identity(output=str(self.root / 'other-output')),
                        self.identity(coverage={'cpu': 'changed'}),
                        self.identity(selected_settings={'target_cpu': {'raw_threshold': 0.1}})]:
            with self.subTest(altered=altered), self.assertRaises(HarmError):
                self.api.begin_final_access(self.study, altered)
        self.assertEqual(read_json(self.study.path.parent / 'final-access.json'), receipt)

    def test_completed_final_evaluation_cannot_be_loaded_reserved_or_completed_again(self):
        receipt = self.api.begin_final_access(self.study, self.identity())
        self.api.finish_final_access(self.study, receipt, 'c' * 64)
        saved = read_json(self.study.path.parent / 'final-access.json')
        self.assertEqual(saved['status'], 'complete')
        self.assertEqual(saved['report_sha256'], 'c' * 64)
        for operation in (lambda: self.api.begin_final_access(self.study, self.identity()),
                          lambda: self.api.load_final_test(self.study, receipt),
                          lambda: self.api.finish_final_access(self.study, receipt, 'd' * 64)):
            with self.assertRaises(HarmError):
                operation()

    def test_concurrent_different_callers_cannot_both_reserve(self):
        identities = [self.identity(output=str(self.root / str(index))) for index in range(2)]
        def reserve(identity):
            try:
                return self.api.begin_final_access(self.study, identity)
            except HarmError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(reserve, identities))
        self.assertEqual(sum(receipt is not None for receipt in receipts), 1)
        self.assertEqual(read_json(self.study.path.parent / 'final-access.json')['status'], 'reserved')

    def test_changed_execution_code_or_study_blocks_reserved_test_loading(self):
        receipt = self.api.begin_final_access(self.study, self.identity())
        changed = {**self.api.execution_identity(), 'sha256': 'd' * 64}
        with patch.object(self.api, 'execution_identity', return_value=changed), self.assertRaises(HarmError):
            self.api.load_final_test(self.study, receipt)
        with (self.study.path / 'test.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('{}\n')
        with self.assertRaises(HarmError):
            self.api.load_final_test(self.study, receipt)

    def test_missing_identity_fields_or_bootstrap_override_is_refused_before_reservation(self):
        for bad in ({}, self.identity(bootstrap={'seed': 7, 'replicates': 10}),
                    self.identity(cohorts={}), self.identity(artifact_manifest_sha256='invalid')):
            with self.subTest(identity=bad), self.assertRaises(HarmError):
                self.api.begin_final_access(self.study, bad)
        self.assertFalse((self.study.path.parent / 'final-access.json').exists())


if __name__ == '__main__':
    unittest.main()
