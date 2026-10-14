"""One reserved research scoring operation with paired aggregate comparisons."""
import math
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from sentinel.analysis import ABUSE_RE
from sentinel.url_ml.metrics import bootstrap_weights, point_metrics

from .access import (BOOTSTRAP, begin_final_access, final_scoring_lock,
                     finish_final_access, load_final_diagnostics, load_final_test)
from .artifacts import load_research_artifact
from .contracts import HarmError, ScoreBatch
from .cpu import score_candidate
from .integrity import canonical_sha256, publish_stage, read_json, safe_path, sha256, write_json
from .protocol import verify_study
from .selection import _probability_diagnostics, apply_calibration


METRICS = ('precision', 'recall', 'f1', 'macro_f1', 'pr_auc', 'fpr', 'brier', 'ece')
CPU_KINDS = ('target_cpu', 'context_cpu')
NEURAL_KINDS = ('target_neural', 'context_neural')


TOKEN_COVERAGE_FIELDS = (
    'total_cases', 'measured_token_cases', 'supported_cases', 'target_tokens_available', 'target_tokens_used',
    'context_tokens_available', 'context_tokens_used', 'context_truncated_cases',
    'target_limit_abstentions', 'context_turns_available', 'context_turns_used',
    'context_turns_omitted',
)


def _token_coverage(batch):
    values = batch.runtime.get('token_coverage', {})
    if not isinstance(values, dict):
        return {}
    return {key: values[key] for key in TOKEN_COVERAGE_FIELDS
            if key in values and type(values[key]) is int and values[key] >= 0}


def _window_coverage(rows):
    available, omitted, unknown = 0, 0, 0
    for row in rows:
        coverage = row.metadata.get('coverage', {})
        value = coverage.get('available_context_turns')
        if type(value) is int and value >= 0:
            available += value
        else:
            unknown += 1
        value = coverage.get('omitted_context_turns')
        if type(value) is int and value >= 0:
            omitted += value
    return {'cases': len(rows), 'used_turns': sum(len(row.model_input.context) for row in rows),
            'reported_available_turns': available, 'reported_omitted_turns': omitted,
            'unknown_available_turn_cases': unknown}

def _checked_batch(batch, ids):
    if (not isinstance(batch, ScoreBatch) or batch.case_ids != ids
            or len(batch.scores) != len(ids) or len(batch.coverage) != len(ids)
            or any(type(flag) is not bool for flag in batch.coverage)):
        raise HarmError('final_comparison_case_ids_or_shape_mismatch')
    for value, covered in zip(batch.scores, batch.coverage):
        if covered:
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise HarmError('final_scores_invalid')
        elif value is not None:
            raise HarmError('final_unsupported_score_invalid')


def _points(labels, scores, threshold, probabilities=None, weights=None):
    point = point_metrics(labels, scores, threshold, weights=weights)
    if probabilities is not None:
        if weights is None:
            diagnostics = _probability_diagnostics(np.asarray(labels), np.asarray(probabilities))
        else:
            indices = np.repeat(np.arange(len(labels)), np.asarray(weights, dtype=int))
            diagnostics = _probability_diagnostics(np.asarray(labels)[indices],
                                                   np.asarray(probabilities)[indices])
        point.update(brier=diagnostics['brier'], ece=diagnostics['ece'],
                     reliability_bins=diagnostics['reliability_bins'])
    return point


def _resources(batch, rows):
    runtime = batch.runtime
    records = runtime.get('records', []) if isinstance(runtime, dict) else []
    def peak(name, alias=None):
        values = [record.get(name) for record in records if isinstance(record, dict)]
        values.extend([runtime.get(name)] if isinstance(runtime, dict) else [])
        if alias is not None:
            values.extend(record.get(alias) for record in records if isinstance(record, dict))
            values.extend([runtime.get(alias)] if isinstance(runtime, dict) else [])
        values = [value for value in values if type(value) in (int, float) and math.isfinite(value)]
        return max(values) if values else None
    elapsed = runtime.get('wall_seconds') if isinstance(runtime, dict) else None
    return {
        'rss_peak_bytes': peak('rss_peak_bytes'),
        'gpu_allocated_peak_bytes': peak('gpu_allocated_peak_bytes', 'peak_allocated_bytes'),
        'gpu_reserved_peak_bytes': peak('gpu_reserved_peak_bytes', 'peak_reserved_bytes'),
        'latency_ms_per_case': elapsed * 1000 / rows
            if type(elapsed) in (int, float) and math.isfinite(elapsed) and rows else None,
    }


