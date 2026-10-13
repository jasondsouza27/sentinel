"""Sparse CPU inputs, fitting and checked scoring; fixtures are invented text."""
from dataclasses import replace
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from sentinel.context_harm.contracts import CandidateRef, HarmCase, HarmError, ModelText


def fixture_rows():
    return (
        HarmCase('n1', ModelText('I appreciate the thoughtful correction.', ('Could we discuss the evidence?',)), ('x1',), 'n-thread', 0, {'author_id': 'SECRET_AUTHOR', 'gold_tag': 'tag'}),
        HarmCase('n2', ModelText('Thanks for explaining the measurements.', ('The earlier estimate needs updating.',)), ('x2',), 'n-thread2', 0, {}),
        HarmCase('p1', ModelText('You are a disgusting worthless fool.', ('We disagree about the proposal.',)), ('x3',), 'p-thread', 1, {}),
        HarmCase('p2', ModelText('Shut up you worthless idiot.', ('I think your result needs checking.',)), ('x4',), 'p-thread2', 1, {}),
    )


class CpuTests(unittest.TestCase):
    def cpu(self):
        try:
            return importlib.import_module('sentinel.context_harm.cpu')
        except ModuleNotFoundError:
            self.fail('sparse CPU model factory is missing')

    def test_metadata_and_gold_labels_cannot_change_model_features_or_scores(self):
        cpu = self.cpu()
        model = cpu.build_cpu_model('context_cpu', {'C': 1.0, 'class_weight': None}).fit(fixture_rows())
        before = model.predict_proba(fixture_rows())
        edited = tuple(replace(row, case_id='different-' + row.case_id, context_ids=('new-id',), thread_id='new-thread',
                               label=1-row.label, metadata={'author_id': 'OTHER', 'gold_context': 'abuse', 'rationale': 'text'}) for row in fixture_rows())
        import numpy as np
        np.testing.assert_array_equal(before, model.predict_proba(edited))
        vocab = set(model.target_vectorizer.vocabulary_) | set(model.context_vectorizer.vocabulary_)
        self.assertNotIn('secret_author', vocab)
        self.assertNotIn('gold_context', vocab)

    def test_context_uses_two_training_only_sparse_feature_spaces(self):
        cpu = self.cpu()
        rows = fixture_rows()
        model = cpu.build_cpu_model('context_cpu', {'C': 0.5, 'class_weight': 'balanced'}).fit(rows)
        validation = (replace(rows[0], model_input=ModelText('validationonlytoken thanks', ('contextvalidationonlytoken evidence',))),)
        matrix = model.transform(validation)
        from scipy import sparse
        self.assertTrue(sparse.issparse(matrix))
        self.assertLessEqual(matrix.shape[1], 60000)
        self.assertNotIn('validationonlytoken', model.target_vectorizer.vocabulary_)
        self.assertNotIn('contextvalidationonlytoken', model.context_vectorizer.vocabulary_)
        self.assertIn('worthless fool', model.target_vectorizer.vocabulary_)
        self.assertNotIn('worthless fool', model.context_vectorizer.vocabulary_)
        self.assertIn('earlier estimate', model.context_vectorizer.vocabulary_)
        self.assertNotIn('earlier estimate', model.target_vectorizer.vocabulary_)

    def test_target_branch_ignores_context_and_uses_identical_prepared_target(self):
        cpu = self.cpu()
        rows = fixture_rows()
        model = cpu.build_cpu_model('target_cpu', {'C': 2.0, 'class_weight': None}).fit(rows)
        import numpy as np
        np.testing.assert_array_equal(model.predict_proba(rows), model.predict_proba(tuple(replace(row, model_input=ModelText(row.model_input.target, ('totally different future text',))) for row in rows)))
        target = cpu.build_cpu_model('target_cpu', {'C': 1.0, 'class_weight': None}).fit(rows)
        context = cpu.build_cpu_model('context_cpu', {'C': 1.0, 'class_weight': None}).fit(rows)
        self.assertEqual(target.target_vectorizer.vocabulary_, context.target_vectorizer.vocabulary_)

    def test_cpu_grid_has_twelve_globally_unique_fixed_configurations(self):
        grid = self.cpu().candidate_grid()
        self.assertEqual(len(grid), 12)
        self.assertEqual(len({item['config_id'] for item in grid}), 12)
        for kind in ('target_cpu', 'context_cpu'):
            entries = [item for item in grid if item['kind'] == kind]
            self.assertEqual({(item['params']['C'], item['params']['class_weight']) for item in entries},
                             {(c, w) for c in (0.5, 1.0, 2.0) for w in (None, 'balanced')})
            self.assertTrue(all(item['config_id'].startswith(kind + '-') for item in entries))
        for params in ({'C': 3.0, 'class_weight': None}, {'C': 1.0, 'class_weight': 'wrong'}, {'C': 1.0, 'class_weight': None, 'max_features': 99999}):
            with self.assertRaises(HarmError):
                self.cpu().build_cpu_model('context_cpu', params)

    def test_preprocessing_masks_urls_and_names_without_metadata_features(self):
        cpu = self.cpu()
        rows = tuple(replace(row, model_input=ModelText(row.model_input.target + ' see https://private.example/name and u/privateuser', row.model_input.context)) for row in fixture_rows())
        model = cpu.build_cpu_model('target_cpu', {'C': 1.0, 'class_weight': None}).fit(rows)
        vocab = model.target_vectorizer.vocabulary_
        self.assertNotIn('privateuser', vocab)
        self.assertNotIn('private', vocab)
        self.assertNotIn('example', vocab)

    def test_importing_cpu_does_not_import_machine_learning_libraries(self):
        import subprocess
        import sys
        child = subprocess.run([sys.executable, '-S', '-c', "import sys; import sentinel.context_harm.cpu; print(any(x in sys.modules for x in ('numpy','sklearn','scipy','joblib','psutil')))"], capture_output=True, text=True, timeout=4)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), 'False')


