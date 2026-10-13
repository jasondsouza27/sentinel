"""Synthetic validation/calibration fixtures, never evidence of model quality."""
import importlib
import math
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from sentinel.context_harm.contracts import (
    CalibrationRecord, CandidateRef, HarmError, ScoreBatch, Selection,
)


def candidate(kind='target_cpu', config_id='target_cpu-default'):
    return CandidateRef(kind, config_id, Path('private-synthetic-candidate'),
                        {'status': 'complete', 'provenance': 'synthetic_fixture'})


def batch(values, labels=None, *, prefix='validation', coverage=None):
    ids = tuple(f'{prefix}-{index}' for index in range(len(values)))
    result = ScoreBatch(ids, tuple(values), tuple(coverage or [True] * len(values)), {})
    return result, dict(zip(ids, labels if labels is not None else [0] * len(values)))


def separated_calibration():
    values, labels, groups = [], [], []
    for group in range(12):
        for label in (0, 1):
            for offset in range(3):
                labels.append(label)
                values.append((0.2 + offset * 0.01) if label == 0 else
                              (0.8 - offset * 0.01))
                groups.append(f'component-{group}')
    scores, gold = batch(values, labels, prefix='calibration')
    return scores, gold, dict(zip(scores.case_ids, groups))


class SelectionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module('sentinel.context_harm.selection')
        except ModuleNotFoundError as error:
            if error.name == 'sentinel.context_harm.selection':
                self.fail('Frozen harm selection and grouped calibration are missing')
            raise

    def choose(self, values, labels, *, kind='target_cpu'):
        scores, gold = batch(values, labels)
        ref = candidate(kind)
        return self.api.select_candidates((ref,), {ref.config_id: scores}, gold)[kind]

    def test_threshold_maximizes_recall_inside_five_percent_fpr_budget(self):
        chosen = self.choose([0.95] + [0.1] * 19 + [0.9, 0.8],
                             [0] * 20 + [1, 1])
        self.assertEqual(chosen.raw_threshold, 0.8)
        self.assertEqual(chosen.validation_report['recall'], 1.0)
        self.assertEqual(chosen.validation_report['confusion']['fp'], 1)
        self.assertLessEqual(chosen.validation_report['fpr'], 0.05)
        self.assertEqual(chosen.validation_report['status'], 'usable')

    def test_equal_recall_prefers_precision_before_config_id(self):
        clean, gold = batch([0.1] * 20 + [0.9, 0.05], [0] * 20 + [1, 1])
        noisy = replace(clean, scores=(0.95,) + (0.1,) * 19 + (0.9, 0.05))
        refs = (candidate(config_id='a-noisy'), candidate(config_id='z-clean'))
        chosen = self.api.select_candidates(refs,
                    {'a-noisy': noisy, 'z-clean': clean}, gold)['target_cpu']
        self.assertEqual(chosen.candidate.config_id, 'z-clean')
        self.assertEqual(chosen.validation_report['recall'], 0.5)
        self.assertEqual(chosen.validation_report['precision'], 1.0)
        self.assertEqual(chosen.validation_report['fpr'], 0.0)

    def test_tied_configurations_use_lexical_id_independent_of_input_order(self):
        scores, gold = batch([0.1] * 20 + [0.9], [0] * 20 + [1])
        refs = (candidate(config_id='z-config'), candidate(config_id='a-config'))
        mapping = {ref.config_id: scores for ref in refs}
        for order in (refs, tuple(reversed(refs))):
            with self.subTest(order=tuple(ref.config_id for ref in order)):
                chosen = self.api.select_candidates(order, mapping, gold)['target_cpu']
                self.assertEqual(chosen.candidate.config_id, 'a-config')

    def test_score_ties_cannot_be_split_to_manufacture_admissible_recall(self):
        unusable = self.choose([0.8] * 20 + [0.8] * 4, [0] * 20 + [1] * 4)
        self.assertIsNone(unusable.raw_threshold)
        self.assertEqual(unusable.validation_report['recall'], 0.0)
        self.assertEqual(unusable.validation_report['fpr'], 0.0)
        self.assertEqual(unusable.validation_report['status'], 'unusable')
        self.assertEqual(unusable.validation_report['reason'], 'validation_zero_recall')

    def test_admissible_negative_only_threshold_is_honestly_unusable(self):
        unusable = self.choose([0.95] + [0.9] * 19 + [0.1], [0] * 20 + [1])
        self.assertIsNone(unusable.raw_threshold)
        self.assertEqual(unusable.validation_report['confusion']['fp'], 0)
        self.assertEqual(unusable.validation_report['recall'], 0.0)
        self.assertEqual(unusable.validation_report['status'], 'unusable')

    def test_paired_branches_and_configurations_require_identical_ordered_ids(self):
        scores, gold = batch([0.1] * 20 + [0.9], [0] * 20 + [1])
        for kinds in [('target_cpu', 'context_cpu'),
                      ('target_neural', 'context_neural'),
                      ('target_cpu', 'target_cpu')]:
            refs = tuple(candidate(kind, f'{kind}-{index}')
                         for index, kind in enumerate(kinds))
            other = replace(scores, case_ids=tuple(reversed(scores.case_ids)),
                            scores=tuple(reversed(scores.scores)))
            with self.subTest(kinds=kinds), self.assertRaises(HarmError):
                self.api.select_candidates(refs,
                    {refs[0].config_id: scores, refs[1].config_id: other}, gold)

    def test_cpu_and_neural_families_can_use_different_cohort_sizes(self):
        cpu, cpu_gold = batch([0.1] * 20 + [0.9, 0.8], [0] * 20 + [1, 1])
        neural, neural_gold = batch([0.2] * 20 + [0.8], [0] * 20 + [1],
                                   prefix='neural-validation')
        refs = tuple(candidate(kind, kind) for kind in
                     ('target_cpu', 'context_cpu', 'target_neural', 'context_neural'))
        scores = {ref.config_id: cpu if ref.kind.endswith('cpu') else neural
                  for ref in refs}
        selected = self.api.select_candidates(refs, scores, {**cpu_gold, **neural_gold})
        self.assertEqual(set(selected), {ref.kind for ref in refs})
        self.assertEqual(selected['target_cpu'].validation_report['rows'], 22)
        self.assertEqual(selected['target_neural'].validation_report['rows'], 21)

    def test_primary_selection_rejects_abstentions_invalid_scores_and_labels(self):
        scores, gold = batch([0.1] * 20 + [0.9], [0] * 20 + [1])
        ref = candidate()
        bad_batches = [
            replace(scores, scores=(None,) + scores.scores[1:]),
            replace(scores, coverage=(False,) + scores.coverage[1:]),
            replace(scores, scores=(float('nan'),) + scores.scores[1:]),
            replace(scores, scores=(1.1,) + scores.scores[1:]),
            replace(scores, scores=(-0.1,) + scores.scores[1:]),
            replace(scores, coverage=scores.coverage[:-1]),
            replace(scores, scores=scores.scores[:-1]),
            replace(scores, case_ids=(scores.case_ids[1],) + scores.case_ids[1:]),
        ]
        for bad in bad_batches:
            with self.subTest(batch=bad), self.assertRaises(HarmError):
                self.api.select_candidates((ref,), {ref.config_id: bad}, gold)
        for bad_gold in ({}, dict.fromkeys(scores.case_ids, 0),
                         {**gold, scores.case_ids[0]: 2}):
            with self.subTest(labels=bad_gold), self.assertRaises(HarmError):
                self.api.select_candidates((ref,), {ref.config_id: scores}, bad_gold)

    def test_unknown_kind_duplicate_configuration_and_missing_scores_are_rejected(self):
        scores, gold = batch([0.1] * 20 + [0.9], [0] * 20 + [1])
        ref = candidate()
        for refs, mapping in [
            ((candidate('unknown'),), {'target_cpu-default': scores}),
            ((ref, ref), {ref.config_id: scores}),
            ((ref,), {}),
            ((), {}),
        ]:
            with self.subTest(refs=refs), self.assertRaises(HarmError):
                self.api.select_candidates(refs, mapping, gold)

    def test_validation_report_contains_aggregate_metrics_without_case_vectors(self):
        scores, gold = batch([0.1] * 20 + [0.9], [0] * 20 + [1])
        ref = candidate()
        chosen = self.api.select_candidates((ref,), {ref.config_id: scores}, gold)['target_cpu']
        rendered = repr(chosen.validation_report)
        self.assertNotIn('validation-0', rendered)
        self.assertNotIn('case_ids', chosen.validation_report)
        self.assertNotIn('scores', chosen.validation_report)


