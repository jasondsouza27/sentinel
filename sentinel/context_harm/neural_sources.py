"""Pinned wheel/model admission with durable aggregate transfer budgets."""
import hashlib
from pathlib import Path
import re
import shutil

from .contracts import FrozenStudy, HarmError
from .integrity import canonical_sha256, read_json, sha256, write_json
from .transport import AcquisitionSession

CATALOG_SHA256 = '3258969ce816008b95fbeb16232f84687e5dbe5d628fd8c56aaad9b3abe994a0'
MODEL_ID = 'distilbert/distilbert-base-uncased'
REVISION = '12040accade4e8a0f71eabdb258fecc2e7e948be'
MODEL_FILES = ('model.safetensors','config.json','tokenizer.json','tokenizer_config.json','vocab.txt','LICENSE','README.md')
WHEEL_BODY_BUDGET = 4 * 1024**3
MODEL_BODY_BUDGET = 512 * 1024**2
WHEEL_LIMITS = {'allow_hosts':['files.pythonhosted.org','download.pytorch.org','download-r2.pytorch.org'],
                'deadline_seconds':600,'max_received_body_bytes':WHEEL_BODY_BUDGET,'max_attempts':1}
MODEL_LIMITS = {'allow_hosts':['huggingface.co','cdn-lfs.huggingface.co','cdn-lfs.hf.co','cdn-lfs-us-1.hf.co','cas-bridge.xethub.hf.co'],
                'deadline_seconds':600,'max_received_body_bytes':MODEL_BODY_BUDGET,'max_attempts':1}


def load_catalog(path: Path) -> dict:
    value = read_json(Path(path))
    if canonical_sha256(value) != CATALOG_SHA256:
        raise HarmError('neural_catalog_changed')
    packages = value.get('packages', [])
    if (len(packages) != 26 or len({p['name'] for p in packages}) != 26
            or value.get('target') != {'architecture':'AMD64','extras':[],'os':'Windows','python':'3.11.17'}):
        raise HarmError('neural_catalog_invalid')
    return value


def lock_text(catalog: dict) -> str:
    return '# Exact Windows CPython 3.11.17 runtime; catalog ' + CATALOG_SHA256 + '\n' + '\n'.join(
        package['name'] + '==' + package['version'] + ' --hash=sha256:' + package['sha256']
        for package in sorted(catalog['packages'], key=lambda p:p['name'])) + '\n'


def installation_commands(bootstrap_python: Path, environment: Path, wheelhouse: Path, lock: Path) -> list[list[str]]:
    environment = Path(environment)
    if environment.name != '.venv-harm-neural':
        raise HarmError('neural_environment_must_be_separate')
    interpreter = str(environment / 'Scripts/python.exe')
    return [[str(bootstrap_python), '-m', 'venv', str(environment)],
            [interpreter, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheelhouse),
             '--require-hashes', '-r', str(lock)], [interpreter, '-m', 'pip', 'check']]


def require_disk_capacity(path: Path) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(path).free < 12 * 1024**3:
        raise HarmError('neural_disk_capacity_unavailable')


def _wheel_path(root, filename):
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith('.whl'):
        raise HarmError('neural_wheel_filename_invalid')
    return Path(root) / filename


def verify_wheelhouse(root: Path, catalog: dict) -> dict:
    root = Path(root)
    expected = {package['filename'] for package in catalog['packages']}
    if {path.name for path in root.glob('*.whl')} != expected:
        raise HarmError('neural_wheel_changed')
    measured = {}
    for package in catalog['packages']:
        path = _wheel_path(root, package['filename'])
        size = path.stat().st_size
        if (size <= 0 or size > WHEEL_BODY_BUDGET or
                (package.get('size_bytes') is not None and size != package['size_bytes']) or sha256(path) != package['sha256']):
            raise HarmError('neural_wheel_changed')
        measured[package['filename']] = {'sha256':package['sha256'],'size_bytes':size}
    return measured


def _download_wheels(root: Path, catalog: dict, *, limits: dict | None = None) -> dict:
    limits = WHEEL_LIMITS if limits is None else limits
    with AcquisitionSession(root, limits) as session:
        for package in catalog['packages']:
            session.fetch(package['url'], _wheel_path(root, package['filename']), resource='wheel-' + package['name'],
                          max_bytes=package.get('size_bytes') or WHEEL_BODY_BUDGET,
                          expected_size=package.get('size_bytes'), expected_sha256=package['sha256'])
        snapshot = session.snapshot()
    return {'members':verify_wheelhouse(root, catalog),'acquisition':snapshot}


def model_metadata(value: dict) -> dict:
    if value.get('sha') != REVISION or value.get('id') != MODEL_ID:
        raise HarmError('neural_model_revision_changed')
    siblings = value.get('siblings')
    if not isinstance(siblings, list):
        raise HarmError('neural_model_metadata_invalid')
    selected = {}
    for item in siblings:
        if not isinstance(item, dict):
            raise HarmError('neural_model_metadata_invalid')
        name = item.get('rfilename')
        if name not in MODEL_FILES:
            continue
        if name in selected or type(item.get('size')) is not int or item['size'] <= 0:
            raise HarmError('neural_model_metadata_invalid')
        lfs = item.get('lfs')
        if lfs is not None:
            if not isinstance(lfs, dict) or not re.fullmatch(r'[a-f0-9]{64}', str(lfs.get('sha256'))) or lfs.get('size') != item['size']:
                raise HarmError('neural_model_metadata_invalid')
            identity = {'type':'sha256_lfs','value':lfs['sha256']}
        else:
            if name == 'model.safetensors' or not re.fullmatch(r'[a-f0-9]{40}', str(item.get('blobId'))):
                raise HarmError('neural_model_metadata_invalid')
            identity = {'type':'git_blob_sha1','value':item['blobId']}
        selected[name] = {'size_bytes':item['size'],'identity':identity}
    if set(selected) != set(MODEL_FILES) or sum(item['size_bytes'] for item in selected.values()) > MODEL_BODY_BUDGET:
        raise HarmError('neural_model_metadata_invalid')
    return {'base_model_id':MODEL_ID,'revision':REVISION,'files':selected}


