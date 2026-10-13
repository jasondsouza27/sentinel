"""Locally trusted, hash-checked harm bundles; schema 1 always stays research-only."""
import math
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from .access import HEX, execution_identity
from .contracts import (CalibrationRecord, CandidateRef, ConversationInput, HarmCase,
                        HarmError, Selection)
from .integrity import (canonical_sha256, read_json, safe_path,
                        sha256, write_json)
from .protocol import assert_fitting_allowed, load_development, verify_study


CPU_KINDS = frozenset(('target_cpu', 'context_cpu'))
NEURAL_KINDS = frozenset(('target_neural', 'context_neural'))
BASE_MEMBERS = frozenset(('metadata.json', 'study-binding.json',
                          'protocol-manifest.json', 'model_card.md'))


def _branch_set(names):
    names = set(names)
    if not CPU_KINDS <= names or names - (CPU_KINDS | NEURAL_KINDS):
        raise HarmError('artifact_branches_invalid')
    if bool(names & NEURAL_KINDS) and not NEURAL_KINDS <= names:
        raise HarmError('artifact_neural_pair_missing')
    return names


def _calibrator(value):
    if not isinstance(value, CalibrationRecord) or value.status not in ('available', 'unavailable'):
        raise HarmError('artifact_calibration_invalid')
    if value.status == 'available':
        if (type(value.slope) not in (int, float) or type(value.intercept) not in (int, float)
                or not math.isfinite(value.slope) or not math.isfinite(value.intercept)
                or value.slope <= 0):
            raise HarmError('artifact_calibration_invalid')
    elif value.slope is not None or value.intercept is not None:
        raise HarmError('artifact_calibration_invalid')
    canonical_sha256(asdict(value))
    return value


def _threshold(value):
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value)
                              or not 0 <= value <= 1):
        raise HarmError('artifact_threshold_invalid')


def _checked_candidate(ref):
    if ref.kind in CPU_KINDS:
        from .cpu import checked_candidate
        return checked_candidate(ref)
    if ref.kind not in NEURAL_KINDS:
        raise HarmError('artifact_candidate_kind_invalid')
    from .neural import checked_candidate
    return checked_candidate(ref)


def _member_names(kind, record):
    members = record.get('members')
    if not isinstance(members, dict) or not members:
        raise HarmError('artifact_candidate_members_invalid')
    if kind in CPU_KINDS and set(members) != {'model.joblib'}:
        raise HarmError('artifact_cpu_members_invalid')
    if kind in NEURAL_KINDS:
        if not any(name.endswith('.safetensors') for name in members):
            raise HarmError('artifact_neural_weights_missing')
        if any(Path(name).suffix not in ('.safetensors', '.json', '.txt', '.md', '')
               or Path(name).name.endswith(('.joblib', '.pickle', '.bin', '.pt'))
               for name in members):
            raise HarmError('artifact_neural_members_invalid')
    return tuple(sorted((*members, 'fit-record.json')))


def _candidate_params(kind, record):
    if kind in CPU_KINDS:
        return record.get('params')
    return {'learning_rate': record.get('learning_rate'),
            'selected_epoch': record.get('selected_epoch'),
            'settings': record.get('settings')}

def _training_binding(rows):
    return canonical_sha256([{
        'case_id': row.case_id, 'label': row.label,
        'model_input': {'target': row.model_input.target, 'context': list(row.model_input.context)},
    } for row in rows])


