"""One reserved final operation on explicitly synthetic cases only."""
import importlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_context_harm_access import make_study
from test_context_harm_artifacts import make_selections
from sentinel.context_harm.contracts import CandidateRef, HarmCase, HarmError, ModelText, ScoreBatch, Selection
from sentinel.context_harm.integrity import read_json, write_json


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module('sentinel.context_harm.evaluation')
        except ModuleNotFoundError as error:
            if error.name == 'sentinel.context_harm.evaluation':
                self.fail('Reserved aggregate harm evaluation is missing')
            raise
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def bundle(self, *, test=None, diagnostics=()):
        from sentinel.context_harm.artifacts import export_artifact
        study = make_study(self.root / 'study', test=test, diagnostics=diagnostics)
        choices, calibrators = make_selections(self.root / 'fitted', study)
        artifact = self.root / 'artifact'
        export_artifact(choices, calibrators, study, artifact)
        return study, artifact, choices, calibrators

    def test_durable_reservation_precedes_loading_and_public_output_has_no_raw_cases(self):
        study, artifact, _, _ = self.bundle()
        output = self.root / 'public'
        original = self.api.load_final_test
        observed = []
        def load(study, receipt):
            observed.append(read_json(study.path.parent / 'final-access.json') == receipt)
            return original(study, receipt)
        with patch.object(self.api, 'load_final_test', side_effect=load):
            report = self.api.evaluate_final(study, artifact, output)
        self.assertEqual(observed, [True])
        self.assertEqual(report['bootstrap']['replicates'], 1000)
        self.assertEqual(report['bootstrap']['seed'], 42)
        self.assertEqual(report['comparison_case_hashes']['target'],
                         report['comparison_case_hashes']['context'])
        self.assertEqual(report['interval_status'], 'available')
        self.assertEqual(report['branches']['target_cpu']['recall'], 1.0)
        self.assertEqual(read_json(study.path.parent / 'final-access.json')['status'], 'complete')
        public = (output / 'evaluation.json').read_text(encoding='utf-8')
        for value in ('test-0', 'ordinary invented discussion', 'you are stupid', 'author_id'):
            self.assertNotIn(value, public)
        self.assertTrue(report['synthetic'])
        self.assertIn('cohort_audit', report)
        self.assertIn('context_window_coverage', report)

    def test_completed_evaluation_is_refused_before_any_worker_runs(self):
        study, artifact, _, _ = self.bundle()
        output = self.root / 'public'
        self.api.evaluate_final(study, artifact, output)
        with patch.object(self.api, 'score_candidate', side_effect=AssertionError('must not score')):
            with self.assertRaises(HarmError):
                self.api.evaluate_final(study, artifact, output)
        self.assertEqual(read_json(study.path.parent / 'final-access.json')['status'], 'complete')

    def test_dominant_component_retains_points_and_marks_intervals_unavailable(self):
        rows = tuple(HarmCase(f'item-{index}', ModelText('plain' if index % 2 == 0 else 'abuse',
                         ('earlier',)), (), 'one-thread', index % 2, {}) for index in range(24))
        refs = {kind: Selection(CandidateRef(kind, kind, Path('synthetic'), {}), 0.5, {})
                for kind in ('target_cpu', 'context_cpu')}
        values = tuple(0.1 if row.label == 0 else 0.9 for row in rows)
        scored = {kind: ScoreBatch(tuple(row.case_id for row in rows), values,
                                  (True,) * len(rows), {}) for kind in refs}
        components = {row.case_id: 'one-component' for row in rows}
        from sentinel.context_harm.contracts import CalibrationRecord
        calibrators = {kind: CalibrationRecord('unavailable', None, None, {}) for kind in refs}
        report = self.api.evaluate_scores(rows, refs, scored, calibrators, components)
        self.assertEqual(report['interval_status'], 'unavailable')
        self.assertIn('dominant_component', report['bootstrap']['unavailable_reasons'])
        self.assertEqual(report['branches']['target_cpu']['recall'], 1.0)
        self.assertIsNone(report['paired_deltas']['context_minus_target']['recall_interval'])

    def test_paired_deltas_share_resampling_and_are_exactly_zero_for_identical_scores(self):
        study = make_study(self.root / 'study')
        from sentinel.context_harm.protocol import read_cases
        rows = read_cases(study.path / 'test.jsonl')
        refs = {kind: Selection(CandidateRef(kind, kind, Path('synthetic'), {}), 0.5, {})
                for kind in ('target_cpu', 'context_cpu')}
        values = tuple(0.1 if row.label == 0 else 0.9 for row in rows)
        scored = {kind: ScoreBatch(tuple(row.case_id for row in rows), values,
                                  (True,) * len(rows), {}) for kind in refs}
        from sentinel.context_harm.contracts import CalibrationRecord
        calibrators = {kind: CalibrationRecord('unavailable', None, None, {}) for kind in refs}
        components = read_json(study.path / 'components.json')['test']
        report = self.api.evaluate_scores(rows, refs, scored, calibrators, components)
        delta = report['paired_deltas']['context_minus_target']
        self.assertEqual(delta['recall_delta'], 0.0)
        self.assertEqual(delta['recall_interval'], [0.0, 0.0])
        self.assertEqual(delta['fpr_interval'], [0.0, 0.0])

    def test_mismatched_ids_or_unsupported_primary_scores_cannot_be_evaluated(self):
        study = make_study(self.root / 'study')
        from sentinel.context_harm.protocol import read_cases
        rows = read_cases(study.path / 'test.jsonl')
        refs = {kind: Selection(CandidateRef(kind, kind, Path('synthetic'), {}), 0.5, {})
                for kind in ('target_cpu', 'context_cpu')}
        base = ScoreBatch(tuple(row.case_id for row in rows), (0.5,) * len(rows),
                          (True,) * len(rows), {})
        from sentinel.context_harm.contracts import CalibrationRecord
        calibrators = {kind: CalibrationRecord('unavailable', None, None, {}) for kind in refs}
        components = read_json(study.path / 'components.json')['test']
        for bad in (replace(base, case_ids=tuple(reversed(base.case_ids))),
                    replace(base, coverage=(False,) + base.coverage[1:],
                            scores=(None,) + base.scores[1:])):
            with self.subTest(batch=bad), self.assertRaises(HarmError):
                self.api.evaluate_scores(rows, refs, {'target_cpu': base, 'context_cpu': bad},
                                         calibrators, components)

    def test_rule_baseline_uses_same_raw_window_and_diagnostics_are_separate(self):
        target = HarmCase('quoted', ModelText('I reject "you are stupid".',
                       ('ordinary preceding context',)), (), 'thread-a', 0,
                       {'labels': ['CounterSpeech'], 'author_id': None})
        positive = HarmCase('positive', ModelText('you are stupid', ('ordinary context',)), (),
                            'thread-b', 1, {'labels': ['PersonDirectedAbuse'], 'author_id': None})
        diagnostic = HarmCase('no-context', ModelText('you are stupid'), (), 'thread-c', 1, {})
        study, artifact, _, _ = self.bundle(test=(target, positive), diagnostics=(diagnostic,))
        report = self.api.evaluate_final(study, artifact, self.root / 'public')
        self.assertEqual(report['rule_baseline']['target']['confusion']['fp'], 1)
        self.assertEqual(report['rule_baseline']['raw_threshold'], 0.5)
        self.assertEqual(report['diagnostics']['target_only_missing_context']['rows'], 1)
        self.assertEqual(report['final_cases'], 2)
        self.assertEqual(report['breakdowns']['counter_speech_only']['rows'], 1)

    def test_interruption_after_publication_resumes_without_scoring_again(self):
        study, artifact, _, _ = self.bundle()
        output = self.root / 'public'
        with patch.object(self.api, 'finish_final_access', side_effect=RuntimeError('synthetic interruption')):
            with self.assertRaises(RuntimeError):
                self.api.evaluate_final(study, artifact, output)
        self.assertEqual(read_json(study.path.parent / 'final-access.json')['status'], 'reserved')
        with patch.object(self.api, 'score_candidate', side_effect=AssertionError('must not score')):
            report = self.api.evaluate_final(study, artifact, output)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(read_json(study.path.parent / 'final-access.json')['status'], 'complete')

    def test_neural_comparison_uses_identical_compatible_subset_without_retuning_cpu(self):
        study = make_study(self.root / 'study')
        from sentinel.context_harm.protocol import read_cases
        from sentinel.context_harm.contracts import CalibrationRecord
        rows = read_cases(study.path / 'test.jsonl')
        kinds = ('target_cpu', 'context_cpu', 'target_neural', 'context_neural')
        refs = {kind: Selection(CandidateRef(kind, kind, Path('synthetic'), {}),
                                0.8 if kind.endswith('cpu') else 0.5, {}) for kind in kinds}
        ids = tuple(row.case_id for row in rows)
        cpu_values = tuple(0.1 if row.label == 0 else 0.7 for row in rows)
        compatible = tuple(index >= 2 for index in range(len(rows)))
        neural_values = tuple((0.1 if row.label == 0 else 0.9) if compatible[index] else None
                              for index, row in enumerate(rows))
        batches = {kind: ScoreBatch(ids, cpu_values if kind.endswith('cpu') else neural_values,
                     (True,) * len(rows) if kind.endswith('cpu') else compatible, {} if kind.endswith('cpu') else {
                         'token_coverage': {'total_cases': 24, 'measured_token_cases': 24, 'supported_cases': 22,
                                            'context_truncated_cases': 10,
                                            'target_limit_abstentions': 2,
                                            'case_ids': ['MUST_NOT_LEAK']}}) for kind in kinds}
        calibrators = {kind: CalibrationRecord('unavailable', None, None, {}) for kind in kinds}
        report = self.api.evaluate_scores(rows, refs, batches, calibrators,
                                         read_json(study.path / 'components.json')['test'])
        subset = report['neural_comparison']
        self.assertEqual(subset['rows'], 22)
        self.assertEqual(subset['comparison_case_hashes']['target_cpu'],
                         subset['comparison_case_hashes']['context_neural'])
        self.assertEqual(subset['branches']['target_cpu']['recall'], 0.0)
        self.assertEqual(subset['branches']['target_cpu']['raw_threshold'], 0.8)
        self.assertEqual(subset['branches']['target_neural']['recall'], 1.0)
        self.assertIn('token_coverage', subset)
        self.assertEqual(subset['token_coverage']['context_neural']['measured_token_cases'], 24)
        self.assertEqual(subset['token_coverage']['context_neural']['context_truncated_cases'], 10)
        self.assertEqual(subset['token_coverage']['context_neural']['target_limit_abstentions'], 2)
        self.assertNotIn('MUST_NOT_LEAK', repr(subset))
        failed = dict(batches)
        for kind in ('target_neural', 'context_neural'):
            failed[kind] = ScoreBatch(ids, (None,) * len(rows), (False,) * len(rows),
                                      {'status': 'unavailable', 'reason': 'cuda_unavailable'})
        failed_report = self.api.evaluate_scores(rows, refs, failed, calibrators,
                                                 read_json(study.path / 'components.json')['test'])
        self.assertEqual(failed_report['neural_comparison']['reason'], 'neural_scoring_unavailable')


if __name__ == '__main__':
    unittest.main()



