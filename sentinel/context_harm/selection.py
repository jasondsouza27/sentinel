"""Frozen validation selection and held-out score calibration for harm research."""
from collections import defaultdict
import warnings

import numpy as np
from scipy.special import expit
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from sentinel.url_ml.metrics import point_metrics

from .contracts import CalibrationRecord, CandidateRef, HarmError, ScoreBatch, Selection


MAX_VALIDATION_FPR = 0.05
CANDIDATE_FAMILIES = {
    'target_cpu': 'cpu', 'context_cpu': 'cpu',
    'target_neural': 'neural', 'context_neural': 'neural',
}


def _score_arrays(batch: ScoreBatch, labels: dict[str, int]):
    ids = batch.case_ids
    if (not ids or any(not isinstance(case_id, str) or not case_id for case_id in ids)
            or len(set(ids)) != len(ids) or len(batch.scores) != len(ids)
            or len(batch.coverage) != len(ids)):
        raise HarmError('score_batch_invalid')
    if any(not covered for covered in batch.coverage) or any(
            score is None for score in batch.scores):
        raise HarmError('primary_score_coverage_incomplete')
    try:
        y = np.asarray([labels[case_id] for case_id in ids])
        scores = np.asarray(batch.scores, dtype=float)
    except (KeyError, TypeError, ValueError):
        raise HarmError('score_batch_invalid') from None
    if (y.ndim != 1 or scores.shape != y.shape
            or not np.all(np.isin(y, [0, 1]))
            or not np.isfinite(scores).all()
            or np.any((scores < 0) | (scores > 1))):
        raise HarmError('score_batch_invalid')
    return y, scores


def _threshold(y, scores):
    """Compare every whole tied-score block, including an all-negative choice."""
    order = np.argsort(-scores, kind='stable')
    ordered_scores, ordered_y = scores[order], y[order]
    true_positives = np.cumsum(ordered_y == 1)
    false_positives = np.cumsum(ordered_y == 0)
    ends = np.flatnonzero(np.r_[ordered_scores[:-1] != ordered_scores[1:], True])
    positives = int((y == 1).sum())
    negatives = int((y == 0).sum())
    chosen, best_rank = None, (0.0, 0.0, 0.0)
    for end in ends:
        tp, fp = int(true_positives[end]), int(false_positives[end])
        fpr = fp / negatives
        if fpr > MAX_VALIDATION_FPR:
            continue
        rank = (tp / positives, tp / (tp + fp), -fpr)
        if rank > best_rank:
            chosen, best_rank = float(ordered_scores[end]), rank
    return chosen


def _selection_rank(report):
    return (report['recall'], report['precision'] or 0.0, -report['fpr'])


def select_candidates(
    candidates: tuple[CandidateRef, ...],
    scores: dict[str, ScoreBatch],
    labels: dict[str, int],
) -> dict[str, Selection]:
    """Select each kind on validation; score-map keys are unique config IDs."""
    if not candidates:
        raise HarmError('selection_candidates_empty')
    ids_by_family, seen_configs = {}, set()
    by_kind = defaultdict(list)
    for candidate in candidates:
        if candidate.kind not in CANDIDATE_FAMILIES:
            raise HarmError('candidate_kind_invalid')
        if (not isinstance(candidate.config_id, str) or not candidate.config_id
                or candidate.config_id in seen_configs):
            raise HarmError('candidate_configuration_invalid')
        seen_configs.add(candidate.config_id)
        if candidate.config_id not in scores:
            raise HarmError('candidate_scores_missing')
        batch = scores[candidate.config_id]
        y, values = _score_arrays(batch, labels)
        if set(y) != {0, 1}:
            raise HarmError('validation_class_support_invalid')
        family = CANDIDATE_FAMILIES[candidate.kind]
        if family in ids_by_family and batch.case_ids != ids_by_family[family]:
            raise HarmError('validation_case_ids_mismatch')
        ids_by_family[family] = batch.case_ids
        threshold = _threshold(y, values)
        report = point_metrics(y, values, threshold)
        report.update({
            'rows': len(y),
            'class_counts': {str(label): int((y == label).sum()) for label in (0, 1)},
            'max_fpr': MAX_VALIDATION_FPR,
            'raw_threshold': threshold,
            'status': 'usable' if report['recall'] > 0 else 'unusable',
        })
        if report['status'] == 'unusable':
            report['reason'] = 'validation_zero_recall'
        by_kind[candidate.kind].append(Selection(candidate, threshold, report))

    selected = {}
    for kind, alternatives in sorted(by_kind.items()):
        # Sorting first makes config ID the final tie-break, independent of input order.
        alternatives.sort(key=lambda choice: choice.candidate.config_id)
        chosen = max(alternatives, key=lambda choice: _selection_rank(choice.validation_report))
        report = dict(chosen.validation_report)
        report['configurations'] = [
            {'config_id': choice.candidate.config_id, **choice.validation_report}
            for choice in alternatives
        ]
        selected[kind] = Selection(chosen.candidate, chosen.raw_threshold, report)
    return selected


