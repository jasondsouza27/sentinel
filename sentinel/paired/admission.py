"""Bind human reviews to a checked, private evidence ledger."""

import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

from sentinel import curation

from .contracts import EVIDENCE_FIELDS, PACKET_FIELDS

_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")
_OPAQUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_TYPES = {"official_confirmation", "independent_threat_report", "source_record", "consent_record"}


def _json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _publish(stage, root, names):
    """Preflight collisions and roll back this stage if a copy fails."""
    targets = [root / name for name in names]
    curation._check_new(targets)
    published = []
    try:
        for name, target in zip(names, targets):
            shutil.copyfile(stage / name, target)
            published.append(target)
    except Exception:
        for target in published:
            target.unlink()
        raise


def validate_ledger(root: Path, intake: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    root = Path(root)
    rows = curation._read_csv(root / "evidence_ledger.csv", EVIDENCE_FIELDS)
    ids = [row["case_id"] for row in rows]
    expected = {row["case_id"] for row in intake}
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("evidence_ledger.csv case_id values must match intake.csv one-to-one")
    if len({row["evidence_id"] for row in rows}) != len(rows):
        raise ValueError("evidence_id values must be unique")
    by_id = {row["case_id"]: row for row in rows}
    for case in intake:
        row = by_id[case["case_id"]]
        case_id = case["case_id"]
        for field in ("evidence_id", "verification_ref"):
            if not _OPAQUE.fullmatch(row[field].strip()):
                raise ValueError(f"{case_id}: {field} must be an opaque pointer")
        if row["evidence_type"].strip() not in _TYPES:
            raise ValueError(f"{case_id}: unsupported evidence_type")
        observed = row["observed_on"].strip()
        if observed:
            try:
                parsed = date.fromisoformat(observed)
            except ValueError as error:
                raise ValueError(f"{case_id}: observed_on must be YYYY-MM-DD") from error
            if parsed.isoformat() != observed:
                raise ValueError(f"{case_id}: observed_on must be YYYY-MM-DD")
        source_hash = row["source_sha256"].strip()
        if source_hash and not _HASH.fullmatch(source_hash):
            raise ValueError(f"{case_id}: source_sha256 must be a SHA-256 digest")
        if row["permission_basis"].strip() != case["collection_basis"].strip():
            raise ValueError(f"{case_id}: permission_basis must equal collection_basis")
        if case["collection_basis"].strip() == "licensed_public" and (not source_hash or not row["source_version"].strip()):
            raise ValueError(f"{case_id}: licensed_public requires source_sha256 and source_version")
        if row["redaction_decision"].strip() not in {"redacted", "none_needed"}:
            raise ValueError(f"{case_id}: redaction_decision must be redacted or none_needed")
    return by_id


def prepare_study_reviews(root: Path) -> dict:
    root = Path(root)
    intake = curation._intake(root)
    ledger = validate_ledger(root, intake)
    names = ("case_packet.csv", "reviewer_a.csv", "reviewer_b.csv", "adjudication.csv",
             "review_manifest.json", "study_review_manifest.json")
    curation._check_new([root / name for name in names])
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        shutil.copyfile(root / "intake.csv", stage / "intake.csv")
        curation.prepare_reviews(stage)
        packet = [
            {**{field: row[field] for field in ("case_id", "message", "url")},
             **{field: ledger[row["case_id"]][field] for field in PACKET_FIELDS[3:]}}
            for row in intake
        ]
        curation._write_csv(stage / "case_packet.csv", PACKET_FIELDS, packet)
        manifest = {
            "schema_version": 1, "cases": len(intake),
            "intake_sha256": curation._sha256(root / "intake.csv"),
            "evidence_ledger_sha256": curation._sha256(root / "evidence_ledger.csv"),
            "case_packet_sha256": curation._sha256(stage / "case_packet.csv"),
            "review_manifest_sha256": curation._sha256(stage / "review_manifest.json"),
        }
        _json(stage / "study_review_manifest.json", manifest)
        _publish(stage, root, names)
    return {"cases": len(intake), "status": "pending_review"}


def _check_prepared(root):
    manifest = json.loads((root / "study_review_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported study_review_manifest.json schema")
    for name in ("intake", "evidence_ledger", "case_packet", "review_manifest"):
        filename = f"{name}.json" if name.endswith("manifest") else f"{name}.csv"
        if manifest.get(f"{name}_sha256") != curation._sha256(root / filename):
            raise ValueError(f"{filename} changed after preparation")
    intake = curation._intake(root)
    validate_ledger(root, intake)
    packet = curation._read_csv(root / "case_packet.csv", PACKET_FIELDS)
    if len(packet) != len(intake) or [r["case_id"] for r in packet] != [r["case_id"] for r in intake]:
        raise ValueError("case_packet.csv does not match intake.csv")
    return manifest


def finalize_study_reviews(root: Path) -> dict:
    root = Path(root)
    _check_prepared(root)
    names = ("final_pairs.csv", "final_audit.json", "study_final_manifest.json")
    curation._check_new([root / name for name in names])
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        for name in ("intake.csv", "reviewer_a.csv", "reviewer_b.csv", "adjudication.csv", "review_manifest.json"):
            shutil.copyfile(root / name, stage / name)
        audit = curation.finalize_reviews(stage)
        final = {"schema_version": 1}
        for name in ("intake.csv", "evidence_ledger.csv", "case_packet.csv", "review_manifest.json",
                     "study_review_manifest.json", "reviewer_a.csv", "reviewer_b.csv", "adjudication.csv"):
            final[name + "_sha256"] = curation._sha256(root / name)
        for name in ("final_pairs.csv", "final_audit.json"):
            final[name + "_sha256"] = curation._sha256(stage / name)
        _json(stage / "study_final_manifest.json", final)
        _publish(stage, root, names)
    return audit


def verify_finalized_study(root: Path) -> dict:
    root = Path(root)
    _check_prepared(root)
    manifest = json.loads((root / "study_final_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported study_final_manifest.json schema")
    for key, expected in manifest.items():
        if not key.endswith("_sha256"):
            continue
        name = key[:-7]
        if curation._sha256(root / name) != expected:
            raise ValueError(f"{name} changed after finalization")
    return curation._verify_finalized(root)
