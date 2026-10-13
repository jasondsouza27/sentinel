"""Private, initially empty, independent human challenge review workflow.

No phrase rules or model predictions assign gold labels. Reviewer identities are
local attestations; this local tool cannot verify who actually performed a review.
"""
import csv
import datetime as dt
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from .contracts import HarmError
from .integrity import canonical_sha256, publish_stage, read_json, sha256, write_json
from ..url_v2.ranges import cache_lock

FAMILIES = frozenset(('quoted_abuse', 'reported_abuse', 'counter_speech',
                      'disagreement', 'direct_abuse', 'uncertain'))
FIELDS = frozenset(('case_id', 'conversation_kind', 'conversation_turns',
    'target_turn_id', 'source_ref', 'permission_basis', 'verification_ref',
    'collected_on', 'family'))
REVIEW_FIELDS = ('case_id', 'packet_sha256', 'reviewer_id', 'task_label', 'family', 'rationale')
MAX_INTAKE_BYTES = 16 * 1024 * 1024


def init_challenge(root: Path) -> dict:
    path = Path(root).resolve() / 'challenge'
    path.mkdir(parents=True, exist_ok=True)
    with cache_lock(path / 'workflow.lock'):
        intake = path / 'intake.jsonl'
        if not intake.exists():
            with intake.open('x', encoding='utf-8'):
                pass
        instructions = path / 'instructions.md'
        if not instructions.exists():
            instructions.write_text(
                '# Independent contextual-harm reviews\n\n'
                'Collect only traceable material with permission and verification references. '
                'Use opaque local case IDs and no unnecessary personal data. '
                'Each of two different humans reviews the blinded packet independently. '
                'Record task_label 0, 1, or uncertain, one listed family, and a rationale. '
                'Do not consult predictions or coordinate first-pass labels. '
                'Disagreements require a third reviewer and recorded adjudication. '
                'Quotation alone does not establish a negative label; reported abuse can '
                'contain directed abuse. Content labels do not establish author intent. '
                'Uncertain labels are excluded from scored cases. '
                'Published packet, final decisions and study reservations cannot be overwritten.\n',
                encoding='utf-8')
    return audit_challenge(root)


def _intake(path: Path) -> list[dict]:
    intake = path / 'intake.jsonl'
    if not intake.exists() or intake.stat().st_size > MAX_INTAKE_BYTES:
        raise HarmError('challenge_intake_missing_or_oversized')
    rows = []; ids = set()
    from .conversation import parse_submission
    try:
        for line in intake.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(row, dict) or set(row) != FIELDS:
                raise HarmError('challenge_intake_fields_invalid')
            if not isinstance(row['case_id'], str) or not row['case_id'].strip() or row['case_id'] in ids:
                raise HarmError('challenge_case_identity_invalid')
            if row['family'] not in FAMILIES:
                raise HarmError('challenge_family_invalid')
            for name in ('source_ref', 'permission_basis', 'verification_ref', 'collected_on'):
                if not isinstance(row[name], str) or not row[name].strip():
                    raise HarmError('challenge_provenance_required')
            dt.date.fromisoformat(row['collected_on'])
            parse_submission({k: row[k] for k in ('conversation_kind', 'conversation_turns', 'target_turn_id')})
            ids.add(row['case_id']); rows.append(row)
    except (ValueError, TypeError, KeyError) as error:
        if isinstance(error, HarmError):
            raise
        raise HarmError('challenge_intake_invalid') from error
    return rows


def _packet(rows: list[dict]) -> dict:
    return {'schema_version': 1, 'task': 'english_directed_abuse', 'cases': [
        {key: row[key] for key in ('case_id', 'conversation_kind', 'conversation_turns', 'target_turn_id')}
        for row in rows]}


