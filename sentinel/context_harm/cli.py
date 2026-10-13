"""Explicit production research stages; failed gates publish unavailable records."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

from .contracts import CalibrationRecord, CandidateRef, FrozenStudy, HarmError, PRODUCTION_CRITERIA, ScoreBatch, Selection
from .integrity import canonical_sha256, read_json, safe_path, sha256, write_json
from .source import default_settings


COMMANDS = ('source', 'audit', 'freeze', 'train-cpu', 'neural-pilot', 'train-neural',
            'pack', 'evaluate', 'predict', 'challenge-init', 'challenge-prepare',
            'challenge-finalize', 'challenge-audit')


def _ensure_absent(path):
    if Path(path).exists():
        raise HarmError('stage_output_exists')


def _cohort(root, settings):
    from .challenge import challenge_reservation
    from .conversation import build_cases
    from .source import load_source
    source = load_source(root, settings)
    reservation = challenge_reservation(root)
    cohort = build_cases(source, settings)
    from .access import execution_identity
    identity = {'source_provenance_sha256': canonical_sha256(source.provenance),
                'challenge_reservation_sha256': canonical_sha256(reservation),
                'config_sha256': canonical_sha256(settings),
                'implementation_sha256': execution_identity()['sha256']}
    return cohort, reservation, identity


def _load_study(root):
    from .protocol import verify_study
    path = Path(root) / 'v1'
    if not (path / 'manifest.json').is_file():
        raise HarmError('ready_frozen_study_required')
    study = FrozenStudy(path, read_json(path / 'manifest.json'))
    binding = verify_study(study)
    if binding.get('synthetic') is True:
        raise HarmError('synthetic_study_not_a_production_cli_input')
    return study


def _common_neural_batches(candidates, batches):
    kinds = [ref for ref in candidates if ref.kind.endswith('_neural')]
    if not kinds:
        return batches
    first = batches[kinds[0].config_id]
    for ref in kinds:
        current = batches[ref.config_id]
        if current.case_ids != first.case_ids or current.coverage != first.coverage:
            raise HarmError('neural_selection_coverage_mismatch')
    indices = tuple(index for index, covered in enumerate(first.coverage) if covered)
    if not indices:
        raise HarmError('neural_selection_no_compatible_cases')
    result = dict(batches)
    for ref in kinds:
        current = batches[ref.config_id]
        result[ref.config_id] = ScoreBatch(
            tuple(current.case_ids[index] for index in indices),
            tuple(current.scores[index] for index in indices),
            (True,) * len(indices), current.runtime)
    return result


def select_and_calibrate(study, candidates, *, neural_python=None):
    """Fit choices/calibration from development only; never load protected rows."""
    from .cpu import score_candidate
    from .protocol import assert_fitting_allowed, load_development
    from .selection import fit_calibration, select_candidates
    from threadpoolctl import threadpool_limits
    assert_fitting_allowed(study)
    development = load_development(study)
    validation_labels = {row.case_id: row.label for row in development['validation']}
    def score(ref, rows):
        runtime = None
        if ref.kind.endswith('_neural'):
            interpreter = neural_python or ref.fit_record.get('neural_python')
            if interpreter is None:
                raise HarmError('neural_interpreter_required')
            runtime = {'python': str(interpreter)}
        return score_candidate(ref, rows, runtime)
    batches = {ref.config_id: score(ref, development['validation']) for ref in candidates}
    batches = _common_neural_batches(candidates, batches)
    selections = select_candidates(tuple(candidates), batches, validation_labels)
    calibration_refs = tuple(choice.candidate for choice in selections.values())
    calibration_batches = {ref.config_id: score(ref, development['calibration'])
                           for ref in calibration_refs}
    calibration_batches = _common_neural_batches(calibration_refs, calibration_batches)
    calibration_labels = {row.case_id: row.label for row in development['calibration']}
    components = read_json(Path(study.path) / 'components.json', max_bytes=16 * 1024 * 1024)['development']
    calibrators = {}
    with threadpool_limits(limits=4):
        for kind, choice in selections.items():
            assert_fitting_allowed(study)
            calibrators[kind] = fit_calibration(choice, calibration_batches[choice.candidate.config_id],
                                                calibration_labels, components)
    assert_fitting_allowed(study)
    return selections, calibrators


def _save_selection(path, study, selections, calibrators):
    from .access import execution_identity
    root = Path(path).resolve().parent
    candidates = {}
    for kind, choice in selections.items():
        directory = Path(choice.candidate.directory).resolve()
        if not directory.is_relative_to(root):
            raise HarmError('selection_candidate_outside_models')
        candidates[kind] = {
            'kind': kind, 'config_id': choice.candidate.config_id,
            'directory': directory.relative_to(root).as_posix(),
            'fit_record': choice.candidate.fit_record,
            'raw_threshold': choice.raw_threshold, 'validation_report': choice.validation_report,
            'calibration': asdict(calibrators[kind]),
        }
    record = {'schema_version': 1, 'release_status': 'research_only',
              'study_manifest_sha256': canonical_sha256(study.manifest),
              'implementation': execution_identity(), 'candidates': candidates}
    write_json(path, record, exclusive=True)
    return record


def _load_selection(path, study):
    from .access import execution_identity
    from .artifacts import _checked_candidate
    record = read_json(path, max_bytes=8 * 1024 * 1024)
    if (record.get('schema_version') != 1 or record.get('release_status') != 'research_only'
            or record.get('study_manifest_sha256') != canonical_sha256(study.manifest)
            or record.get('implementation') != execution_identity()
            or not isinstance(record.get('candidates'), dict)):
        raise HarmError('selection_record_changed')
    choices, calibrators = {}, {}
    for kind, value in record['candidates'].items():
        directory = safe_path(Path(path).parent, value['directory'])
        candidate = CandidateRef(kind, value['config_id'], directory, value['fit_record'])
        _checked_candidate(candidate)
        choices[kind] = Selection(candidate, value['raw_threshold'], value['validation_report'])
        cal = value['calibration']
        calibrators[kind] = CalibrationRecord(cal['status'], cal['slope'], cal['intercept'], cal['report'])
    return choices, calibrators


def _selection_summary(selections, calibrators):
    return {kind: {'config_id': choice.candidate.config_id,
                  'raw_threshold': choice.raw_threshold,
                  'validation_status': choice.validation_report.get('status'),
                  'validation_recall': choice.validation_report.get('recall'),
                  'validation_fpr': choice.validation_report.get('fpr'),
                  'calibration_status': calibrators[kind].status}
            for kind, choice in selections.items()}


def _challenge_summary(record):
    allowed = ('schema_version', 'status', 'case_count', 'labelled_count', 'uncertain_count',
               'adjudicated_count', 'families', 'claim_ready', 'reserved', 'packet_sha256')
    return {key: record[key] for key in allowed if key in record}


def _neural_summary(record):
    allowed = ('schema_version', 'status', 'reason', 'may_fit_full_candidate',
               'pilot_rows', 'optimizer_steps', 'forecast_seconds', 'peak_allocated_bytes',
               'peak_reserved_bytes', 'study_manifest_sha256', 'source_manifest_sha256')
    return {key: record[key] for key in allowed if key in record}


def _execute(args):
    command = args.command
    if command == 'predict':
        if not args.research:
            raise HarmError('research_artifact_live_refused')
        from .artifacts import predict_research
        from .conversation import parse_submission
        submitted = read_json(args.input_json, max_bytes=128 * 1024)
        return predict_research(args.artifact, parse_submission(submitted))
    root = args.root.resolve()
    if any(part.casefold() == 'onedrive' for part in root.parts):
        raise HarmError('private_research_path_in_onedrive')
    settings = default_settings()
    if command.startswith('challenge-'):
        from .challenge import (audit_challenge, finalize_challenge_reviews, init_challenge,
                                prepare_challenge_reviews)
        operation = {'challenge-init': init_challenge, 'challenge-audit': audit_challenge,
                     'challenge-prepare': prepare_challenge_reviews,
                     'challenge-finalize': finalize_challenge_reviews}[command]
        return _challenge_summary(operation(root))
    runs = root / 'runs'
    if command == 'source':
        from .source import acquire_release
        _ensure_absent(runs / 'source.json')
        provenance = acquire_release(root, settings)
        report = {'schema_version': 1, 'status': 'ready', 'stage': 'source',
                  'archive_sha256': settings['source']['sha256'],
                  'member_sha256': settings['source']['member_sha256'],
                  'provenance_sha256': canonical_sha256(provenance),
                  'annotation_rows': provenance.get('annotation_rows'),
                  'utterances': provenance.get('utterances')}
        write_json(runs / 'source.json', report, exclusive=True)
        return report
    if command == 'audit':
        from .protocol import audit_cohort
        _ensure_absent(runs / 'audit.json')
        cohort, reservation, identity = _cohort(root, settings)
        report = {**audit_cohort(cohort, reservation, PRODUCTION_CRITERIA),
                  'audit_binding': identity, 'models_trained': False, 'final_test_scored': False}
        write_json(runs / 'audit.json', report, exclusive=True)
        return report
    if command == 'freeze':
        from .protocol import freeze_study, verify_study
        _ensure_absent(root / 'v1')
        audit = read_json(runs / 'audit.json', max_bytes=4 * 1024 * 1024)
        if audit.get('status') != 'ready':
            raise HarmError('prior_protocol_unavailable')
        _, _, identity = _cohort(root, settings)
        if audit.get('audit_binding') != identity:
            raise HarmError('prior_audit_identity_changed')
        study = freeze_study(root, settings)
        binding = verify_study(study)
        report = {'schema_version': 1, 'status': 'frozen', 'synthetic': binding['synthetic'],
                  'study_manifest_sha256': canonical_sha256(study.manifest), 'audit': binding['audit']}
        write_json(runs / 'freeze.json', report, exclusive=True)
        return report
    study = _load_study(root)
    if command == 'evaluate':
        from .evaluation import evaluate_final
        return evaluate_final(study, args.artifact, args.output)
    from .protocol import assert_fitting_allowed
    assert_fitting_allowed(study)
    models = args.models.resolve()
    if any(part.casefold() == 'onedrive' for part in models.parts):
        raise HarmError('models_private_path_in_onedrive')
    if command == 'train-cpu':
        from .cpu import fit_cpu_candidates
        record_path = models / 'cpu-selection.json'
        _ensure_absent(record_path)
        candidates = fit_cpu_candidates(study, models / 'cpu', settings)
        selections, calibrators = select_and_calibrate(study, candidates)
        _save_selection(record_path, study, selections, calibrators)
        return {'schema_version': 1, 'status': 'complete', 'stage': command,
                'study_manifest_sha256': canonical_sha256(study.manifest),
                'branches': _selection_summary(selections, calibrators), 'final_test_scored': False}
    if command == 'neural-pilot':
        from .neural import run_neural_pilot
        from .neural_sources import prepare_neural_sources
        pilot_path = models / 'neural-pilot.json'
        _ensure_absent(pilot_path)
        if not args.neural_python.is_file():
            raise HarmError('neural_python_unavailable')
        catalog = Path(__file__).resolve().parents[2] / 'output/research/context-harm-neural-package-catalog.json'
        sources = prepare_neural_sources(root, catalog)
        if sources.get('status') != 'ready':
            write_json(pilot_path, sources, exclusive=True)
            return _neural_summary(sources)
        record = run_neural_pilot(study, args.neural_python, sources, pilot_path)
        return _neural_summary(record)
    if command == 'train-neural':
        from .neural import fit_neural_candidates
        record_path = models / 'neural-selection.json'
        _ensure_absent(record_path)
        pilot = read_json(models / 'neural-pilot.json', max_bytes=4 * 1024 * 1024)
        if pilot.get('status') != 'ready' or pilot.get('may_fit_full_candidate') is not True:
            raise HarmError('neural_pilot_unavailable')
        candidates = fit_neural_candidates(study, pilot, args.neural_python, models / 'neural', settings)
        selections, calibrators = select_and_calibrate(study, candidates, neural_python=args.neural_python)
        _save_selection(record_path, study, selections, calibrators)
        return {'schema_version': 1, 'status': 'complete', 'stage': command,
                'branches': _selection_summary(selections, calibrators), 'final_test_scored': False}
    if command == 'pack':
        from .artifacts import export_artifact
        selections, calibrators = _load_selection(models / 'cpu-selection.json', study)
        if (models / 'neural-selection.json').exists():
            neural, neural_calibrators = _load_selection(models / 'neural-selection.json', study)
            selections.update(neural)
            calibrators.update(neural_calibrators)
        else:
            records = [path for path in (models / 'neural-pilot.json', runs / 'neural-pilot-unavailable.json',
                       runs / 'train-neural-unavailable.json', root / 'neural-sources-unavailable.json') if path.exists()]
            unavailable = any(read_json(path, max_bytes=4 * 1024 * 1024).get('status') == 'neural_unavailable'
                              for path in records)
            if not unavailable:
                raise HarmError('neural_participation_not_locked')
        output = args.output.resolve() if args.output is not None else models / 'artifact'
        metadata = export_artifact(selections, calibrators, study, output)
        return {'schema_version': 1, 'status': 'packed', 'release_status': metadata['release_status'],
                'model_version': metadata['model_version'], 'coverage': metadata['coverage'],
                'branches': _selection_summary(selections, calibrators), 'final_test_scored': False}
    raise HarmError('unsupported_research_command')


def _failure(args, error):
    reason = error.reason if isinstance(error, HarmError) else 'stage_inputs_or_resources_unavailable'
    if not isinstance(reason, str) or not re.fullmatch(r'[a-z0-9_:., -]{1,512}', reason):
        reason = 'stage_failed'
    neural = args.command in ('neural-pilot', 'train-neural')
    record = {'schema_version': 1, 'task_id': 'english_directed_abuse', 'stage': args.command,
              'status': 'neural_unavailable' if neural else 'unavailable', 'reason': reason}
    if neural:
        record['may_fit_full_candidate'] = False
    root = getattr(args, 'root', None)
    if root is not None:
        try:
            audit_path = root / 'runs/audit.json'
            if audit_path.exists():
                audit = read_json(audit_path, max_bytes=4 * 1024 * 1024)
                if audit.get('status') == 'unavailable':
                    record['unavailable_reasons'] = audit.get('unavailable_reasons', [])
                    record['failed_allocation'] = audit.get('failed_allocation')
                    record['audit_sha256'] = sha256(audit_path)
            output = root / 'runs' / (args.command + '-unavailable.json')
            if output.exists():
                output = output.with_name(args.command + '-unavailable-' + uuid4().hex + '.json')
            write_json(output, record, exclusive=True)
        except (HarmError, OSError, ValueError):
            record['unavailable_record_status'] = 'could_not_persist'
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sentinel English directed-abuse research workflow')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in COMMANDS:
        stage = commands.add_parser(name)
        if name != 'predict':
            stage.add_argument('--root', type=Path, required=True)
        if name in ('train-cpu', 'neural-pilot', 'train-neural', 'pack'):
            stage.add_argument('--models', type=Path, required=True)
        if name in ('neural-pilot', 'train-neural'):
            stage.add_argument('--neural-python', type=Path, required=True)
        if name in ('evaluate', 'predict'):
            stage.add_argument('--artifact', type=Path, required=True)
        if name == 'evaluate':
            stage.add_argument('--output', type=Path, required=True)
        if name == 'pack':
            stage.add_argument('--output', type=Path)
        if name == 'predict':
            stage.add_argument('--input-json', type=Path, required=True)
            stage.add_argument('--research', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command != 'predict' and sys.version_info[:3] != (3, 11, 17):
            raise HarmError('research_requires_locked_python31117')
        result = _execute(args)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 2 if result.get('status') == 'neural_unavailable' else 0
    except (HarmError, OSError, ImportError, ValueError, KeyError, TypeError) as error:
        print(json.dumps(_failure(args, error), sort_keys=True, allow_nan=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
