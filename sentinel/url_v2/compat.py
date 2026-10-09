"""Validated development-only envelope accepted by the legacy trainer."""
import hashlib
import json
from sentinel.url_ml.contracts import DatasetError,SplitBundle
from .audit import iter_records
from .contracts import AuditBundle
from sentinel.url_ml.provenance import validate_provenance
from .protocol import DEVELOPMENT_SCHEMA,assert_training_ready
from .storage import manifest_hash,read_json,verify_files

def verify_frozen_splits(splits):
    if set(splits.development.partitions)!={"train","validation","calibration"} or set(splits.tracks)!={"primary","external"}:
        raise DatasetError("frozen_partitions_invalid")
    if splits.root is None or splits.audit_root is None: raise DatasetError("frozen_private_roots_required")
    protocol=read_json(splits.root/"manifest.json")
    if protocol!=splits.manifest: raise DatasetError("frozen_protocol_changed")
    verify_files(splits.root,protocol["files"])
    actual_components={}; actual_sources={}
    with (splits.root/"components.jsonl").open(encoding="utf-8") as f:
        for line in f:
            value=json.loads(line)
            if manifest_hash({"case_ids":value["case_ids"]})!=value["component_id"]: raise DatasetError("frozen_component_identity_invalid")
            for key in value["case_ids"]: actual_components[key]=value["component_id"]
    with (splits.root/"owners.jsonl").open(encoding="utf-8") as f:
        for line in f:
            value=json.loads(line); actual_sources[value["case_id"]]=tuple(value["source_ids"])
    if actual_components!=splits.component_by_case or actual_sources!=splits.sources_by_case: raise DatasetError("frozen_components_or_owners_changed")
    audit_manifest=read_json(splits.audit_root/"manifest.json")
    verify_files(splits.audit_root,audit_manifest["files"])
    if manifest_hash(audit_manifest)!=protocol["audit_manifest_sha256"]: raise DatasetError("frozen_audit_changed")
    parts={**splits.development.partitions,**splits.tracks}; assignments={name:[r.case_id for r in rows] for name,rows in parts.items()}
    encoded=(json.dumps(assignments,sort_keys=True,ensure_ascii=True,allow_nan=False)+"\n").encode()
    if hashlib.sha256(encoded).hexdigest()!=protocol["files"]["assignments.json"]: raise DatasetError("frozen_assignments_changed")
    lookup={r.case_id:r for rows in parts.values() for r in rows}; checked=set()
    for record in iter_records(AuditBundle(splits.audit_root,audit_manifest)):
        if record.row.case_id in lookup:
            if record.row!=lookup[record.row.case_id]: raise DatasetError("frozen_rows_changed")
            checked.add(record.row.case_id)
    if checked!=set(lookup): raise DatasetError("frozen_rows_missing")
    return protocol

def development_bundle(splits):
    assert_training_ready(splits)
    verify_frozen_splits(splits)
    manifest=splits.development.manifest; provenance=manifest.get("provenance",{})
    if manifest.get("schema")!=DEVELOPMENT_SCHEMA or set(splits.development.partitions)!={"train","validation","calibration"}: raise DatasetError("v2_development_envelope_invalid")
    validate_provenance(provenance,stage="development")
    if provenance["protocol_sha256"]!=manifest_hash(splits.manifest): raise DatasetError("v2_protocol_digest_mismatch")
    ownership={}; cases=set()
    for name,rows in {**splits.development.partitions,**splits.tracks}.items():
        for row in rows:
            component=splits.component_by_case.get(row.case_id)
            if component is None or row.case_id in cases or (component in ownership and ownership[component]!=name): raise DatasetError("v2_development_overlap")
            ownership[component]=name; cases.add(row.case_id)
    return SplitBundle(dict(splits.development.partitions),dict(manifest))
