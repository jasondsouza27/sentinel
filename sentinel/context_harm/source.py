"""Verified CAD v1.1 source, literal TSV text and explicit directed-abuse labels."""
import csv
import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from .contracts import CadUtterance, HarmError, SourceRelease
from .integrity import canonical_sha256, publish_stage, read_json, safe_path, sha256, write_json
from .transport import AcquisitionSession

FIELDS = (
    'id', 'info_id', 'info_subreddit', 'info_subreddit_id', 'info_id.parent',
    'info_id.link', 'info_thread.id', 'info_order', 'info_image.saved',
    'annotation_Primary', 'annotation_Secondary', 'annotation_Context',
    'annotation_Target', 'annotation_Target_top.level.category',
    'annotation_highlighted', 'meta_author', 'meta_created_utc', 'meta_date',
    'meta_day', 'meta_permalink', 'split', 'subreddit_seen', 'meta_text',
)
DIRECTED = frozenset(('IdentityDirectedAbuse', 'AffiliationDirectedAbuse', 'PersonDirectedAbuse'))
LABELS = DIRECTED | {'Neutral', 'CounterSpeech', 'Slur'}
ELIGIBLE_SPLITS = frozenset(('train', 'dev', 'test'))
EXCLUSIONS = frozenset(('exclude_bot', 'exclude_empty', 'exclude_image', 'exclude_lang'))
MISSING = frozenset(('', 'na', 'nan', 'none', '[deleted]', '[removed]'))
ARCHIVE_SHA = '69f5ed2fd7b40de21fe54c620549f0be6c34eaf55b8de06ff481cabe3e9476d2'
MEMBER_SHA = '7287d635e1d35ae1e64779ffe107df16f493c6ccc4084c4497bbf3f56ae0f349'


def default_settings() -> dict:
    return read_json(Path(__file__).resolve().parents[2] / 'configs/context-harm-v1.json')


def metadata_value(value: str) -> str | None:
    if not isinstance(value, str):
        raise HarmError('source_field_not_string')
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].strip()
    return None if value.casefold() in MISSING else value


def map_labels(labels: tuple[str, ...]) -> int:
    values = set(labels)
    if not values or not values <= LABELS or ('Neutral' in values and len(values) > 1):
        raise HarmError('source_label_set_invalid')
    return int(bool(values & DIRECTED))


def coalesce_rows(rows: list[dict[str, str]]) -> tuple[CadUtterance, ...]:
    grouped = defaultdict(list)
    for row in rows:
        if set(row) != set(FIELDS) or any(not isinstance(value, str) for value in row.values()):
            raise HarmError('source_schema_invalid')
        case_id = metadata_value(row['info_id'])
        if case_id is None or metadata_value(row['info_thread.id']) is None:
            raise HarmError('source_identity_missing')
        grouped[case_id].append(row)
    output = []
    for case_id, annotations in sorted(grouped.items()):
        first = annotations[0]
        identity_fields = ('info_thread.id', 'info_id.parent', 'info_id.link', 'meta_author', 'info_order')
        for name in identity_fields:
            if len({metadata_value(row[name]) for row in annotations}) != 1:
                raise HarmError('source_utterance_conflict')
        if len({row['meta_text'] for row in annotations}) != 1:
            raise HarmError('source_utterance_conflict')
        splits = {metadata_value(row['split']) for row in annotations}
        if not splits <= ELIGIBLE_SPLITS | EXCLUSIONS or len(splits & ELIGIBLE_SPLITS) > 1:
            raise HarmError('source_split_conflict')
        labels = tuple(sorted({value for row in annotations if (value := metadata_value(row['annotation_Primary'])) is not None}))
        if labels:
            map_labels(labels)
        text = first['meta_text']
        supported = bool(text.strip()) and text.strip().casefold() not in ('[deleted]', '[removed]')
        supported = supported and not bool(splits & {'exclude_empty', 'exclude_image', 'exclude_lang'})
        eligible = bool(splits & ELIGIBLE_SPLITS) and not bool(splits & EXCLUSIONS) and supported
        if eligible:
            map_labels(labels)
        tags = tuple(sorted({value for row in annotations if (value := metadata_value(row['annotation_Context'])) is not None}))
        split = next(iter(splits & ELIGIBLE_SPLITS), sorted(splits)[0])
        order = metadata_value(first['info_order'])
        output.append(CadUtterance(case_id, metadata_value(first['info_thread.id']),
            metadata_value(first['info_id.parent']), metadata_value(first['info_id.link']),
            metadata_value(first['meta_author']), tuple(token.strip() for token in order.split(',')) if order else (),
            text, split, labels, tags, eligible, supported,
            {'community': metadata_value(first['info_subreddit']),
             'date': metadata_value(first['meta_date']), 'created_utc': metadata_value(first['meta_created_utc']),
             'annotation_rows': len(annotations), 'excluded_splits': sorted(splits & EXCLUSIONS)}))
    return tuple(output)


