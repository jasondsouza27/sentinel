"""Validated development-only envelope accepted by the legacy trainer."""
from sentinel.url_ml.contracts import DatasetError,SplitBundle
from sentinel.url_ml.provenance import validate_provenance
from .protocol import DEVELOPMENT_SCHEMA,assert_training_ready
from .storage import manifest_hash

def development_bundle(splits):
    assert_training_ready(splits)
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