def prepare_challenge_reviews(root: Path) -> dict:
    path = Path(root).resolve() / 'challenge'
    with cache_lock(path / 'workflow.lock'):
        if (path / 'reservation.json').exists():
            raise HarmError('challenge_already_reserved')
        rows = _intake(path); output = path / 'review-packet'
        if output.exists():
            raise HarmError('challenge_packet_exists')
        stage = Path(tempfile.mkdtemp(prefix='.review-stage-', dir=path))
        try:
            write_json(stage / 'packet.json', _packet(rows))
            digest = sha256(stage / 'packet.json')
            write_json(stage / 'provenance.json', {'schema_version': 1,
                'intake_sha256': sha256(path / 'intake.jsonl'), 'case_count': len(rows),
                'packet_sha256': digest})
            # Editable responses are outside the immutable packet member set.
            for filename in ('reviewer-a.csv', 'reviewer-b.csv'):
                with (stage / filename).open('x', encoding='utf-8', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
                    writer.writeheader()
                    writer.writerows({'case_id': row['case_id'], 'packet_sha256': digest} for row in rows)
            # publish_stage requires an exact member set, including the initial blank forms.
            initial = publish_stage(stage, output, {name: sha256(stage / name) for name in
                ('packet.json', 'provenance.json', 'reviewer-a.csv', 'reviewer-b.csv')})
            return {'status': 'pending', 'case_count': len(rows), 'packet_sha256': digest,
                    'initial_manifest_sha256': initial['manifest_sha256']}
        finally:
            if stage.exists() and stage.resolve().parent == path:
                shutil.rmtree(stage)


def _verified_packet(path: Path, rows: list[dict]) -> tuple[Path, dict]:
    packet = path / 'review-packet'
    manifest = read_json(packet / 'manifest.json')
    provenance = read_json(packet / 'provenance.json')
    for name in ('packet.json', 'provenance.json'):
        if manifest.get('members', {}).get(name) != sha256(packet / name):
            raise HarmError('challenge_packet_changed')
    if (provenance.get('intake_sha256') != sha256(path / 'intake.jsonl')
        or provenance.get('packet_sha256') != sha256(packet / 'packet.json')
        or canonical_sha256(read_json(packet / 'packet.json', max_bytes=MAX_INTAKE_BYTES)) != canonical_sha256(_packet(rows))):
        raise HarmError('challenge_intake_or_packet_changed')
    return packet, provenance


def _review(path: Path, ids: set[str], packet_hash: str) -> tuple[dict, str]:
    if path.stat().st_size > MAX_INTAKE_BYTES:
        raise HarmError('challenge_review_oversized')
    try:
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != REVIEW_FIELDS:
                raise HarmError('challenge_review_fields_invalid')
            rows = list(reader)
        answers = {}; reviewers = set()
        for row in rows:
            if (set(row) != set(REVIEW_FIELDS) or any(v is None for v in row.values())
                or row['case_id'] not in ids or row['case_id'] in answers
                or row['packet_sha256'] != packet_hash or not row['reviewer_id'].strip()
                or row['task_label'] not in ('0', '1', 'uncertain') or row['family'] not in FAMILIES
                or not row['rationale'].strip()):
                raise HarmError('challenge_review_invalid')
            reviewers.add(row['reviewer_id'].strip().casefold()); answers[row['case_id']] = row
        if set(answers) != ids or len(reviewers) != 1:
            raise HarmError('challenge_review_incomplete')
        return answers, next(iter(reviewers))
    except (csv.Error, UnicodeError) as error:
        raise HarmError('challenge_review_invalid') from error


def finalize_challenge_reviews(root: Path) -> dict:
    path = Path(root).resolve() / 'challenge'
    with cache_lock(path / 'workflow.lock'):
        if (path / 'final').exists() or (path / 'reservation.json').exists():
            raise HarmError('challenge_final_or_reservation_exists')
        rows = _intake(path)
        if not rows:
            raise HarmError('challenge_empty_pending')
        packet, provenance = _verified_packet(path, rows)
        ids = {row['case_id'] for row in rows}; digest = provenance['packet_sha256']
        left, reviewer_a = _review(packet / 'reviewer-a.csv', ids, digest)
        right, reviewer_b = _review(packet / 'reviewer-b.csv', ids, digest)
        if reviewer_a == reviewer_b:
            raise HarmError('challenge_reviews_not_independent')
        adjudication = read_json(packet / 'adjudication.json') if (packet / 'adjudication.json').exists() else {}
        if set(adjudication) - ids:
            raise HarmError('challenge_adjudication_unknown_case')
        decisions = []; adjudicated = 0
        for row in rows:
            identity = row['case_id']; a = left[identity]; b = right[identity]
            decision = a
            if a['task_label'] != b['task_label'] or a['family'] != b['family']:
                decision = adjudication.get(identity, {})
                if (set(decision) != {'reviewer_id', 'task_label', 'family', 'rationale'}
                    or not isinstance(decision.get('reviewer_id'), str)
                    or not decision['reviewer_id'].strip()
                    or decision['reviewer_id'].strip().casefold() in (reviewer_a, reviewer_b)
                    or decision.get('task_label') not in ('0', '1', 'uncertain')
                    or decision.get('family') not in FAMILIES or not decision.get('rationale', '').strip()):
                    raise HarmError('challenge_disagreement_needs_adjudication')
                adjudicated += 1
            decisions.append({'case_id': identity, 'label': None if decision['task_label'] == 'uncertain'
                else int(decision['task_label']), 'family': decision['family'],
                'adjudicated': decision is not a})
        members = {name: sha256(packet / name) for name in ('packet.json','provenance.json',
            'reviewer-a.csv','reviewer-b.csv','manifest.json')}
        if (packet / 'adjudication.json').exists():
            members['adjudication.json'] = sha256(packet / 'adjudication.json')
        record = {'schema_version': 1, 'intake_sha256': sha256(path / 'intake.jsonl'),
            'review_hashes': members, 'case_count': len(rows),
            'labelled_count': sum(r['label'] is not None for r in decisions),
            'uncertain_count': sum(r['label'] is None for r in decisions), 'adjudicated_count': adjudicated}
        stage = Path(tempfile.mkdtemp(prefix='.final-stage-', dir=path))
        try:
            write_json(stage / 'decisions.json', {'cases': decisions})
            write_json(stage / 'record.json', record)
            publish_stage(stage, path / 'final', {name: sha256(stage / name) for name in ('decisions.json','record.json')})
        finally:
            if stage.exists() and stage.resolve().parent == path:
                shutil.rmtree(stage)
        return record


def _final_record(path: Path) -> dict:
    final = path / 'final'; manifest = read_json(final / 'manifest.json')
    if set(manifest.get('members', {})) != {'decisions.json', 'record.json'}:
        raise HarmError('challenge_final_invalid')
    for name, digest in manifest['members'].items():
        if sha256(final / name) != digest:
            raise HarmError('challenge_final_changed')
    record = read_json(final / 'record.json')
    if record.get('intake_sha256') != sha256(path / 'intake.jsonl'):
        raise HarmError('challenge_intake_changed')
    for name, digest in record['review_hashes'].items():
        if name not in ('packet.json','provenance.json','reviewer-a.csv','reviewer-b.csv','manifest.json','adjudication.json'):
            raise HarmError('challenge_review_member_invalid')
        if sha256(path / 'review-packet' / name) != digest:
            raise HarmError('challenge_review_changed')
    return record


def challenge_reservation(root: Path) -> dict:
    path = Path(root).resolve() / 'challenge'
    if not path.exists():
        raise HarmError('challenge_initialization_required')
    with cache_lock(path / 'workflow.lock'):
        rows = _intake(path)
        final = _final_record(path) if rows else None
        from .conversation import parse_submission
        from .text import duplicate_keys
        ownership = []
        for row in rows:
            submission = parse_submission({k: row[k] for k in ('conversation_kind','conversation_turns','target_turn_id')})
            ownership.append({'case_id': row['case_id'], 'source_ref': row['source_ref'],
                'keys': duplicate_keys(submission.model_input)})
        record = {'schema_version': 1, 'case_count': len(rows),
            'status': 'reserved' if rows else 'pending', 'intake_sha256': sha256(path / 'intake.jsonl'),
            'final_manifest_sha256': sha256(path/'final/manifest.json') if final else None,
            'cad_case_ids': sorted({row['source_ref'][len('cad-v1.1:'):] for row in rows
                if row['source_ref'].startswith('cad-v1.1:')}),
            'duplicate_keys': ownership, 'case_ids': [row['case_id'] for row in rows]}
        # Normalize tuples into the same JSON representation on the first and resumed call.
        record = json.loads(json.dumps(record, allow_nan=False))
        output = path / 'reservation.json'
        if output.exists():
            existing = read_json(output, max_bytes=MAX_INTAKE_BYTES)
            if existing != record:
                raise HarmError('challenge_reserved_inputs_changed')
            return existing
        write_json(output, record, exclusive=True)
        return record


def audit_challenge(root: Path) -> dict:
    path = Path(root).resolve() / 'challenge'
    intake = path / 'intake.jsonl'
    if not intake.exists():
        return {'status': 'not_initialized', 'case_count': 0, 'claim_ready': False}
    if not intake.read_text(encoding='utf-8').strip():
        return {'status': 'pending', 'case_count': 0, 'labelled_count': 0,
                'claim_ready': False, 'reserved': (path/'reservation.json').exists()}
    rows = _intake(path)
    if not (path / 'final').exists():
        return {'status': 'pending', 'case_count': len(rows), 'labelled_count': 0, 'claim_ready': False}
    record = _final_record(path)
    decisions = read_json(path/'final/decisions.json')['cases']
    return {'status': 'adjudicated', 'case_count': len(rows),
        'labelled_count': record['labelled_count'], 'uncertain_count': record['uncertain_count'],
        'adjudicated_count': record['adjudicated_count'],
        'families': dict(Counter(r['family'] for r in decisions)),
        'claim_ready': record['labelled_count'] > 0, 'reserved': (path/'reservation.json').exists()}