# Fixed protocol settings: these are not a calibration hyperparameter grid.
EPSILON = 1e-6
MIN_LOGIT_SPREAD = 1e-8
CALIBRATION_FOLDS = 3
CALIBRATION_SEED = 42
MIN_CALIBRATION_PER_CLASS = 30
MIN_HELD_OUT_PER_CLASS = 5
MIN_FIT_PER_CLASS = 20


def _clipped_logits(scores):
    clipped = np.clip(scores, EPSILON, 1 - EPSILON)
    return np.log(clipped / (1 - clipped))


def _probability_diagnostics(y, probabilities):
    """Five equal-frequency bins; tied probabilities keep their input order."""
    bins = []
    ece = 0.0
    ordered = np.argsort(probabilities, kind='stable')
    for index, members in enumerate(np.array_split(ordered, 5)):
        count = len(members)
        mean_probability = float(np.mean(probabilities[members])) if count else None
        observed_fraction = float(np.mean(y[members])) if count else None
        bins.append({
            'bin': index, 'count': count,
            'mean_probability': mean_probability,
            'observed_fraction': observed_fraction,
        })
        if count:
            ece += count / len(y) * abs(mean_probability - observed_fraction)
    return {
        'brier': float(np.mean((probabilities - y) ** 2)),
        'ece': float(ece),
        'ece_binning': 'five_equal_frequency_stable_score_order',
        'reliability_bins': bins,
    }


def _unavailable_calibration(report, reason):
    return CalibrationRecord('unavailable', None, None, {**report, 'reason': reason})


def _fit_sigmoid(logits, y):
    if float(np.ptp(logits)) <= MIN_LOGIT_SPREAD:
        return None, 'insufficient_score_variation'
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', ConvergenceWarning)
            model = LogisticRegression(C=1e6, solver='lbfgs', max_iter=1000,
                                       random_state=CALIBRATION_SEED)
            model.fit(logits.reshape(-1, 1), y)
        slope = float(model.coef_[0, 0])
        intercept = float(model.intercept_[0])
    except (ValueError, FloatingPointError, OverflowError, ConvergenceWarning):
        return None, 'calibration_fit_failed'
    if not np.isfinite([slope, intercept]).all() or slope <= 0:
        return None, 'nonpositive_or_invalid_slope'
    return (slope, intercept), None


