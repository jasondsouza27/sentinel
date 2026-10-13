"""Durable, exclusive final reservations; completed studies cannot be rescored."""
import hashlib
import json
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from uuid import uuid4

from .contracts import FrozenStudy, HarmError
from .integrity import canonical_bytes, canonical_sha256, read_json, write_json
from .protocol import read_cases, verify_study


BOOTSTRAP = {'seed': 42, 'replicates': 1000,
             'unit': 'connected_test_thread_author_duplicate_component'}
IDENTITY_FIELDS = frozenset((
    'artifact_manifest_sha256', 'implementation', 'selected_settings',
    'preprocessing', 'cohorts', 'coverage', 'tokenizer_base_hashes',
    'bootstrap', 'output',
))
HEX = re.compile(r'[a-f0-9]{64}\Z')
SUPPORT_FILES = (
    'sentinel/analysis.py', 'sentinel/url_ml/metrics.py', 'sentinel/url_ml/contracts.py',
    'sentinel/url_v2/ranges.py', 'sentinel/url_v2/contracts.py', 'sentinel/url_v2/storage.py',
    'configs/context-harm-v1.json',
)
LOCK_FILES = ('requirements-ml-win-py311.lock.txt',
              'requirements-url-data-win-py311.lock.txt',
              'requirements-harm-neural-win-py311.lock.txt')


def execution_identity() -> dict:
    """Bind all harm code, imported support, config, locks and CPU package versions."""
    root = Path(__file__).resolve().parents[2]
    paths = {path.relative_to(root).as_posix(): path
             for path in (root / 'sentinel/context_harm').glob('*.py')}
    paths.update({name: root / name for name in SUPPORT_FILES + LOCK_FILES})
    files = {}
    for name, path in sorted(paths.items()):
        if not path.is_file():
            if name == 'requirements-harm-neural-win-py311.lock.txt':
                files[name] = None
                continue
            raise HarmError('execution_binding_file_missing')
        data = path.read_bytes().replace(b'\r\n', b'\n')
        if path.suffix == '.json':
            files[name] = canonical_sha256(read_json(path))
        else:
            files[name] = hashlib.sha256(data).hexdigest()
    pins = {}
    for line in (root / LOCK_FILES[0]).read_text(encoding='utf-8').splitlines():
        match = re.match(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)', line.strip())
        if match:
            try:
                pins[match.group(1)] = metadata.version(match.group(1))
            except metadata.PackageNotFoundError:
                pins[match.group(1)] = None
    identity = {
        'files': files, 'locks': {name: files[name] for name in LOCK_FILES},
        'environment': {'python': '.'.join(map(str, sys.version_info[:3])),
                        'cpu_packages': pins},
    }
    return {**identity, 'sha256': canonical_sha256(identity)}


@contextmanager
def _lock(path):
    from sentinel.url_ml.contracts import DatasetError
    from sentinel.url_v2.ranges import cache_lock
    try:
        with cache_lock(path):
            yield
    except DatasetError:
        raise HarmError('final_access_busy') from None


@contextmanager
def final_scoring_lock(study: FrozenStudy):
    """Keep identical concurrent evaluators from sharing an in-progress receipt."""
    with _lock(Path(study.path).resolve().parent / '.final-evaluation-lock'):
        yield


def _study_binding(study):
    binding = verify_study(study)
    return binding, {
        'study_manifest_sha256': canonical_sha256(study.manifest),
        'source': binding.get('source'),
        'config_sha256': binding.get('config_sha256'),
        'protocol_code_hashes': binding.get('code_hashes'),
        'case_hashes': binding.get('case_hashes'),
        'synthetic': binding.get('synthetic') is True,
    }


