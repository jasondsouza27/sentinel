"""Sparse training factories. Importing this module imports no ML packages."""
from pathlib import Path
from .contracts import HarmCase, HarmError, ModelText

KINDS = ('target_cpu', 'context_cpu')


def _params(params):
    if (not isinstance(params, dict) or set(params) != {'C', 'class_weight'}
            or type(params.get('C')) not in (int, float) or params['C'] not in (0.5, 1.0, 2.0)
            or params.get('class_weight') not in (None, 'balanced')):
        raise HarmError('cpu_candidate_settings_invalid')
    return dict(params)


def candidate_grid() -> tuple[dict, ...]:
    return tuple({'kind': kind, 'config_id': kind + '-c' + format(c, 'g') + '-' + ('none' if weight is None else weight),
                  'params': {'C': c, 'class_weight': weight}}
                 for kind in KINDS for c in (0.5, 1.0, 2.0) for weight in (None, 'balanced'))


class CPUModel:
    def __init__(self, kind, params):
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        self.kind, self.params = kind, dict(params)
        self.target_vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=30000, dtype=np.float32)
        self.context_vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=30000, dtype=np.float32) if kind == 'context_cpu' else None
        self.classifier = LogisticRegression(C=params['C'], class_weight=params['class_weight'],
                                              solver='liblinear', max_iter=1000, random_state=42)

    def _texts(self, rows):
        from .text import prepare_model_text
        values = []
        for row in rows:
            value = row.model_input if isinstance(row, HarmCase) else row
            if not isinstance(value, ModelText):
                raise HarmError('cpu_model_text_required')
            values.append(prepare_model_text(value))
        return values

    def _matrix(self, rows, *, fit):
        from scipy.sparse import hstack
        texts = self._texts(rows)
        target = [value.target for value in texts]
        target_matrix = self.target_vectorizer.fit_transform(target) if fit else self.target_vectorizer.transform(target)
        if self.kind == 'target_cpu':
            return target_matrix
        context = [' [CONTEXT_TURN] '.join(value.context) for value in texts]
        context_matrix = self.context_vectorizer.fit_transform(context) if fit else self.context_vectorizer.transform(context)
        return hstack((target_matrix, context_matrix), format='csr')

    def fit(self, rows):
        import warnings
        from sklearn.exceptions import ConvergenceWarning
        from threadpoolctl import threadpool_limits
        rows = tuple(rows)
        if any(not isinstance(row, HarmCase) or type(row.label) is not int or row.label not in (0, 1) for row in rows) or {row.label for row in rows} != {0, 1}:
            raise HarmError('cpu_training_classes_invalid')
        with warnings.catch_warnings(), threadpool_limits(limits=4):
            warnings.simplefilter('error', ConvergenceWarning)
            try:
                self.classifier.fit(self._matrix(rows, fit=True), [row.label for row in rows])
            except ConvergenceWarning:
                raise HarmError('cpu_nonconvergence') from None
        return self

    def transform(self, rows):
        return self._matrix(rows, fit=False)

    def predict_proba(self, rows):
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=4):
            return self.classifier.predict_proba(self.transform(rows))

    @property
    def classes_(self):
        return self.classifier.classes_


def build_cpu_model(kind: str, params: dict) -> CPUModel:
    if kind not in KINDS:
        raise HarmError('cpu_candidate_kind_invalid')
    return CPUModel(kind, _params(params))

# These settings are the approved fixed family, not caller-selected tuning.
CPU_SETTINGS = {'c_values': [0.5, 1.0, 2.0], 'class_weights': [None, 'balanced'], 'max_features': 30000,
                'max_iter': 1000, 'solver': 'liblinear', 'deadline_seconds': 900,
                'rss_bytes': 8589934592, 'native_threads': 4}
CPU_IMPLEMENTATION_FILES = ('cpu.py', 'text.py', 'worker.py', 'runtime.py', 'contracts.py', 'integrity.py')
CPU_DEPENDENCIES = ('numpy', 'scipy', 'scikit-learn', 'joblib', 'psutil', 'threadpoolctl')
MAX_MODEL_BYTES = 64 * 1024**2
SCORE_BATCH_SIZE = 128