def _paired_report(rows, selections, batches, calibrators, components):
    ids = tuple(row.case_id for row in rows)
    labels = np.asarray([row.label for row in rows])
    if not rows or len(set(ids)) != len(ids) or not np.isin(labels, [0, 1]).all():
        raise HarmError('final_rows_invalid')
    if any(case_id not in components for case_id in ids):
        raise HarmError('final_components_missing')
    groups = tuple(components[case_id] for case_id in ids)
    if any(not isinstance(group, str) or not group for group in groups):
        raise HarmError('final_components_invalid')
    kinds = tuple(sorted(selections))
    raw, probabilities, points = {}, {}, {}
    for kind in kinds:
        if kind not in batches or kind not in calibrators:
            raise HarmError('final_branch_missing')
        _checked_batch(batches[kind], ids)
        if not all(batches[kind].coverage):
            raise HarmError('primary_final_coverage_incomplete')
        raw[kind] = np.asarray(batches[kind].scores, dtype=float)
        mapped = apply_calibration(calibrators[kind], tuple(raw[kind]))
        probabilities[kind] = None if mapped is None else np.asarray(mapped)
        points[kind] = _points(labels, raw[kind], selections[kind].raw_threshold,
                               probabilities[kind])
    counts = Counter(groups)
    reasons = []
    class_components = {str(label): len({group for group, actual in zip(groups, labels)
                                         if actual == label}) for label in (0, 1)}
    if min(class_components.values()) < 10:
        reasons.append('insufficient_class_component_support')
    largest_fraction = max(counts.values()) / len(rows)
    if largest_fraction > 0.5:
        reasons.append('dominant_component')
    pairs = [('context_cpu', 'target_cpu', 'context_minus_target')]
    if set(NEURAL_KINDS) <= set(kinds):
        pairs.extend([
            ('context_neural', 'target_neural', 'neural_context_minus_target'),
            ('target_neural', 'target_cpu', 'neural_minus_cpu_target'),
            ('context_neural', 'context_cpu', 'neural_minus_cpu_context'),
        ])
    distributions = {kind: {metric: [] for metric in METRICS} for kind in kinds}
    deltas = {name: {metric: [] for metric in METRICS} for _, _, name in pairs}
    if not reasons:
        for weights in bootstrap_weights(groups, replicates=BOOTSTRAP['replicates'], seed=BOOTSTRAP['seed']):
            sample = {kind: _points(labels, raw[kind], selections[kind].raw_threshold,
                                    probabilities[kind], weights) for kind in kinds}
            for kind in kinds:
                for metric in METRICS:
                    if sample[kind][metric] is not None:
                        distributions[kind][metric].append(sample[kind][metric])
            for context, target, name in pairs:
                for metric in METRICS:
                    if sample[context][metric] is not None and sample[target][metric] is not None:
                        deltas[name][metric].append(sample[context][metric] - sample[target][metric])
    def interval(values):
        return np.percentile(values, [2.5, 97.5]).tolist() if len(values) >= 500 else None
    branches = {}
    for kind in kinds:
        branches[kind] = {
            **points[kind], 'rows': len(rows), 'components': len(counts),
            'config_id': selections[kind].candidate.config_id,
            'raw_threshold': selections[kind].raw_threshold,
            'calibration_status': calibrators[kind].status,
            'uncalibrated_probability_diagnostics': _probability_diagnostics(labels, raw[kind]),
            'coverage': 1.0, 'abstentions': 0,
            'intervals': {metric: interval(distributions[kind][metric]) for metric in METRICS},
            'resources': _resources(batches[kind], len(rows)),
        }
    paired = {}
    for context, target, name in pairs:
        paired[name] = {}
        for metric in METRICS:
            paired[name][metric + '_delta'] = (
                points[context][metric] - points[target][metric]
                if points[context][metric] is not None and points[target][metric] is not None else None)
            paired[name][metric + '_interval'] = interval(deltas[name][metric])
    return {
        'rows': len(rows), 'branches': branches, 'paired_deltas': paired,
        'comparison_case_hashes': {kind: canonical_sha256(ids) for kind in kinds},
        'interval_status': 'unavailable' if reasons else 'available',
        'bootstrap': {**BOOTSTRAP, 'unavailable_reasons': reasons,
                      'class_components': class_components,
                      'largest_component_fraction': largest_fraction,
                      'status': 'unavailable' if reasons else 'complete'},
    }


