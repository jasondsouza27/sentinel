"""Checked research artifacts built only from invented fixtures."""
import importlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_context_harm_access import make_study
from sentinel.context_harm.contracts import CalibrationRecord, CandidateRef, HarmError, Selection
from sentinel.context_harm.integrity import read_json, sha256, write_json


def make_selections(root, study):
    from sentinel.context_harm.cpu import _fit_rows
    from sentinel.context_harm.protocol import load_development
    from sentinel.context_harm.source import default_settings
    development = load_development(study)
    selections, calibrators = {}, {}
    for kind in ('target_cpu', 'context_cpu'):
        directory = Path(root) / kind
        record = _fit_rows(development['train'], kind, {'C': 0.5, 'class_weight': None},
                           directory, study.manifest, default_settings())
        # Explicit controlled resource fixture. This is not a measured study run.
        record.update(synthetic_fixture=True, fit_runtime={
            'ownership': 'windows_job_kill_on_close', 'cleanup_complete': True,
            'monitoring_complete': True, 'native_threads': 4,
            'rss_limit_bytes': 8589934592, 'deadline_seconds': 900,
            'rss_peak_bytes': 1,
        })
        write_json(directory / 'fit-record.json', record, exclusive=True)
        ref = CandidateRef(kind, record['config_id'], directory, record)
        selections[kind] = Selection(ref, 0.5, {'status': 'usable', 'rows': 8,
                                              'recall': 1.0, 'fpr': 0.0, 'precision': 1.0})
        calibrators[kind] = CalibrationRecord('unavailable', None, None,
                                             {'reason': 'synthetic_fixture_support'})
    return selections, calibrators


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module('sentinel.context_harm.artifacts')
        except ModuleNotFoundError as error:
            if error.name == 'sentinel.context_harm.artifacts':
                self.fail('Checked harm research artifacts are missing')
            raise
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = make_study(self.root / 'study')
        self.selected, self.calibrators = make_selections(self.root / 'fitted', self.study)
        self.output = self.root / 'bundle'

    def export(self):
        return self.api.export_artifact(self.selected, self.calibrators, self.study, self.output)

    def test_research_only_schema_round_trip_is_explicit_and_immutable(self):
        metadata = self.export()
        self.assertEqual(metadata['schema_version'], 1)
        self.assertEqual(metadata['release_status'], 'research_only')
        self.assertTrue(metadata['synthetic'])
        self.assertEqual(metadata, self.api.inspect_artifact(self.output, research=True))
        self.assertEqual(len(metadata['model_version']), 64)
        with self.assertRaises(HarmError):
            self.api.inspect_artifact(self.output)
        with self.assertRaises((HarmError, FileExistsError)):
            self.export()

    def test_tampered_weight_and_fit_record_are_rejected_before_scoring(self):
        self.export()
        from sentinel.context_harm import cpu
        model = self.output / 'branches/target_cpu/model.joblib'
        model.write_bytes(model.read_bytes() + b'altered')
        with patch.object(cpu, 'score_candidate', side_effect=AssertionError('must not score')):
            with self.assertRaises(HarmError):
                self.api.load_research_artifact(self.output)
        self.assertEqual(self.selected['target_cpu'].candidate.directory.joinpath('model.joblib').stat().st_size,
                         model.stat().st_size - 7)

    def test_changed_code_or_lock_binding_blocks_checks_before_deserialization(self):
        self.export()
        original = self.api.execution_identity()
        for name in ('sentinel/context_harm/selection.py',
                     'requirements-ml-win-py311.lock.txt',
                     'requirements-harm-neural-win-py311.lock.txt'):
            changed = {**original, 'files': {**original['files'], name: 'f' * 64}}
            with self.subTest(name=name), patch.object(self.api, 'execution_identity', return_value=changed):
                with self.assertRaises(HarmError):
                    self.api.load_research_artifact(self.output)

    def test_unsupported_manifest_schema_or_member_path_is_rejected(self):
        self.export()
        manifest = read_json(self.output / 'manifest.json')
        for bad in ({**manifest, 'schema_version': 2},
                    {**manifest, 'members': {'../outside.joblib': 'a' * 64}}):
            write_json(self.output / 'manifest.json', bad)
            (self.output / 'manifest.sha256').write_text(sha256(self.output / 'manifest.json') + '\n',
                                                        encoding='ascii')
            with self.assertRaises(HarmError):
                self.api.inspect_artifact(self.output, research=True)

    def test_missing_branch_invalid_calibrator_and_foreign_study_cannot_export(self):
        bad = {'target_cpu': self.selected['target_cpu']}
        with self.assertRaises(HarmError):
            self.api.export_artifact(bad, self.calibrators, self.study, self.output)
        calibrators = {**self.calibrators, 'target_cpu': CalibrationRecord('available', -1.0, 0.0, {})}
        with self.assertRaises(HarmError):
            self.api.export_artifact(self.selected, calibrators, self.study, self.output)
        ref = self.selected['target_cpu'].candidate
        record = {**ref.fit_record, 'study_manifest_sha256': 'f' * 64}
        write_json(ref.directory / 'fit-record.json', record)
        choices = {**self.selected, 'target_cpu': replace(self.selected['target_cpu'],
                   candidate=replace(ref, fit_record=record))}
        with self.assertRaises(HarmError):
            self.api.export_artifact(choices, self.calibrators, self.study, self.output)
        self.assertFalse(self.output.exists())

    def test_failed_manifest_checksum_write_does_not_publish_a_partial_bundle(self):
        original = Path.write_text
        def write(path, *args, **kwargs):
            if path.name == 'manifest.sha256':
                raise OSError('synthetic checksum publication failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', write), self.assertRaises((OSError, HarmError)):
            self.export()
        self.assertFalse(self.output.exists(), 'An interrupted artifact must stay private in its stage')
    def test_packing_is_forbidden_after_final_access(self):
        write_json(self.study.path.parent / 'final-access.json', {'status': 'reserved'})
        with self.assertRaises(HarmError):
            self.export()
        self.assertFalse(self.output.exists())

    def test_artifact_metadata_contains_no_case_ids_or_training_text(self):
        metadata = self.export()
        serialized = repr(metadata)
        self.assertNotIn('train-0', serialized)
        self.assertNotIn('ordinary invented discussion', serialized)
        self.assertNotIn('you are stupid', serialized)
        self.assertNotIn('scores', metadata)

    def test_offline_prediction_uses_ordered_context_and_suppresses_unsupported_probability(self):
        self.export()
        from sentinel.context_harm.conversation import parse_submission
        request = parse_submission({'conversation_kind': 'linear', 'conversation_turns': [
            {'turn_id': 'earlier', 'speaker_id': None, 'text': 'A preceding observation.'},
            {'turn_id': 'target', 'speaker_id': None, 'text': 'you are stupid'},
            {'turn_id': 'future', 'speaker_id': None, 'text': 'Later material excluded.'},
        ], 'target_turn_id': 'target', 'language': 'en'})
        result = self.api.predict_research(self.output, request)
        self.assertEqual(result['branch'], 'context_cpu')
        self.assertEqual(result['category'], 'review')
        self.assertEqual(result['target_id'], 'target')
        self.assertTrue(result['research_only'])
        self.assertNotIn('calibrated_probability', result)
        self.assertEqual(result['coverage']['later_turns_excluded'], 1)



class NeuralBundleTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module('sentinel.context_harm.artifacts')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        from context_harm_neural_fixtures import ControlledWorkers, fixture_sources, ready_study
        from sentinel.context_harm import neural
        from sentinel.context_harm.source import default_settings
        self.neural = neural
        self.study = ready_study(self.root)
        sources = fixture_sources(self.root)
        workers = ControlledWorkers(neural, self.study, sources)
        with patch('sentinel.context_harm.neural_sources.verify_sources', side_effect=lambda value: value), \
             patch.object(neural, 'run_worker', side_effect=workers):
            import sys
            pilot = neural.run_neural_pilot(self.study, Path(sys.executable), sources, self.root / 'pilot.json')
            candidates = neural.fit_neural_candidates(self.study, pilot, Path(sys.executable),
                                                       self.root / 'neural-candidates', default_settings())
        self.selected, self.calibrators = make_selections(self.root / 'cpu-fitted', self.study)
        for ref in candidates:
            if ref.kind in self.selected:
                continue
            self.selected[ref.kind] = Selection(ref, 0.5, {'status': 'usable', 'rows': 90,
                                                        'recall': 1.0, 'precision': 1.0, 'fpr': 0.0})
            self.calibrators[ref.kind] = CalibrationRecord('unavailable', None, None,
                                                          {'reason': 'controlled_software_fixture'})
        self.output = self.root / 'bundle'

    def test_neural_bundle_records_actual_configuration_checkpoint_and_gpu_aggregates(self):
        metadata = self.api.export_artifact(self.selected, self.calibrators, self.study, self.output)
        self.assertEqual(metadata, self.api.inspect_artifact(self.output, research=True))
        branch = metadata['branches']['target_neural']
        self.assertIsInstance(branch['params'], dict, 'Neural selected parameters must be explicit')
        self.assertEqual(branch['params']['learning_rate'], 2e-5)
        self.assertEqual(branch['params']['selected_epoch'], 1)
        self.assertEqual(branch['fit_resources']['gpu_allocated_peak_bytes'], 1024 ** 3)
        self.assertEqual(branch['fit_resources']['gpu_reserved_peak_bytes'], 2 * 1024 ** 3)
        self.assertTrue(metadata['synthetic'])

    def test_changed_copied_tokenizer_is_rejected_before_any_neural_worker(self):
        self.api.export_artifact(self.selected, self.calibrators, self.study, self.output)
        path = self.output / 'branches/context_neural/tokenizer.json'
        path.write_bytes(path.read_bytes() + b'changed')
        with patch.object(self.neural, 'run_worker', side_effect=AssertionError('must not load neural model')):
            with self.assertRaises(HarmError):
                self.api.inspect_artifact(self.output, research=True)

if __name__ == '__main__':
    unittest.main()