import hashlib
import importlib.metadata
import math
import os
import shutil
import sys
import tempfile
import threading
import time
from uuid import uuid4

from .contracts import CandidateRef, FrozenStudy, ScoreBatch, WorkerLimits
from .integrity import canonical_bytes, canonical_sha256, publish_stage, read_json, sha256, write_json
from .runtime import run_worker

_FIT_LOCK = threading.Lock()


def _lf_hash(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def implementation_hashes() -> dict:
    directory = Path(__file__).resolve().parent
    return {name: _lf_hash(directory / name) for name in CPU_IMPLEMENTATION_FILES}


def dependency_binding() -> dict:
    try:
        versions = {name: importlib.metadata.version(name) for name in CPU_DEPENDENCIES}
        lock = Path(__file__).resolve().parents[2] / 'requirements-ml-win-py311.lock.txt'
        pinned = dict(line.split('==', 1) for line in lock.read_text(encoding='utf-8').splitlines()
                      if line and not line.startswith('#'))
        if any(pinned.get(name) != value for name, value in versions.items()):
            raise HarmError('cpu_dependency_lock_mismatch')
        if sys.version_info[:3] != (3, 11, 17):
            raise HarmError('cpu_python_version_unsupported')
        return {'dependencies': versions, 'dependency_lock_sha256': _lf_hash(lock), 'python_version': '3.11.17'}
    except (OSError, importlib.metadata.PackageNotFoundError):
        raise HarmError('cpu_dependencies_unavailable') from None


def _settings(settings):
    if not isinstance(settings, dict) or settings.get('cpu') != CPU_SETTINGS:
        raise HarmError('cpu_settings_not_production')
    return dict(settings['cpu'])


def _entry(kind, params):
    params = _params(params)
    for value in candidate_grid():
        if value['kind'] == kind and value['params'] == params:
            return value
    raise HarmError('cpu_candidate_settings_invalid')


def _feature_row(row):
    if not isinstance(row, HarmCase) or not isinstance(row.case_id, str) or not row.case_id or len(row.case_id) > 256 or not isinstance(row.model_input, ModelText):
        raise HarmError('cpu_score_rows_invalid')
    return {'case_id': row.case_id, 'model_input': {'target': row.model_input.target,
                                                 'context': list(row.model_input.context)}}


def _covered(kind, value):
    return (isinstance(value.target, str) and bool(value.target.strip()) and len(value.target) <= 10000
            and isinstance(value.context, tuple) and len(value.context) <= 4
            and all(isinstance(turn, str) and bool(turn.strip()) for turn in value.context)
            and len(value.target) + sum(len(turn) for turn in value.context) <= 20000
            and (kind == 'target_cpu' or bool(value.context)))


def _fit_rows(rows, kind, params, directory, study_manifest, settings):
    """Fit/save in a private stage; the supervisor adds its measured fit record."""
    import joblib
    rows, directory = tuple(rows), Path(directory)
    entry, cpu_settings = _entry(kind, params), _settings(settings)
    if any(not _covered(kind, row.model_input) for row in rows):
        raise HarmError('cpu_training_input_outside_coverage')
    if len({row.case_id for row in rows}) != len(rows):
        raise HarmError('cpu_training_duplicate_identity')
    dependencies = dependency_binding()
    code = implementation_hashes()
    started = time.perf_counter()
    model = build_cpu_model(kind, params).fit(rows)
    directory.mkdir(parents=True, exist_ok=False)
    model_path = directory / 'model.joblib'
    joblib.dump(model, model_path, compress=3, protocol=5)
    if model_path.stat().st_size > MAX_MODEL_BYTES:
        raise HarmError('cpu_model_oversized')
    training = [{'case_id': row.case_id, 'label': row.label, 'model_input': _feature_row(row)['model_input']}
                for row in rows]
    feature_counts = {'target': len(model.target_vectorizer.vocabulary_),
                      'context': len(model.context_vectorizer.vocabulary_) if model.context_vectorizer is not None else 0}
    return {'schema_version': 1, 'task_id': 'english_directed_abuse', 'status': 'ok', 'kind': kind,
            'config_id': entry['config_id'], 'params': params, 'cpu_settings': cpu_settings,
            'cpu_settings_sha256': canonical_sha256(cpu_settings),
            'study_manifest_sha256': canonical_sha256(study_manifest),
            'training_cohort_sha256': canonical_sha256(training),
            'train_ids_sha256': canonical_sha256(sorted(row.case_id for row in rows)), 'train_rows': len(rows),
            'implementation': code, 'implementation_sha256': canonical_sha256(code), **dependencies,
            'members': {'model.joblib': sha256(model_path)}, 'feature_counts': feature_counts,
            'fit_seconds': time.perf_counter() - started}


def checked_candidate(candidate: CandidateRef) -> dict:
    """Check all caller-bound metadata and model bytes before joblib can run."""
    if not isinstance(candidate, CandidateRef):
        raise HarmError('cpu_candidate_reference_invalid')
    entry = _entry(candidate.kind, candidate.fit_record.get('params'))
    record = read_json(Path(candidate.directory) / 'fit-record.json')
    if record != candidate.fit_record or candidate.config_id != entry['config_id']:
        raise HarmError('cpu_fit_record_changed')
    if (record.get('schema_version') != 1 or record.get('task_id') != 'english_directed_abuse'
            or record.get('status') != 'ok' or record.get('kind') != candidate.kind
            or record.get('config_id') != candidate.config_id or record.get('cpu_settings') != CPU_SETTINGS
            or record.get('cpu_settings_sha256') != canonical_sha256(CPU_SETTINGS)):
        raise HarmError('cpu_fit_record_invalid')
    for field in ('study_manifest_sha256', 'training_cohort_sha256', 'train_ids_sha256'):
        value = record.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise HarmError('cpu_fit_record_invalid')
    code = implementation_hashes()
    if record.get('implementation') != code or record.get('implementation_sha256') != canonical_sha256(code):
        raise HarmError('cpu_implementation_changed')
    dependencies = dependency_binding()
    if any(record.get(key) != value for key, value in dependencies.items()):
        raise HarmError('cpu_dependencies_changed')
    measured = record.get('fit_runtime', {})
    if (not isinstance(measured, dict) or measured.get('ownership') != 'windows_job_kill_on_close'
            or measured.get('cleanup_complete') is not True or measured.get('monitoring_complete') is not True
            or measured.get('native_threads') != 4 or measured.get('rss_limit_bytes') != 8589934592
            or measured.get('deadline_seconds') != 900 or type(measured.get('rss_peak_bytes')) is not int
            or not 0 < measured['rss_peak_bytes'] <= 8589934592):
        raise HarmError('cpu_fit_runtime_invalid')
    if type(record.get('train_rows')) is not int or record['train_rows'] <= 0:
        raise HarmError('cpu_fit_record_invalid')
    counts = record.get('feature_counts', {})
    if (not isinstance(counts, dict) or set(counts) != {'target', 'context'}
            or any(type(count) is not int or not 0 <= count <= 30000 for count in counts.values())
            or counts['target'] == 0 or (candidate.kind == 'context_cpu' and counts['context'] == 0)):
        raise HarmError('cpu_fit_record_invalid')
    path = Path(candidate.directory) / 'model.joblib'
    if record.get('members', {}).keys() != {'model.joblib'} or not path.is_file() or not 0 < path.stat().st_size <= MAX_MODEL_BYTES:
        raise HarmError('cpu_model_member_invalid')
    if sha256(path) != record['members']['model.joblib']:
        raise HarmError('cpu_model_hash_changed')
    return record


def fit_cpu_candidates(study: FrozenStudy, output: Path, settings: dict) -> tuple[CandidateRef, ...]:
    from .protocol import assert_fitting_allowed
    cpu_settings = _settings(settings)
    assert_fitting_allowed(study)
    if not _FIT_LOCK.acquire(blocking=False):
        raise HarmError('cpu_fitting_busy')
    stage, measurements = None, []
    output = Path(output).resolve()
    try:
        if output.exists():
            raise HarmError('cpu_output_already_exists')
        if any(part.casefold() == 'onedrive' for part in output.parts):
            raise HarmError('cpu_private_path_in_onedrive')
        output.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.cpu-stage-', dir=output.parent))
        for entry in candidate_grid():
            assert_fitting_allowed(study)
            request = stage / ('request-' + entry['config_id'] + '.json')
            write_json(request, {'operation': 'cpu_fit', 'study_path': str(Path(study.path).resolve()),
                                 'study_manifest_sha256': canonical_sha256(study.manifest), 'settings': settings,
                                 'kind': entry['kind'], 'params': entry['params'],
                                 'output_directory': str(stage / entry['config_id'])}, exclusive=True)
            try:
                result = run_worker([sys.executable, '-m', 'sentinel.context_harm.worker', '--request', str(request)],
                                    WorkerLimits(cpu_settings['deadline_seconds'], cpu_settings['rss_bytes'], cpu_settings['native_threads']))
            finally:
                request.unlink(missing_ok=True)
            measurements.append({'kind': entry['kind'], 'config_id': entry['config_id'], 'status': result.status,
                                 'reason': result.reason, 'measurements': result.measurements})
            if result.status != 'ok':
                raise HarmError(result.reason or 'cpu_candidate_unavailable')
            record = result.output.get('fit_record')
            if not isinstance(record, dict) or record.get('study_manifest_sha256') != canonical_sha256(study.manifest):
                raise HarmError('cpu_worker_fit_binding_invalid')
            record = {**record, 'fit_runtime': result.measurements}
            directory = stage / entry['config_id']
            write_json(directory / 'fit-record.json', record, exclusive=True)
            checked_candidate(CandidateRef(entry['kind'], entry['config_id'], directory, record))
        assert_fitting_allowed(study)
        files = {path.relative_to(stage).as_posix(): sha256(path) for path in stage.rglob('*') if path.is_file()}
        publish_stage(stage, output, files)
        return tuple(CandidateRef(entry['kind'], entry['config_id'], output / entry['config_id'],
                                  read_json(output / entry['config_id'] / 'fit-record.json')) for entry in candidate_grid())
    except Exception as error:
        if stage is not None:
            reason = error.reason if isinstance(error, HarmError) else 'cpu_training_failed'
            write_json(output.parent / (output.name + '.failure-' + uuid4().hex + '.json'),
                       {'schema_version': 1, 'status': 'unavailable', 'reason': reason,
                        'study_manifest_sha256': canonical_sha256(study.manifest), 'candidates': measurements}, exclusive=True)
        if isinstance(error, HarmError):
            raise
        raise HarmError('cpu_training_failed') from None
    finally:
        if stage is not None and stage.exists() and stage.resolve().parent == output.parent and stage.name.startswith('.cpu-stage-'):
            shutil.rmtree(stage)
        _FIT_LOCK.release()


def _score_limits(runtime):
    runtime = {} if runtime is None else runtime
    if not isinstance(runtime, dict):
        raise HarmError('cpu_score_runtime_invalid')
    limits = WorkerLimits(runtime.get('deadline_seconds', 60), runtime.get('rss_bytes', 8589934592), runtime.get('native_threads', 4))
    if (type(limits.deadline_seconds) is not int or not 0 < limits.deadline_seconds <= 60
            or type(limits.rss_bytes) is not int or not 0 < limits.rss_bytes <= 8589934592
            or type(limits.native_threads) is not int or not 0 < limits.native_threads <= 4):
        raise HarmError('cpu_score_runtime_invalid')
    return limits, runtime.get('python', sys.executable)


def score_candidate(candidate: CandidateRef, rows: tuple[HarmCase, ...], runtime: dict | None = None) -> ScoreBatch:
    record = checked_candidate(candidate)
    limits, interpreter = _score_limits(runtime)
    features = tuple(_feature_row(row) for row in rows)
    ids = tuple(row['case_id'] for row in features)
    if len(set(ids)) != len(ids):
        raise HarmError('cpu_score_duplicate_identity')
    scores, coverage, measurements = [], [], []
    started = time.perf_counter()
    for start in range(0, len(features), SCORE_BATCH_SIZE):
        chunk = features[start:start + SCORE_BATCH_SIZE]
        payload = canonical_bytes({'operation': 'cpu_score', 'kind': candidate.kind, 'config_id': candidate.config_id,
                                   'candidate_directory': str(Path(candidate.directory).resolve()),
                                   'fit_record_sha256': canonical_sha256(record), 'rows': chunk})
        result = run_worker([interpreter, '-m', 'sentinel.context_harm.worker', '--request-stdin'], limits,
                            input_payload=payload)
        measurements.append(result.measurements)
        if result.status != 'ok':
            return ScoreBatch(ids, (None,) * len(ids), (False,) * len(ids),
                              {'status': 'unavailable', 'reason': result.reason, 'records': measurements,
                               'wall_seconds': time.perf_counter() - started})
        value = result.output
        if (value.get('case_ids') != [row['case_id'] for row in chunk]
                or not isinstance(value.get('scores'), list) or not isinstance(value.get('coverage'), list)
                or len(value['scores']) != len(chunk) or len(value['coverage']) != len(chunk)
                or any(type(flag) is not bool for flag in value['coverage'])
                or any((type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1) if flag else score is not None
                       for score, flag in zip(value['scores'], value['coverage']))):
            raise HarmError('cpu_worker_scores_invalid')
        scores.extend(value['scores'])
        coverage.extend(value['coverage'])
    return ScoreBatch(ids, tuple(scores), tuple(coverage), {'status': 'ok', 'records': measurements,
                      'wall_seconds': time.perf_counter() - started,
                      'rss_peak_bytes': max((item.get('rss_peak_bytes', 0) for item in measurements), default=0)})


def _request_rows(rows):
    if not isinstance(rows, list) or len(rows) > SCORE_BATCH_SIZE:
        raise HarmError('cpu_score_request_invalid')
    result = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'case_id', 'model_input'} or not isinstance(row['case_id'], str)
                or not row['case_id'] or len(row['case_id']) > 256 or not isinstance(row['model_input'], dict)
                or set(row['model_input']) != {'target', 'context'} or not isinstance(row['model_input']['target'], str)
                or not isinstance(row['model_input']['context'], list)
                or any(not isinstance(turn, str) for turn in row['model_input']['context'])):
            raise HarmError('cpu_score_request_invalid')
        result.append((row['case_id'], ModelText(row['model_input']['target'], tuple(row['model_input']['context']))))
    if len({identity for identity, _ in result}) != len(result):
        raise HarmError('cpu_score_duplicate_identity')
    return tuple(result)