def _breakdowns(rows, selections, batches):
    categories = defaultdict(list)
    community_names = sorted({str(row.metadata.get('community', 'unknown')) for row in rows})
    communities = {value: f'community_{index + 1}' for index, value in enumerate(community_names)}
    for index, row in enumerate(rows):
        labels = set(row.metadata.get('labels', ()))
        if labels == {'CounterSpeech'}:
            categories['counter_speech_only'].append(index)
        if labels == {'Slur'}:
            categories['non_hateful_slur_only'].append(index)
        if labels == {'Slur', 'CounterSpeech'}:
            categories['counter_speech_and_non_hateful_slur'].append(index)
        categories['author_known' if row.metadata.get('author_id') is not None else 'unknown_author'].append(index)
        community = communities[str(row.metadata.get('community', 'unknown'))]
        categories['community:' + community].append(index)
        split = row.metadata.get('split', 'unknown')
        categories['source_split:' + (split if split in ('train', 'dev', 'test') else 'unknown')].append(index)
        for tag in row.metadata.get('context_tags', ()):
            if isinstance(tag, str):
                categories['gold_context_tag:' + tag].append(index)
        coverage = row.metadata.get('coverage', {})
        for name in ('available_context_turns', 'used_context_turns'):
            value = coverage.get(name, 0)
            if type(value) is int and value >= 0:
                categories[name + ':' + str(value)].append(index)
    output = {}
    for name, indices in sorted(categories.items()):
        entry = {'rows': len(indices), 'class_counts': {
            str(label): sum(rows[index].label == label for index in indices) for label in (0, 1)},
                 'branches': {}}
        for kind in CPU_KINDS:
            metric = _points([rows[index].label for index in indices],
                             [batches[kind].scores[index] for index in indices],
                             selections[kind].raw_threshold)
            entry['branches'][kind] = {key: metric[key] for key in
                                       ('confusion', 'precision', 'recall', 'fpr', 'f1')}
        output[name] = entry
    return output


def _rule_baseline(rows):
    labels = [row.label for row in rows]
    target = [float(bool(ABUSE_RE.search(row.model_input.target))) for row in rows]
    context = [float(bool(ABUSE_RE.search('\n'.join((*row.model_input.context,
                                                   row.model_input.target))))) for row in rows]
    return {'method': 'existing_fixed_ABUSE_RE', 'raw_threshold': 0.5,
            'target': _points(labels, target, 0.5), 'context': _points(labels, context, 0.5)}