def _validated_identity(identity, binding):
    if not isinstance(identity, dict) or set(identity) != IDENTITY_FIELDS:
        raise HarmError('final_identity_incomplete')
    digest = identity.get('artifact_manifest_sha256')
    if not isinstance(digest, str) or not HEX.fullmatch(digest):
        raise HarmError('final_artifact_identity_invalid')
    if (identity.get('implementation') != execution_identity()
            or identity.get('bootstrap') != BOOTSTRAP
            or identity.get('cohorts') != binding.get('case_hashes')
            or identity.get('preprocessing') != binding.get('settings', {}).get('context')):
        raise HarmError('final_identity_mismatch')
    settings = identity.get('selected_settings')
    if (not isinstance(settings, dict) or not {'target_cpu', 'context_cpu'} <= set(settings)
            or set(settings) - {'target_cpu', 'context_cpu', 'target_neural', 'context_neural'}
            or (('target_neural' in settings) != ('context_neural' in settings))):
        raise HarmError('final_selection_identity_invalid')
    if (not isinstance(identity.get('coverage'), dict) or not identity['coverage']
            or not isinstance(identity.get('tokenizer_base_hashes'), dict)
            or not isinstance(identity.get('output'), str)
            or not Path(identity['output']).is_absolute()):
        raise HarmError('final_coverage_or_output_identity_invalid')
    # A JSON round trip detaches the durable identity from caller-owned dictionaries.
    return json.loads(canonical_bytes(identity))


def begin_final_access(study: FrozenStudy, identity: dict) -> dict:
    binding, study_binding = _study_binding(study)
    identity = _validated_identity(identity, binding)
    path = Path(study.path).resolve().parent / 'final-access.json'
    with _lock(path.parent / '.final-access-lock'):
        if path.exists():
            receipt = read_json(path, max_bytes=4 * 1024 * 1024)
            if receipt.get('status') == 'complete':
                raise HarmError('final_evaluation_already_complete')
            if (receipt.get('schema_version') != 1 or receipt.get('status') != 'reserved'
                    or receipt.get('study_binding') != study_binding
                    or receipt.get('identity') != identity
                    or receipt.get('identity_sha256') != canonical_sha256(identity)):
                raise HarmError('final_reserved_identity_changed')
            return receipt
        receipt = {
            'schema_version': 1, 'task_id': 'english_directed_abuse',
            'status': 'reserved', 'reservation_id': uuid4().hex,
            'reserved_at': datetime.now(timezone.utc).isoformat(),
            'study_binding': study_binding, 'identity': identity,
            'identity_sha256': canonical_sha256(identity),
        }
        write_json(path, receipt, exclusive=True)
        return receipt


def _validate_receipt(study, receipt):
    path = Path(study.path).resolve().parent / 'final-access.json'
    saved = read_json(path, max_bytes=4 * 1024 * 1024)
    binding, study_binding = _study_binding(study)
    if (not isinstance(receipt, dict) or saved != receipt
            or saved.get('schema_version') != 1 or saved.get('status') != 'reserved'
            or saved.get('study_binding') != study_binding):
        raise HarmError('final_receipt_invalid_or_complete')
    identity = _validated_identity(saved.get('identity'), binding)
    if saved.get('identity_sha256') != canonical_sha256(identity):
        raise HarmError('final_receipt_identity_changed')
    return saved


def load_final_test(study: FrozenStudy, receipt: dict):
    with _lock(Path(study.path).resolve().parent / '.final-access-lock'):
        _validate_receipt(study, receipt)
        return read_cases(Path(study.path) / 'test.jsonl')


def load_final_diagnostics(study: FrozenStudy, receipt: dict):
    """The declared protected diagnostics share the primary final reservation."""
    with _lock(Path(study.path).resolve().parent / '.final-access-lock'):
        _validate_receipt(study, receipt)
        return read_cases(Path(study.path) / 'diagnostics.jsonl')


def finish_final_access(study: FrozenStudy, receipt: dict, report_hash: str) -> None:
    if not isinstance(report_hash, str) or not HEX.fullmatch(report_hash):
        raise HarmError('final_report_hash_invalid')
    path = Path(study.path).resolve().parent / 'final-access.json'
    with _lock(path.parent / '.final-access-lock'):
        saved = _validate_receipt(study, receipt)
        completed = {**saved, 'status': 'complete', 'report_sha256': report_hash,
                     'completed_at': datetime.now(timezone.utc).isoformat()}
        write_json(path, completed)