def worker_operation(request: dict) -> dict:
    """Invoked only after worker ownership; final rows are never opened here."""
    if request.get('operation') == 'cpu_fit':
        from .protocol import assert_fitting_allowed, load_development
        path = Path(request['study_path']).resolve()
        study = FrozenStudy(path, read_json(path / 'manifest.json'))
        if canonical_sha256(study.manifest) != request.get('study_manifest_sha256'):
            raise HarmError('cpu_study_manifest_changed')
        assert_fitting_allowed(study)
        development = load_development(study)
        record = _fit_rows(development['train'], request['kind'], request['params'],
                           Path(request['output_directory']), study.manifest, request['settings'])
        assert_fitting_allowed(study)
        return {'fit_record': record}
    if request.get('operation') != 'cpu_score':
        raise HarmError('cpu_worker_operation_invalid')
    directory = Path(request['candidate_directory'])
    record = read_json(directory / 'fit-record.json')
    if canonical_sha256(record) != request.get('fit_record_sha256'):
        raise HarmError('cpu_fit_record_changed')
    candidate = CandidateRef(request['kind'], request['config_id'], directory, record)
    checked_candidate(candidate)
    rows = _request_rows(request.get('rows'))
    coverage = tuple(_covered(candidate.kind, value) for _, value in rows)
    scores = [None] * len(rows)
    covered = [value for (_, value), flag in zip(rows, coverage) if flag]
    if covered:
        import joblib
        model = joblib.load(directory / 'model.joblib')
        if not isinstance(model, CPUModel) or model.kind != candidate.kind or model.params != record['params'] or list(model.classes_) != [0, 1]:
            raise HarmError('cpu_model_schema_invalid')
        probabilities = model.predict_proba(covered)[:, list(model.classes_).index(1)]
        iterator = iter(probabilities)
        for index, flag in enumerate(coverage):
            if flag:
                value = float(next(iterator))
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise HarmError('cpu_model_scores_invalid')
                scores[index] = value
    return {'case_ids': [identity for identity, _ in rows], 'scores': scores, 'coverage': list(coverage)}