def fit_calibration(
    selection: Selection,
    scores: ScoreBatch,
    labels: dict[str, int],
    components: dict[str, str],
) -> CalibrationRecord:
    """Check fixed grouped OOF diagnostics, then fit once on all calibration rows."""
    report = {
        'method': 'sigmoid_on_clipped_score_logits',
        'epsilon': EPSILON, 'min_logit_range': MIN_LOGIT_SPREAD,
        'seed': CALIBRATION_SEED, 'fold_count': CALIBRATION_FOLDS,
        'fold_assignment': 'seeded_component_shuffle_equal_component_folds',
        'min_per_class': MIN_CALIBRATION_PER_CLASS,
        'min_held_out_per_class': MIN_HELD_OUT_PER_CLASS,
        'min_fit_per_class': MIN_FIT_PER_CLASS,
        'raw_threshold': selection.raw_threshold,
        'settings': {'C': 1e6, 'solver': 'lbfgs', 'max_iter': 1000,
                     'random_state': CALIBRATION_SEED},
    }
    try:
        y, values = _score_arrays(scores, labels)
    except HarmError:
        return _unavailable_calibration(report, 'calibration_inputs_invalid')
    counts = {str(label): int((y == label).sum()) for label in (0, 1)}
    report.update({'rows': len(y), 'class_counts': counts,
                   'uncalibrated': _probability_diagnostics(y, values)})
    if min(counts.values()) < MIN_CALIBRATION_PER_CLASS:
        return _unavailable_calibration(report, 'insufficient_calibration_support')
    try:
        group_values = tuple(components[case_id] for case_id in scores.case_ids)
    except KeyError:
        return _unavailable_calibration(report, 'calibration_components_invalid')
    if any(not isinstance(group, str) or not group for group in group_values):
        return _unavailable_calibration(report, 'calibration_components_invalid')
    unique_groups = sorted(set(group_values))
    report['components'] = len(unique_groups)
    if len(unique_groups) < CALIBRATION_FOLDS:
        return _unavailable_calibration(report, 'insufficient_grouped_fold_support')
    logits = _clipped_logits(values)
    report['score_logit_range'] = float(np.ptp(logits))
    if report['score_logit_range'] <= MIN_LOGIT_SPREAD:
        return _unavailable_calibration(report, 'insufficient_score_variation')

    # Allocate once and gate every fold before fitting. No retries, stratification
    # searches or cutting a component to manufacture class support.
    rng = np.random.default_rng(CALIBRATION_SEED)
    shuffled_groups = rng.permutation(unique_groups)
    held_out_groups = np.array_split(shuffled_groups, CALIBRATION_FOLDS)
    group_array = np.asarray(group_values)
    folds, descriptions = [], []
    for index, held_groups in enumerate(held_out_groups):
        held_mask = np.isin(group_array, held_groups)
        held, fitting = np.flatnonzero(held_mask), np.flatnonzero(~held_mask)
        held_counts = {str(label): int((y[held] == label).sum()) for label in (0, 1)}
        fit_counts = {str(label): int((y[fitting] == label).sum()) for label in (0, 1)}
        descriptions.append({
            'fold': index, 'held_out_rows': len(held), 'fit_rows': len(fitting),
            'held_out_components': len(held_groups),
            'fit_components': len(unique_groups) - len(held_groups),
            'held_out_class_counts': held_counts, 'fit_class_counts': fit_counts,
        })
        folds.append((fitting, held))
    report['folds'] = descriptions
    if any(min(fold['held_out_class_counts'].values()) < MIN_HELD_OUT_PER_CLASS
           or min(fold['fit_class_counts'].values()) < MIN_FIT_PER_CLASS
           for fold in descriptions):
        return _unavailable_calibration(report, 'insufficient_grouped_fold_support')

    oof = np.empty(len(y), dtype=float)
    for fitting, held in folds:
        parameters, reason = _fit_sigmoid(logits[fitting], y[fitting])
        if reason is not None:
            return _unavailable_calibration(report, reason)
        slope, intercept = parameters
        oof[held] = expit(slope * logits[held] + intercept)
    if not np.isfinite(oof).all():
        return _unavailable_calibration(report, 'calibration_fit_failed')
    report['out_of_fold'] = _probability_diagnostics(y, oof)
    if report['out_of_fold']['brier'] > report['uncalibrated']['brier']:
        return _unavailable_calibration(report, 'out_of_fold_brier_worsened')

    parameters, reason = _fit_sigmoid(logits, y)
    if reason is not None:
        return _unavailable_calibration(report, reason)
    slope, intercept = parameters
    return CalibrationRecord('available', slope, intercept, report)


def apply_calibration(
    calibration: CalibrationRecord,
    scores: tuple[float, ...],
) -> tuple[float, ...] | None:
    """Map probabilities only when the frozen calibrator is supported and valid."""
    if calibration.status != 'available':
        return None
    slope, intercept = calibration.slope, calibration.intercept
    if (slope is None or intercept is None
            or not np.isfinite([slope, intercept]).all() or slope <= 0):
        raise HarmError('invalid_calibration')
    try:
        values = np.asarray(scores, dtype=float)
    except (TypeError, ValueError):
        raise HarmError('calibration_scores_invalid') from None
    if (values.ndim != 1 or not np.isfinite(values).all()
            or np.any((values < 0) | (values > 1))):
        raise HarmError('calibration_scores_invalid')
    probabilities = expit(slope * _clipped_logits(values) + intercept)
    if not np.isfinite(probabilities).all():
        raise HarmError('invalid_calibration')
    return tuple(float(value) for value in probabilities)