if __name__ == '__main__':
    unittest.main()


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module('sentinel.context_harm.selection')
        self.assertTrue(callable(getattr(self.api, 'fit_calibration', None)),
                        'Grouped held-out harm calibration is missing')
        self.assertTrue(callable(getattr(self.api, 'apply_calibration', None)),
                        'Supported calibration application is missing')
        self.selection = Selection(candidate(), 0.8, {'status': 'usable', 'recall': 1.0})

    def fit(self, scores=None, gold=None, groups=None):
        if scores is None:
            scores, gold, groups = separated_calibration()
        return self.api.fit_calibration(self.selection, scores, gold, groups)

    def test_three_grouped_oof_fits_improve_probabilities_without_changing_raw_threshold(self):
        cal = self.fit()
        self.assertEqual(cal.status, 'available')
        self.assertGreater(cal.slope, 0.0)
        mapped = self.api.apply_calibration(cal, (0.2, 0.8))
        self.assertLess(mapped[0], 0.2)
        self.assertGreater(mapped[1], 0.8)
        self.assertEqual(self.selection.raw_threshold, 0.8)
        self.assertEqual(cal.report['raw_threshold'], 0.8)
        self.assertLess(cal.report['out_of_fold']['brier'],
                        cal.report['uncalibrated']['brier'])
        self.assertEqual(len(cal.report['folds']), 3)
        for fold in cal.report['folds']:
            self.assertEqual(fold['held_out_class_counts'], {'0': 12, '1': 12})
            self.assertEqual(fold['fit_class_counts'], {'0': 24, '1': 24})
        self.assertEqual(len(cal.report['out_of_fold']['reliability_bins']), 5)
        self.assertEqual(sum(row['count'] for row in
                             cal.report['out_of_fold']['reliability_bins']), 72)
        self.assertAlmostEqual(cal.report['uncalibrated']['brier'], 0.04416666666666667)
        self.assertEqual(cal.report['seed'], 42)

    def test_small_calibration_partition_suppresses_probability(self):
        scores, gold = batch([0.2] * 29 + [0.8] * 30, [0] * 29 + [1] * 30)
        groups = {case_id: f'component-{index}' for index, case_id in
                  enumerate(scores.case_ids)}
        cal = self.fit(scores, gold, groups)
        self.assertEqual(cal.status, 'unavailable')
        self.assertEqual(cal.report['reason'], 'insufficient_calibration_support')
        self.assertIsNone(self.api.apply_calibration(cal, (0.2, 0.8)))

    def test_whole_component_folds_cannot_cut_one_positive_component_for_support(self):
        scores, gold = batch([0.2] * 60 + [0.8] * 60, [0] * 60 + [1] * 60)
        groups = {case_id: f'negative-component-{index // 5}' if index < 60 else
                  'all-positive-component' for index, case_id in enumerate(scores.case_ids)}
        cal = self.fit(scores, gold, groups)
        self.assertEqual(cal.status, 'unavailable')
        self.assertEqual(cal.report['reason'], 'insufficient_grouped_fold_support')
        self.assertIsNone(cal.slope)
        self.assertIsNone(self.api.apply_calibration(cal, (0.2, 0.8)))

    def test_too_few_components_suppresses_probability(self):
        scores, gold, _ = separated_calibration()
        groups = {case_id: f'component-{index % 2}' for index, case_id in
                  enumerate(scores.case_ids)}
        cal = self.fit(scores, gold, groups)
        self.assertEqual(cal.status, 'unavailable')
        self.assertEqual(cal.report['reason'], 'insufficient_grouped_fold_support')

    def test_tied_clipped_and_effectively_tied_predictors_are_unavailable(self):
        scores, gold, groups = separated_calibration()
        for values in ((0.1,) * 72, (0.0,) * 36 + (1e-8,) * 36,
                       (1.0,) * 36 + (1 - 1e-8,) * 36,
                       (0.1,) * 36 + (0.1 + 1e-12,) * 36):
            with self.subTest(values=values[:2]):
                cal = self.fit(replace(scores, scores=values), gold, groups)
                self.assertEqual(cal.status, 'unavailable')
                self.assertEqual(cal.report['reason'], 'insufficient_score_variation')
                self.assertIsNone(cal.slope)

    def test_reversed_scores_cannot_produce_an_inverted_confidence_mapping(self):
        scores, gold, groups = separated_calibration()
        cal = self.fit(replace(scores, scores=tuple(1 - value for value in scores.scores)),
                       gold, groups)
        self.assertEqual(cal.status, 'unavailable')
        self.assertEqual(cal.report['reason'], 'nonpositive_or_invalid_slope')
        self.assertIsNone(self.api.apply_calibration(cal, (0.2, 0.8)))

    def test_worsened_oof_brier_is_unavailable_before_final_fit(self):
        # The raw probabilities match aggregate frequencies, while whole-group
        # variability makes fitted out-of-fold probabilities less reliable.
        values, labels, group_names = [], [], []
        for group, (score, positives) in enumerate(
                [(0.2, 0), (0.2, 2), (0.2, 4), (0.2, 0), (0.2, 2), (0.2, 4),
                 (0.8, 6), (0.8, 8), (0.8, 10), (0.8, 6), (0.8, 8), (0.8, 10)]):
            values.extend([score] * 10)
            labels.extend([1] * positives + [0] * (10 - positives))
            group_names.extend([f'component-{group:02d}'] * 10)
        scores, gold = batch(values, labels)
        groups = dict(zip(scores.case_ids, group_names))
        from sklearn.linear_model import LogisticRegression
        fits = []

        class ObservedLogisticRegression(LogisticRegression):
            def fit(self, X, y, sample_weight=None):
                fits.append(len(y))
                return super().fit(X, y, sample_weight=sample_weight)

        with patch.object(self.api, 'LogisticRegression', ObservedLogisticRegression):
            cal = self.fit(scores, gold, groups)
        self.assertEqual(cal.status, 'unavailable')
        self.assertEqual(cal.report['reason'], 'out_of_fold_brier_worsened')
        self.assertGreater(cal.report['out_of_fold']['brier'],
                           cal.report['uncalibrated']['brier'])
        self.assertEqual(len(fits), 3)
        self.assertNotIn(120, fits)
        self.assertIsNone(self.api.apply_calibration(cal, (0.2, 0.8)))

    def test_nonfinite_solver_output_is_unavailable(self):
        from sklearn.linear_model import LogisticRegression

        class NonfiniteLogisticRegression(LogisticRegression):
            def fit(self, X, y, sample_weight=None):
                import numpy as np
                super().fit(X, y, sample_weight=sample_weight)
                self.coef_ = np.array([[float('nan')]])
                return self

        with patch.object(self.api, 'LogisticRegression', NonfiniteLogisticRegression):
            cal = self.fit()
        self.assertEqual(cal.status, 'unavailable')
        self.assertEqual(cal.report['reason'], 'nonpositive_or_invalid_slope')
        self.assertIsNone(cal.slope)

    def test_fit_failure_and_nonconvergence_cannot_publish_probability(self):
        from sklearn.exceptions import ConvergenceWarning
        from sklearn.linear_model import LogisticRegression
        import warnings

        class FailedLogisticRegression(LogisticRegression):
            def fit(self, X, y, sample_weight=None):
                raise ValueError('synthetic private failure')

        class UnconvergedLogisticRegression(LogisticRegression):
            def fit(self, X, y, sample_weight=None):
                super().fit(X, y, sample_weight=sample_weight)
                warnings.warn('synthetic private failure', ConvergenceWarning)
                return self

        for model in (FailedLogisticRegression, UnconvergedLogisticRegression):
            with self.subTest(model=model), patch.object(self.api, 'LogisticRegression', model):
                cal = self.fit()
            self.assertEqual(cal.status, 'unavailable')
            self.assertEqual(cal.report['reason'], 'calibration_fit_failed')
            self.assertNotIn('synthetic private failure', repr(cal.report))

    def test_missing_component_or_unsupported_calibration_input_is_unavailable(self):
        scores, gold, groups = separated_calibration()
        invalid = [
            (scores, gold, {}),
            (scores, gold, {**groups, scores.case_ids[0]: ''}),
            (replace(scores, scores=(None,) + scores.scores[1:]), gold, groups),
            (replace(scores, coverage=(False,) + scores.coverage[1:]), gold, groups),
            (scores, {}, groups),
        ]
        for values, labels, components in invalid:
            with self.subTest(values=values):
                cal = self.fit(values, labels, components)
                self.assertEqual(cal.status, 'unavailable')
                self.assertIsNone(self.api.apply_calibration(cal, (0.2, 0.8)))

    def test_available_mapping_clips_endpoints_and_rejects_corrupt_parameters(self):
        cal = CalibrationRecord('available', 2.0, 0.0, {})
        mapped = self.api.apply_calibration(cal, (0.0, 0.5, 1.0))
        self.assertIsInstance(mapped, tuple)
        self.assertGreater(mapped[0], 0.0)
        self.assertEqual(mapped[1], 0.5)
        self.assertLess(mapped[2], 1.0)
        for slope, intercept in [(None, 0), (0, 0), (-1, 0), (math.nan, 0),
                                 (1, None), (1, math.inf)]:
            with self.subTest(slope=slope, intercept=intercept), self.assertRaises(HarmError):
                self.api.apply_calibration(CalibrationRecord('available', slope, intercept, {}),
                                           (0.2, 0.8))
        for values in ((math.nan,), (-0.1,), (1.1,), (None,)):
            with self.subTest(values=values), self.assertRaises(HarmError):
                self.api.apply_calibration(cal, values)

    def test_equal_frequency_ece_preserves_tied_score_order_and_uses_five_bins(self):
        # Tie order matters when a tied block spans equal-frequency boundaries.
        values, labels, group_names = [], [], []
        for group in range(12):
            labels.extend([0, 0, 0, 1, 1, 1])
            values.extend([0.2] * 3 + [0.8] * 3)
            group_names.extend([f'component-{group}'] * 6)
        scores, gold = batch(values, labels)
        cal = self.fit(scores, gold, dict(zip(scores.case_ids, group_names)))
        self.assertEqual(cal.status, 'available')
        bins = cal.report['uncalibrated']['reliability_bins']
        self.assertEqual([row['count'] for row in bins], [15, 15, 14, 14, 14])
        self.assertAlmostEqual(bins[2]['observed_fraction'], 8 / 14)
        self.assertAlmostEqual(bins[2]['mean_probability'], 0.2 + 0.6 * 8 / 14)
        self.assertAlmostEqual(cal.report['uncalibrated']['ece'], 0.16666666666666666)

    def test_calibration_report_is_deterministic_and_has_no_case_or_group_vectors(self):
        scores, gold, groups = separated_calibration()
        first = self.fit(scores, gold, groups)
        second = self.fit(scores, gold, dict(reversed(tuple(groups.items()))))
        self.assertEqual(first, second)
        self.assertNotIn('calibration-0', repr(first.report))
        self.assertNotIn('component-0', repr(first.report))
        self.assertNotIn('case_ids', first.report)
        self.assertNotIn('scores', first.report)


if __name__ == '__main__':
    unittest.main()