def evaluate_scores(rows, selections, batches, calibrators, components) -> dict:
    """Pure aggregation used only after the caller has obtained authorized scores."""
    if not set(CPU_KINDS) <= set(selections):
        raise HarmError('final_cpu_pair_missing')
    cpu = _paired_report(rows, {kind: selections[kind] for kind in CPU_KINDS},
                         batches, calibrators, components)
    report = {
        'final_cases': len(rows), 'branches': cpu['branches'],
        'paired_deltas': cpu['paired_deltas'], 'bootstrap': cpu['bootstrap'],
        'interval_status': cpu['interval_status'],
        'comparison_case_hashes': {'target': cpu['comparison_case_hashes']['target_cpu'],
                                   'context': cpu['comparison_case_hashes']['context_cpu']},
        'breakdowns': _breakdowns(rows, selections, batches),
        'context_window_coverage': _window_coverage(rows),
        'rule_baseline': _rule_baseline(rows),
        'neural_comparison': {'status': 'unavailable', 'reason': 'not_selected_before_final_access'},
    }
    if set(NEURAL_KINDS) <= set(selections):
        ids = tuple(row.case_id for row in rows)
        for kind in NEURAL_KINDS:
            _checked_batch(batches[kind], ids)
        coverage = batches['target_neural'].coverage
        if any(batches[kind].runtime.get('status') == 'unavailable' for kind in NEURAL_KINDS):
            report['neural_comparison'] = {'status': 'unavailable', 'reason': 'neural_scoring_unavailable'}
        elif coverage != batches['context_neural'].coverage:
            report['neural_comparison'] = {'status': 'unavailable', 'reason': 'neural_coverage_mismatch'}
        else:
            indices = tuple(index for index, supported in enumerate(coverage) if supported)
            if not indices:
                report['neural_comparison'] = {'status': 'unavailable', 'reason': 'no_neural_compatible_cases'}
            else:
                compatible = tuple(rows[index] for index in indices)
                subset_ids = tuple(row.case_id for row in compatible)
                subset = {kind: ScoreBatch(subset_ids, tuple(batches[kind].scores[index] for index in indices),
                           (True,) * len(indices), batches[kind].runtime) for kind in selections}
                report['neural_comparison'] = {
                    'status': 'complete', **_paired_report(compatible, selections, subset, calibrators, components),
                    'coverage': len(indices) / len(rows), 'abstentions': len(rows) - len(indices),
                }
        report['neural_comparison']['token_coverage'] = {
            kind: _token_coverage(batches[kind]) for kind in NEURAL_KINDS}
        report['neural_comparison']['resources'] = {
            kind: _resources(batches[kind], len(rows)) for kind in NEURAL_KINDS}
    return report


def _identity(study, bundle, artifact, output):
    metadata = bundle['metadata']
    binding = verify_study(study)
    if metadata['protocol_manifest_sha256'] != canonical_sha256(study.manifest):
        raise HarmError('final_artifact_study_mismatch')
    # Attest before reserving or reopening protected final data. Repeating an
    # interrupted evaluation must use the originally recorded runtime as well.
    from .neural import attest_current_runtime
    neural_runtime = {}
    for kind, selection in sorted(bundle['selections'].items()):
        if kind in NEURAL_KINDS:
            record = selection.candidate.fit_record
            neural_runtime[kind] = attest_current_runtime(record['neural_python'], record['runtime_probe'])
    return {
        'artifact_manifest_sha256': sha256(Path(artifact) / 'manifest.json'),
        'implementation': metadata['implementation'],
        'selected_settings': {kind: {'config_id': branch['config_id'],
             'raw_threshold': branch['raw_threshold'], 'params': branch['params'],
             'calibration': branch['calibration']} for kind, branch in metadata['branches'].items()},
        'preprocessing': metadata['preprocessing'], 'cohorts': binding['case_hashes'],
        'coverage': {**metadata['coverage'], 'neural_settings': metadata['neural_settings'],
                     'neural_runtime': neural_runtime,
                     'diagnostics': 'declared_protected_missing_context_targets'},
        'tokenizer_base_hashes': {kind: branch['tokenizer_base_hashes']
                                  for kind, branch in metadata['branches'].items() if kind in NEURAL_KINDS},
        'bootstrap': dict(BOOTSTRAP), 'output': str(Path(output).resolve()),
    }


def _score(selection, rows):
    runtime = None
    if selection.candidate.kind in NEURAL_KINDS:
        interpreter = selection.candidate.fit_record.get('neural_python')
        if not interpreter:
            raise HarmError('final_neural_interpreter_unavailable')
        runtime = {'python': interpreter}
    return score_candidate(selection.candidate, rows, runtime)