def verify_model_members(root: Path, metadata: dict) -> dict[str,str]:
    if metadata.get('base_model_id') != MODEL_ID or metadata.get('revision') != REVISION or set(metadata.get('files', {})) != set(MODEL_FILES):
        raise HarmError('neural_model_metadata_invalid')
    hashes = {}
    for name, info in metadata['files'].items():
        path = Path(root) / name
        if not path.is_file() or path.stat().st_size != info['size_bytes']:
            raise HarmError('neural_model_blob_changed')
        if info['identity']['type'] == 'sha256_lfs':
            actual = sha256(path)
        elif info['identity']['type'] == 'git_blob_sha1':
            digest = hashlib.sha1(b'blob ' + str(info['size_bytes']).encode('ascii') + b'\0')
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1024*1024), b''):
                    digest.update(chunk)
            actual = digest.hexdigest()
        else:
            raise HarmError('neural_model_metadata_invalid')
        if actual != info['identity']['value']:
            raise HarmError('neural_model_blob_changed')
        hashes[name] = sha256(path)
    return hashes


def _download_model(root: Path) -> dict:
    root = Path(root)
    api = 'https://huggingface.co/api/models/' + MODEL_ID + '/revision/' + REVISION + '?blobs=true'
    with AcquisitionSession(root, MODEL_LIMITS) as session:
        session.fetch(api, root/'revision-metadata.json',resource='revision-metadata',max_bytes=1024**2)
        metadata = model_metadata(read_json(root/'revision-metadata.json'))
        for name, info in metadata['files'].items():
            session.fetch('https://huggingface.co/' + MODEL_ID + '/resolve/' + REVISION + '/' + name,
                          root/name,resource='model-' + name.replace('.', '-').lower(),max_bytes=info['size_bytes'],
                          expected_size=info['size_bytes'],
                          expected_sha256=info['identity']['value'] if info['identity']['type']=='sha256_lfs' else None)
        snapshot = session.snapshot()
    return {'metadata':metadata,'members':verify_model_members(root, metadata),'acquisition':snapshot}


def verify_sources(sources: dict) -> dict:
    if (not isinstance(sources, dict) or sources.get('status') != 'ready' or sources.get('catalog_sha256') != CATALOG_SHA256
            or sources.get('base_model_id') != MODEL_ID or sources.get('revision') != REVISION):
        raise HarmError('neural_sources_unavailable_or_changed')
    manifest = sources.get('manifest')
    if not isinstance(manifest, dict) or canonical_sha256(manifest) != sources.get('source_manifest_sha256'):
        raise HarmError('neural_sources_unavailable_or_changed')
    catalog = load_catalog(Path(sources['catalog_path']))
    if verify_wheelhouse(Path(sources['wheelhouse_path']), catalog) != manifest['wheels']['members']:
        raise HarmError('neural_sources_unavailable_or_changed')
    if verify_model_members(Path(sources['model_dir']), manifest['model']['metadata']) != manifest['model']['members']:
        raise HarmError('neural_sources_unavailable_or_changed')
    return sources


def prepare_neural_sources(root: Path, catalog: Path) -> dict:
    """No body request is made unless the protected study is already admitted."""
    root = Path(root).resolve()
    pins = load_catalog(catalog)
    from .protocol import assert_fitting_allowed
    try:
        study = FrozenStudy(root/'v1',read_json(root/'v1/manifest.json'))
        assert_fitting_allowed(study)
    except (HarmError, OSError):
        record = {'schema_version':1,'status':'neural_unavailable','reason':'protected_cohort_unavailable',
                  'may_fit_full_candidate':False,'catalog_sha256':CATALOG_SHA256}
        write_json(root/'neural-sources-unavailable.json',record)
        return record
    if any(part.casefold() == 'onedrive' for part in root.parts):
        raise HarmError('neural_private_path_in_onedrive')
    try:
        require_disk_capacity(root)
        ready_path = root/'neural-sources.json'
        if ready_path.exists():
            return verify_sources(read_json(ready_path,max_bytes=4*1024**2))
        wheelhouse = root/'neural-acquisition/wheels'
        model_dir = root/'neural-acquisition/model'
        wheels = _download_wheels(wheelhouse,pins)
        model = _download_model(model_dir)
        manifest = {'schema_version':1,'catalog_sha256':CATALOG_SHA256,'base_model_id':MODEL_ID,'revision':REVISION,
                    'wheels':wheels,'model':model}
        record = {'schema_version':1,'status':'ready','may_fit_full_candidate':False,'catalog_sha256':CATALOG_SHA256,
                  'base_model_id':MODEL_ID,'revision':REVISION,'catalog_path':str(Path(catalog).resolve()),
                  'wheelhouse_path':str(wheelhouse),'model_dir':str(model_dir),'tokenizer_dir':str(model_dir),
                  'manifest':manifest,'source_manifest_sha256':canonical_sha256(manifest)}
        write_json(ready_path,record,exclusive=True)
        return record
    except (HarmError, OSError) as error:
        reason = error.reason if isinstance(error,HarmError) else 'neural_sources_unavailable'
        record = {'schema_version':1,'status':'neural_unavailable','reason':reason,'may_fit_full_candidate':False,
                  'catalog_sha256':CATALOG_SHA256}
        write_json(root/'neural-sources-unavailable.json',record)
        return record