if __name__ == '__main__':
    unittest.main()

class CpuArtifactTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, '_temporary'):
            cls._temporary.cleanup()

    def _study(self):
        if hasattr(type(self), '_study_cache'):
            return type(self)._study_cache
        from sentinel.context_harm.contracts import CadUtterance, CaseCohort, HarmCriteria, SourceRelease
        from sentinel.context_harm.protocol import _freeze_cohort
        from sentinel.context_harm.source import default_settings
        type(self)._temporary = tempfile.TemporaryDirectory()
        root = Path(type(self)._temporary.name)
        rows, records = [], []
        for index in range(40):
            for label in (0, 1):
                identity, thread = f'c{index}-{label}', f'thread{index}'
                value = ModelText(fixture_rows()[0 if label == 0 else 2].model_input.target + f' item{index}', (f'Earlier item{index}',))
                rows.append(HarmCase(identity, value, (f'context{index}',), thread, label, {'source_split': 'train'}))
                records.append(CadUtterance(identity, thread, None, None, None, ('0',), value.target, 'train',
                                             ('PersonDirectedAbuse',) if label else ('Neutral',), (), True, True, {}))
        for label in (0, 1):
            identity = 'test-' + str(label)
            value = ModelText('Held test sentence ' + str(label), ('Distinct held context',))
            rows.append(HarmCase(identity, value, ('testcontext',), identity, label, {'source_split': 'test'}))
            records.append(CadUtterance(identity, identity, None, None, None, ('0',), value.target, 'test',
                                         ('PersonDirectedAbuse',) if label else ('Neutral',), (), True, True, {}))
        cohort = CaseCohort(tuple(rows), (), SourceRelease(tuple(records), {'synthetic_fixture': True}), {})
        challenge = {'schema_version': 1, 'case_count': 0, 'status': 'pending', 'cad_case_ids': [], 'duplicate_keys': [], 'case_ids': []}
        settings = default_settings()
        study = _freeze_cohort(root / 'study', cohort, settings, challenge, criteria=HarmCriteria(2, 1, 1, 1, 1, 1, .7), synthetic=True)
        type(self)._study_cache = (study, settings, root)
        return type(self)._study_cache

    def _cpu(self):
        module = importlib.import_module('sentinel.context_harm.cpu')
        self.assertTrue(callable(getattr(module, 'fit_cpu_candidates', None)), 'CPU fitting entry point is missing')
        self.assertTrue(callable(getattr(module, 'score_candidate', None)), 'checked CPU scoring entry point is missing')
        return module

    def _trained(self):
        cpu = self._cpu()
        if not hasattr(type(self), '_candidate_cache'):
            study, settings, root = self._study()
            type(self)._candidate_cache = cpu.fit_cpu_candidates(study, root / 'models', settings)
        return type(self)._candidate_cache

    def test_complete_grid_publishes_only_training_vocabulary_and_bound_fit_records(self):
        import os
        import joblib
        from sentinel.context_harm.integrity import canonical_sha256, read_json, sha256
        from sentinel.context_harm.protocol import load_development
        candidates = self._trained()
        study, settings, root = self._study()
        development = load_development(study)
        self.assertEqual(len(candidates), 12)
        self.assertTrue((root / 'models/manifest.json').exists())
        expected_ids = canonical_sha256(sorted(row.case_id for row in development['train']))
        validation_token = development['validation'][0].model_input.target.split()[-1]
        for candidate in candidates:
            record = read_json(candidate.directory / 'fit-record.json')
            self.assertEqual(record, candidate.fit_record)
            self.assertEqual(record['status'], 'ok')
            self.assertEqual(record['train_ids_sha256'], expected_ids)
            self.assertEqual(record['train_rows'], len(development['train']))
            self.assertEqual(record['study_manifest_sha256'], canonical_sha256(study.manifest))
            self.assertEqual(record['cpu_settings'], settings['cpu'])
            self.assertEqual(record['members']['model.joblib'], sha256(candidate.directory / 'model.joblib'))
            self.assertNotEqual(record['fit_runtime']['pid'], os.getpid())
            self.assertEqual(record['fit_runtime']['native_threads'], 4)
            self.assertTrue(record['fit_runtime']['cleanup_complete'])
            model = joblib.load(candidate.directory / 'model.joblib')
            self.assertNotIn(validation_token.casefold(), model.target_vectorizer.vocabulary_)
            self.assertLessEqual(sum(record['feature_counts'].values()), 60000)

    def test_scoring_preserves_case_order_raw_probabilities_and_feature_only_payload(self):
        from sentinel.context_harm.protocol import load_development
        from unittest.mock import patch
        cpu = self._cpu()
        candidate = self._trained()[6]
        study, _, _ = self._study()
        rows = tuple(reversed(load_development(study)['validation']))
        real_run_worker = cpu.run_worker
        payloads = []
        def observe(*args, **kwargs):
            payloads.append(json.loads(kwargs['input_payload']))
            return real_run_worker(*args, **kwargs)
        with patch.object(cpu, 'run_worker', side_effect=observe):
            before = cpu.score_candidate(candidate, rows)
        after = cpu.score_candidate(candidate, tuple(replace(row, label=1-row.label, metadata={'SECRET': 'audit-only'}) for row in rows))
        self.assertEqual(before.case_ids, tuple(row.case_id for row in rows))
        self.assertEqual(before.scores, after.scores)
        self.assertTrue(all(before.coverage))
        self.assertTrue(all(0 <= value <= 1 for value in before.scores))
        self.assertEqual(before.runtime['status'], 'ok')
        for request in payloads:
            self.assertEqual(request['operation'], 'cpu_score')
            self.assertTrue(all(set(row) == {'case_id', 'model_input'} for row in request['rows']))
            self.assertTrue(all(set(row['model_input']) == {'target', 'context'} for row in request['rows']))

    def test_changed_model_hash_is_rejected_before_deserialization(self):
        from unittest.mock import patch
        candidate = self._trained()[0]
        path = candidate.directory / 'model.joblib'
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b'corrupted')
        with patch('joblib.load', side_effect=AssertionError('unverified model reached deserializer')):
            with self.assertRaisesRegex(HarmError, 'cpu_model_hash_changed'):
                self._cpu().score_candidate(candidate, fixture_rows())

    def test_changed_fit_binding_is_rejected_before_deserialization(self):
        from unittest.mock import patch
        candidate = self._trained()[0]
        path = candidate.directory / 'fit-record.json'
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        value = json.loads(original)
        value['study_manifest_sha256'] = '0' * 64
        path.write_text(json.dumps(value), encoding='utf-8')
        with patch('joblib.load', side_effect=AssertionError('unverified fit binding reached deserializer')):
            with self.assertRaisesRegex(HarmError, 'cpu_fit_record_changed'):
                self._cpu().score_candidate(candidate, fixture_rows())

    def test_resource_failure_cannot_publish_a_partial_candidate_grid(self):
        from sentinel.context_harm.contracts import WorkerRecord
        from unittest.mock import patch
        cpu = self._cpu()
        study, settings, root = self._study()
        output = root / 'failed-models'
        real_run_worker, calls = cpu.run_worker, []
        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                return WorkerRecord('unavailable', 'worker_rss_limit_exceeded', {'rss_peak_bytes': 8589934593}, {})
            return real_run_worker(*args, **kwargs)
        with patch.object(cpu, 'run_worker', side_effect=fail_second):
            with self.assertRaisesRegex(HarmError, 'worker_rss_limit_exceeded'):
                cpu.fit_cpu_candidates(study, output, settings)
        self.assertEqual(len(calls), 2)
        self.assertFalse(output.exists())
        failures = list(root.glob('failed-models.failure-*.json'))
        self.assertEqual(len(failures), 1)
        report = json.loads(failures[0].read_text())
        self.assertEqual(report['reason'], 'worker_rss_limit_exceeded')
        self.assertNotIn('worthless fool', json.dumps(report))
        self.assertFalse(any(root.glob('.cpu-stage-*')))

    def test_final_access_receipt_blocks_refitting_before_a_worker_launch(self):
        from unittest.mock import patch
        cpu = self._cpu()
        study, settings, root = self._study()
        receipt = study.path.parent / 'final-access.json'
        receipt.write_text('{}', encoding='utf-8')
        self.addCleanup(receipt.unlink)
        with patch.object(cpu, 'run_worker', side_effect=AssertionError('reserved test permits refitting')):
            with self.assertRaisesRegex(HarmError, 'fitting_forbidden_after_final_access'):
                cpu.fit_cpu_candidates(study, root / 'refit-models', settings)
        self.assertFalse((root / 'refit-models').exists())

    def test_failed_or_mutated_study_never_reaches_training(self):
        from unittest.mock import patch
        cpu = self._cpu()
        study, settings, root = self._study()
        path = study.path / 'train.jsonl'
        original = path.read_bytes()
        self.addCleanup(path.write_bytes, original)
        path.write_bytes(original + b'{}\n')
        with patch.object(cpu, 'run_worker', side_effect=AssertionError('mutated data reaches training')):
            with self.assertRaisesRegex(HarmError, 'study_member_changed'):
                cpu.fit_cpu_candidates(study, root / 'mutated-models', settings)

    def test_unsupported_context_inputs_abstain_without_successful_partial_scores(self):
        candidate = self._trained()[6]
        rows = (replace(fixture_rows()[0], model_input=ModelText('Supported target', ())),
                replace(fixture_rows()[1], model_input=ModelText('x' * 10001, ('Earlier turn',))))
        scores = self._cpu().score_candidate(candidate, rows)
        self.assertEqual(scores.case_ids, ('n1', 'n2'))
        self.assertEqual(scores.scores, (None, None))
        self.assertEqual(scores.coverage, (False, False))

    def test_nonconvergence_does_not_produce_a_usable_model(self):
        import warnings
        from sklearn.exceptions import ConvergenceWarning
        from unittest.mock import patch
        cpu = self._cpu()
        def nonconvergence(*args, **kwargs):
            warnings.warn('solver did not converge', ConvergenceWarning)
        with patch('sklearn.linear_model.LogisticRegression.fit', side_effect=nonconvergence):
            with self.assertRaisesRegex(HarmError, 'cpu_nonconvergence'):
                cpu.build_cpu_model('target_cpu', {'C': 1.0, 'class_weight': None}).fit(fixture_rows())