def _diagnostics(rows, selection, calibrator):
    if not rows:
        return {'status': 'unavailable', 'reason': 'no_declared_cases', 'rows': 0}
    batch = _score(selection, rows)
    ids = tuple(row.case_id for row in rows)
    _checked_batch(batch, ids)
    indices = tuple(index for index, supported in enumerate(batch.coverage) if supported)
    if not indices:
        return {'status': 'unavailable', 'reason': 'no_supported_diagnostic_cases',
                'rows': len(rows), 'coverage': 0.0}
    values = tuple(batch.scores[index] for index in indices)
    probabilities = apply_calibration(calibrator, values)
    return {'status': 'complete', 'rows': len(rows), 'supported_rows': len(indices),
            'coverage': len(indices) / len(rows),
            'target_only': _points([rows[index].label for index in indices], values,
                                    selection.raw_threshold, probabilities),
            'resources': _resources(batch, len(rows))}


def _existing_report(output, identity_hash):
    manifest = read_json(output / 'manifest.json')
    if manifest.get('schema_version') != 1 or set(manifest.get('members', {})) != {
            'evaluation.json', 'model_card.md'}:
        raise HarmError('final_publication_invalid')
    for name, digest in manifest['members'].items():
        if sha256(safe_path(output, name)) != digest:
            raise HarmError('final_publication_changed')
    report = read_json(output / 'evaluation.json', max_bytes=16 * 1024 * 1024)
    if report.get('final_identity_sha256') != identity_hash or report.get('status') != 'complete':
        raise HarmError('final_publication_identity_mismatch')
    return report


def evaluate_final(study, artifact: Path, output: Path) -> dict:
    output = Path(output).resolve()
    with final_scoring_lock(study):
        bundle = load_research_artifact(artifact)
        identity = _identity(study, bundle, artifact, output)
        receipt = begin_final_access(study, identity)
        if output.exists():
            report = _existing_report(output, receipt['identity_sha256'])
            finish_final_access(study, receipt, sha256(output / 'evaluation.json'))
            return report
        rows = load_final_test(study, receipt)
        diagnostic_rows = load_final_diagnostics(study, receipt)
        components = read_json(Path(study.path) / 'components.json', max_bytes=16 * 1024 * 1024)['test']
        selections, calibrators = bundle['selections'], bundle['calibrators']
        batches = {kind: _score(selection, rows) for kind, selection in selections.items()}
        report = evaluate_scores(rows, selections, batches, calibrators, components)
        report.update({
            'schema_version': 1, 'task_id': 'english_directed_abuse', 'status': 'complete',
            'study_status': 'research_only', 'synthetic': bundle['metadata']['synthetic'],
            'artifact_manifest_sha256': identity['artifact_manifest_sha256'],
            'protocol_manifest_sha256': canonical_sha256(study.manifest),
            'cohort_audit': verify_study(study).get('audit', {}),
            'final_identity_sha256': receipt['identity_sha256'],
            'diagnostics': {'target_only_missing_context': _diagnostics(
                diagnostic_rows, selections['target_cpu'], calibrators['target_cpu'])},
            'calibration_note': 'Final diagnostics are reporting only; frozen decisions and calibrators are unchanged.',
        })
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.harm-evaluation-stage-', dir=output.parent))
        try:
            write_json(stage / 'evaluation.json', report, exclusive=True)
            (stage / 'model_card.md').write_text(
                '# Sentinel English directed-abuse research evaluation\n\n'
                f'Cases: {report["final_cases"]}. Synthetic: {str(report["synthetic"]).lower()}. '
                f'Interval status: {report["interval_status"]}.\n\n'
                'These are aggregate results from one reserved research operation. Synthetic results '
                'verify software only. A measured context gain is not required or assumed. '
                'Initial bundles remain research-only, and human challenge/live release remain pending.\n\n'
                'Historical Reddit labels, generic encoder pretraining, available ancestry, '
                'window/token omissions, class/component support and resource limits constrain interpretation. '
                'Content labels do not establish intent, repeated harassment, or contemporary cross-platform accuracy.\n',
                encoding='utf-8')
            publish_stage(stage, output, {path.name: sha256(path) for path in stage.iterdir()})
            finish_final_access(study, receipt, sha256(output / 'evaluation.json'))
            return report
        finally:
            if stage.exists() and stage.resolve().parent == output.parent:
                shutil.rmtree(stage)