def export_artifact(selections, calibrators, study, output: Path) -> dict:
    names = _branch_set(selections)
    if set(calibrators) != names:
        raise HarmError('artifact_calibrators_missing')
    assert_fitting_allowed(study)
    binding = verify_study(study)
    development = load_development(study)
    output = Path(output).resolve()
    if output.exists():
        raise HarmError('artifact_output_exists')
    if any(part.casefold() == 'onedrive' for part in output.parts):
        raise HarmError('artifact_private_path_in_onedrive')
    branches = {}
    for kind in sorted(names):
        selection = selections[kind]
        if not isinstance(selection, Selection) or selection.candidate.kind != kind:
            raise HarmError('artifact_selection_invalid')
        _threshold(selection.raw_threshold)
        _calibrator(calibrators[kind])
        record = _checked_candidate(selection.candidate)
        if record.get('study_manifest_sha256') != canonical_sha256(study.manifest):
            raise HarmError('artifact_candidate_study_mismatch')
        if (record.get('synthetic_fixture') or record.get('synthetic') is True) and binding.get('synthetic') is not True:
            raise HarmError('artifact_synthetic_candidate_for_real_study')
        if kind in CPU_KINDS and (
                record.get('training_cohort_sha256') != _training_binding(development['train'])
                or record.get('train_ids_sha256') != canonical_sha256(
                    sorted(row.case_id for row in development['train']))
                or record.get('train_rows') != len(development['train'])):
            raise HarmError('artifact_training_cohort_mismatch')
        branches[kind] = {
            'config_id': selection.candidate.config_id, 'params': _candidate_params(kind, record),
            'selection_partition': record.get('selection_partition', 'validation'),
            'compatible_cohort_sha256': record.get('compatible_cohort_sha256'),
            'raw_threshold': selection.raw_threshold,
            'validation_report': selection.validation_report,
            'calibration': asdict(calibrators[kind]),
            'fit_record_sha256': canonical_sha256(record),
            'member_names': list(_member_names(kind, record)),
            'model_hashes': record['members'],
            'fit_seconds': record.get('fit_seconds'),
            'fit_resources': {
                'rss_peak_bytes': record.get('fit_runtime', {}).get('rss_peak_bytes'),
                'gpu_allocated_peak_bytes': record.get('peak_allocated_bytes'),
                'gpu_reserved_peak_bytes': record.get('peak_reserved_bytes'),
                'native_threads': record.get('fit_runtime', {}).get('native_threads'),
            },
            'tokenizer_base_hashes': record.get('tokenizer_base_hashes',
                                               record.get('source_hashes', {})),
        }
    metadata = {
        'schema_version': 1, 'task_id': 'english_directed_abuse',
        'release_status': 'research_only', 'synthetic': binding.get('synthetic') is True,
        'implementation': execution_identity(),
        'protocol_manifest_sha256': canonical_sha256(study.manifest),
        'study_binding_sha256': canonical_sha256(binding),
        'source': binding.get('source'), 'config_sha256': binding.get('config_sha256'),
        'cohort_hashes': binding.get('case_hashes'), 'branches': branches,
        'coverage': {'cpu': 'full_primary_within_application_caps',
                     'neural': 'participating' if names & NEURAL_KINDS else 'unavailable'},
        'preprocessing': binding['settings']['context'],
        'neural_settings': binding['settings']['neural'],
    }
    metadata['model_version'] = canonical_sha256(metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.harm-artifact-stage-', dir=output.parent))
    try:
        write_json(stage / 'metadata.json', metadata, exclusive=True)
        write_json(stage / 'study-binding.json', binding, exclusive=True)
        write_json(stage / 'protocol-manifest.json', study.manifest, exclusive=True)
        for kind, branch in branches.items():
            source = Path(selections[kind].candidate.directory)
            for name in branch['member_names']:
                destination = safe_path(stage, 'branches/' + kind + '/' + name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(safe_path(source, name), destination)
        (stage / 'model_card.md').write_text(
            '# Sentinel English directed-abuse research artifact\n\n'
            'This schema-1 bundle is research-only. Live learned warnings remain unavailable.\n\n'
            'Synthetic fixtures verify software behaviour only; they do not measure detector quality.\n\n'
            'CAD v1.1 is attributed to its author release under CC BY 4.0: '
            'https://zenodo.org/records/4881008 . The study pools purged original train/dev '
            'threads and preserves published test-thread ownership.\n\n'
            'Decisions use frozen raw validation thresholds under the declared 5% FPR budget. '
            'Calibration affects displayed probabilities only when supported. Historical Reddit '
            'labels do not establish contemporary, multilingual or cross-platform accuracy, intent '
            'or repeated harassment.\n\n'
            'Hash checks detect changed local bytes and settings; they do not authenticate '
            'an artifact downloaded from an untrusted source.\n', encoding='utf-8')
        assert_fitting_allowed(study)
        members = {path.relative_to(stage).as_posix(): sha256(path)
                   for path in stage.rglob('*') if path.is_file()}
        # The checksum must exist in the private stage before the bundle becomes
        # visible. Publishing a directory before this write leaves a partial
        # artifact behind when that write is interrupted.
        manifest = {'schema_version': 1, 'members': dict(sorted(members.items()))}
        write_json(stage / 'manifest.json', manifest, exclusive=True)
        (stage / 'manifest.sha256').write_text(sha256(stage / 'manifest.json') + '\n', encoding='ascii')
        os.rename(stage, output)
        inspect_artifact(output, research=True)
        return metadata
    finally:
        if stage.exists() and stage.resolve().parent == output.parent:
            shutil.rmtree(stage)


def inspect_artifact(path: Path, *, research: bool = False) -> dict:
    """Check schema, every member and implementation before any model can load."""
    path = Path(path).resolve()
    try:
        checksum = (path / 'manifest.sha256').read_text(encoding='ascii').strip()
        if not HEX.fullmatch(checksum) or checksum != sha256(path / 'manifest.json'):
            raise HarmError('artifact_manifest_hash_changed')
        manifest = read_json(path / 'manifest.json', max_bytes=4 * 1024 * 1024)
        if manifest.get('schema_version') != 1 or not isinstance(manifest.get('members'), dict):
            raise HarmError('artifact_schema_unsupported')
        for name, digest in manifest['members'].items():
            member = safe_path(path, name)
            if not isinstance(digest, str) or not HEX.fullmatch(digest) or sha256(member) != digest:
                raise HarmError('artifact_member_changed')
        actual = {member.relative_to(path).as_posix() for member in path.rglob('*') if member.is_file()}
        if actual != set(manifest['members']) | {'manifest.json', 'manifest.sha256'}:
            raise HarmError('artifact_member_set_changed')
        metadata = read_json(path / 'metadata.json', max_bytes=8 * 1024 * 1024)
        if (metadata.get('schema_version') != 1 or metadata.get('task_id') != 'english_directed_abuse'
                or metadata.get('release_status') != 'research_only'):
            raise HarmError('artifact_schema_unsupported')
        if research is not True:
            raise HarmError('research_artifact_live_refused')
        if metadata.get('implementation') != execution_identity():
            raise HarmError('artifact_implementation_or_locks_changed')
        if metadata.get('model_version') != canonical_sha256(
                {key: value for key, value in metadata.items() if key != 'model_version'}):
            raise HarmError('artifact_model_version_changed')
        branches = metadata.get('branches')
        if not isinstance(branches, dict):
            raise HarmError('artifact_branches_invalid')
        _branch_set(branches)
        binding = read_json(path / 'study-binding.json', max_bytes=4 * 1024 * 1024)
        protocol = read_json(path / 'protocol-manifest.json')
        if (metadata.get('study_binding_sha256') != canonical_sha256(binding)
                or metadata.get('protocol_manifest_sha256') != canonical_sha256(protocol)
                or metadata.get('cohort_hashes') != binding.get('case_hashes')
                or metadata.get('config_sha256') != canonical_sha256(binding.get('settings'))
                or metadata.get('synthetic') != (binding.get('synthetic') is True)):
            raise HarmError('artifact_protocol_binding_changed')
        expected = set(BASE_MEMBERS)
        for kind, branch in branches.items():
            _threshold(branch.get('raw_threshold'))
            cal = branch.get('calibration', {})
            _calibrator(CalibrationRecord(cal.get('status'), cal.get('slope'), cal.get('intercept'),
                                           cal.get('report', {})))
            directory = safe_path(path, 'branches/' + kind)
            record = read_json(directory / 'fit-record.json', max_bytes=4 * 1024 * 1024)
            if (branch.get('fit_record_sha256') != canonical_sha256(record)
                    or record.get('study_manifest_sha256') != metadata['protocol_manifest_sha256']
                    or branch.get('member_names') != list(_member_names(kind, record))
                    or branch.get('model_hashes') != record.get('members')
                    or branch.get('params') != _candidate_params(kind, record)
                    or branch.get('tokenizer_base_hashes') != record.get('tokenizer_base_hashes',
                        record.get('source_hashes', {}))):
                raise HarmError('artifact_candidate_binding_changed')
            _checked_candidate(CandidateRef(kind, branch['config_id'], directory, record))
            expected.update('branches/' + kind + '/' + name for name in branch['member_names'])
        if expected != set(manifest['members']):
            raise HarmError('artifact_member_set_changed')
        return metadata
    except (OSError, UnicodeError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, HarmError):
            raise
        raise HarmError('artifact_unavailable_or_invalid') from None


def load_research_artifact(path: Path) -> dict:
    """Return checked references; joblib stays inside the bounded scoring worker."""
    metadata = inspect_artifact(path, research=True)
    selected, calibrators = {}, {}
    for kind, branch in metadata['branches'].items():
        directory = Path(path).resolve() / 'branches' / kind
        ref = CandidateRef(kind, branch['config_id'], directory, read_json(directory / 'fit-record.json'))
        selected[kind] = Selection(ref, branch['raw_threshold'], branch['validation_report'])
        cal = branch['calibration']
        calibrators[kind] = CalibrationRecord(cal['status'], cal['slope'], cal['intercept'], cal['report'])
    return {'metadata': metadata, 'selections': selected, 'calibrators': calibrators}


def predict_research(path: Path, request: ConversationInput) -> dict:
    """Explicit offline prediction; this helper never approves a live artifact."""
    if not isinstance(request, ConversationInput):
        raise HarmError('research_prediction_input_invalid')
    bundle = load_research_artifact(path)
    metadata = bundle['metadata']
    from .service import unavailable
    if request.language != 'en' or not request.model_input.target.strip():
        result = unavailable(request, 'unsupported_target', version=metadata['model_version'])
        return {**result, 'research_only': True}
    branch = 'context_cpu' if request.model_input.context else 'target_cpu'
    selection = bundle['selections'][branch]
    if selection.raw_threshold is None or selection.validation_report.get('status') == 'unusable':
        return {**unavailable(request, 'unusable_validation_detector', version=metadata['model_version']),
                'research_only': True}
    from .cpu import score_candidate
    row = HarmCase('submitted-target', request.model_input, (), 'submitted-case', 0, {})
    scored = score_candidate(selection.candidate, (row,))
    if scored.coverage != (True,) or len(scored.scores) != 1 or scored.scores[0] is None:
        return {**unavailable(request, 'score_outside_coverage_or_unavailable',
                              version=metadata['model_version']), 'research_only': True}
    from .selection import apply_calibration
    mapped = apply_calibration(bundle['calibrators'][branch], (scored.scores[0],))
    coverage = {**request.coverage, 'language': request.language,
                'language_assumed': request.language_assumed}
    evidence = []
    if any(mark in request.model_input.target for mark in ('"', '“', '”')):
        evidence.append('Quotation marks appear in the target; their meaning requires human review.')
    if request.model_input.context:
        evidence.append('Only preceding conversation turns are supplied as context.')
    result = {
        'schema_version': 1, 'task_id': 'english_directed_abuse', 'research_only': True,
        'state': 'complete' if request.model_input.context else 'degraded',
        'category': 'review' if scored.scores[0] >= selection.raw_threshold else 'not_flagged',
        'branch': branch, 'target_id': request.target_id, 'coverage': coverage, 'evidence': evidence,
        'unavailable_checks': [] if request.model_input.context else ['Preceding context is unavailable.'],
        'uncertainty': 'Historical content labels cannot establish intent or repeated harassment. '
                       'This assessment comes from a research-only model.',
        'action': 'Review the target and preceding conversation before deciding whether to report it.',
        'model_version': metadata['model_version'],
    }
    if mapped is not None:
        result['calibrated_probability'] = mapped[0]
    return result


