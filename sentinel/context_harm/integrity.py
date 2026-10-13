"""Canonical identities and checked, exclusive local stage publication."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .contracts import HarmError


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as error:
        raise HarmError('invalid_canonical_json') from error


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    base = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise HarmError('path_outside_stage')
    path = (base / rel).resolve()
    if not path.is_relative_to(base) or path == base:
        raise HarmError('path_outside_stage')
    return path


def read_json(path: Path, *, max_bytes: int = 1024 * 1024) -> dict:
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise HarmError('metadata_oversized')
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise HarmError('metadata_not_object')
        return value
    except (OSError, UnicodeError, ValueError) as error:
        if isinstance(error, HarmError):
            raise
        raise HarmError('metadata_unavailable_or_invalid') from error


def write_json(path: Path, value: object, *, exclusive: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / ('.pending-' + uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(canonical_bytes(value) + b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish_stage(stage: Path, output: Path, members: dict[str, str]) -> dict:
    stage = Path(stage).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('stage already exists')
    if stage.parent != output.parent or not stage.is_dir() or not members:
        raise HarmError('stage_location_invalid')
    actual = {p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file()}
    if actual != set(members) or 'manifest.json' in members:
        raise HarmError('stage_members_invalid')
    for name, digest in members.items():
        if sha256(safe_path(stage, name)) != digest:
            raise HarmError('stage_member_hash_mismatch')
    manifest = {'schema_version': 1, 'members': dict(sorted(members.items()))}
    write_json(stage / 'manifest.json', manifest, exclusive=True)
    # Windows directory rename refuses an existing destination; callers also
    # own a stage lock. No completed output is silently replaced.
    os.rename(stage, output)
    return {**manifest, 'manifest_sha256': canonical_sha256(manifest)}