def read_cad_tsv(path: Path) -> tuple[CadUtterance, ...]:
    try:
        with Path(path).open('r', encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream, delimiter='\t', quoting=csv.QUOTE_NONE)
            if reader.fieldnames != list(FIELDS):
                raise HarmError('source_schema_invalid')
            rows = list(reader)
        return coalesce_rows(rows)
    except (csv.Error, UnicodeError, OSError) as error:
        raise HarmError('source_tsv_unavailable_or_invalid') from error


def verify_archive(path: Path, pin: dict, *, max_member_bytes: int = 16 * 1024 * 1024) -> dict:
    if Path(path).stat().st_size != pin['size'] or sha256(path) != pin['sha256']:
        raise HarmError('source_archive_pin_mismatch')
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 128 or len({info.filename for info in infos}) != len(infos):
                raise HarmError('source_archive_members_invalid')
            for info in infos:
                name = PurePosixPath(info.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in info.filename or ':' in info.filename or stat.S_ISLNK(info.external_attr >> 16):
                    raise HarmError('source_archive_path_invalid')
            member = archive.getinfo(pin['member'])
            if member.file_size > max_member_bytes:
                raise HarmError('source_member_oversized')
            with archive.open(member) as stream:
                tsv = stream.read(max_member_bytes + 1)
            if len(tsv) > max_member_bytes or hashlib.sha256(tsv).hexdigest() != pin['member_sha256']:
                raise HarmError('source_member_pin_mismatch')
            codebook_name = pin.get('codebook', 'data/cad_codebook_april2021.pdf')
            book = archive.getinfo(codebook_name)
            if book.file_size > 1024 * 1024:
                raise HarmError('source_codebook_oversized')
            codebook = archive.read(book)
            if not codebook.startswith(b'%PDF-'):
                raise HarmError('source_codebook_invalid')
            return {'tsv': tsv, 'codebook': codebook,
                    'codebook_sha256': hashlib.sha256(codebook).hexdigest()}
    except (zipfile.BadZipFile, KeyError, RuntimeError) as error:
        raise HarmError('source_archive_invalid') from error


def _production_settings(settings: dict) -> None:
    source = settings.get('source', {})
    if (source.get('sha256') != ARCHIVE_SHA or source.get('member_sha256') != MEMBER_SHA
        or source.get('size') != 9941773 or source.get('member') != 'data/cad_v1_1.tsv'
        or source.get('download_url') != 'https://zenodo.org/api/records/4881008/files/data.zip/content'
        or source.get('metadata_url') != 'https://zenodo.org/api/records/4881008'
        or settings.get('schema_version') != 1):
        raise HarmError('source_configuration_not_production')
    limits = settings.get('acquisition', {})
    if (limits.get('max_received_body_bytes') != 32 * 1024 * 1024
        or limits.get('deadline_seconds') != 120 or limits.get('allow_hosts') != ['zenodo.org']):
        raise HarmError('source_configuration_not_production')


def acquire_release(root: Path, settings: dict) -> dict:
    _production_settings(settings)
    root = Path(root).resolve(); pin = settings['source']
    with AcquisitionSession(root / 'acquisition', settings['acquisition']) as session:
        metadata = session.fetch(pin['metadata_url'], session.root / 'record.json',
                                 resource='metadata', max_bytes=1024 * 1024)
        record = read_json(session.root / 'record.json')
        if record.get('id') != 4881008 or record.get('metadata', {}).get('license', {}).get('id') != 'cc-by-4.0':
            raise HarmError('source_record_or_license_mismatch')
        receipt = session.fetch(pin['download_url'], session.root / 'data.zip', resource='archive',
                                max_bytes=12 * 1024 * 1024, expected_size=pin['size'], expected_sha256=pin['sha256'])
        content = verify_archive(session.root / 'data.zip', pin)
        output = root / 'source'
        if output.exists():
            return load_source(root, settings).provenance
        stage = Path(tempfile.mkdtemp(prefix='.source-stage-', dir=root))
        try:
            (stage / 'cad_v1_1.tsv').write_bytes(content['tsv'])
            (stage / 'cad_codebook_april2021.pdf').write_bytes(content['codebook'])
            records = read_cad_tsv(stage / 'cad_v1_1.tsv')
            provenance = {'schema_version': 1, 'status': 'verified_source_only',
                'source_id': 'cad-v1.1', 'record_url': 'https://zenodo.org/records/4881008',
                'license': 'CC-BY-4.0', 'archive_sha256': receipt['sha256'], 'member_sha256': MEMBER_SHA,
                'codebook_sha256': content['codebook_sha256'], 'metadata_sha256': metadata['sha256'],
                'config_sha256': canonical_sha256(settings), 'annotation_rows': sum(r.metadata['annotation_rows'] for r in records),
                'utterances': len(records), 'eligible_utterances': sum(r.eligible for r in records),
                'eligible_splits': dict(Counter(r.split for r in records if r.eligible)),
                'eligible_class_counts': dict(Counter(str(map_labels(r.labels)) for r in records if r.eligible)),
                'mixed_label_utterances': sum(len(r.labels) > 1 for r in records),
                'source_exclusions': dict(Counter(flag for r in records for flag in r.metadata['excluded_splits'])),
                'taxonomy_review': 'pending_codebook_inspection', 'models_trained': False, 'final_test_scored': False}
            write_json(stage / 'metadata.json', provenance)
            publish_stage(stage, output, {name: sha256(stage / name) for name in
                ('cad_v1_1.tsv', 'cad_codebook_april2021.pdf', 'metadata.json')})
            return provenance
        finally:
            if stage.exists():
                if stage.resolve().parent != root:
                    raise HarmError('source_stage_cleanup_outside_root')
                shutil.rmtree(stage)


def load_source(root: Path, settings: dict) -> SourceRelease:
    _production_settings(settings)
    path = Path(root).resolve() / 'source'
    manifest = read_json(path / 'manifest.json')
    expected = {'cad_v1_1.tsv', 'cad_codebook_april2021.pdf', 'metadata.json'}
    if manifest.get('schema_version') != 1 or set(manifest.get('members', {})) != expected:
        raise HarmError('source_manifest_invalid')
    for name, digest in manifest['members'].items():
        if sha256(safe_path(path, name)) != digest:
            raise HarmError('source_member_changed')
    provenance = read_json(path / 'metadata.json')
    if (provenance.get('archive_sha256') != ARCHIVE_SHA or provenance.get('member_sha256') != MEMBER_SHA
        or provenance.get('config_sha256') != canonical_sha256(settings)
        or sha256(path / 'cad_v1_1.tsv') != MEMBER_SHA):
        raise HarmError('source_provenance_changed')
    return SourceRelease(read_cad_tsv(path / 'cad_v1_1.tsv'), provenance)
