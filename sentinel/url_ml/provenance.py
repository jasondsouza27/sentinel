"""Explicit, stdlib-only digest meanings for legacy and multi-source research."""
import re
from .contracts import DatasetError
from .splits import manifest_hash

def validate_provenance(value,*,stage):
    if stage not in ("development","artifact") or not isinstance(value,dict): raise DatasetError("provenance_contract_invalid")
    schema=value.get("provenance_schema")
    if schema is None:
        if "source_catalog_sha256" in value or "protocol_sha256" in value: raise DatasetError("provenance_schema_required")
        fields=["source_sha256","psl_sha256","derived_sha256","dataset_manifest_sha256"]
        if stage=="artifact": fields.append("split_manifest_sha256")
    elif schema in ("url-provenance-v2","url-provenance-v3"):
        if "source_sha256" in value: raise DatasetError("v2_single_source_digest_forbidden" if schema=="url-provenance-v2" else "v3_single_source_digest_forbidden")
        fields=["source_catalog_sha256","dataset_manifest_sha256","derived_sha256","psl_sha256","parser_code_sha256","protocol_sha256"]
        if schema=="url-provenance-v3": fields += ["config_sha256","parent_v2_protocol_sha256","protected_domains_sha256"]
        if type(value.get("seed")) is not int or value["seed"]!=42: raise DatasetError("v2_seed_invalid")
        if stage=="artifact":
            fields += ["split_manifest_sha256","training_config_sha256","calibration_ids_sha256"]
            if not isinstance(value.get("training_config"),dict) or manifest_hash(value["training_config"])!=value.get("training_config_sha256"): raise DatasetError("v2_training_config_digest_mismatch")
    else: raise DatasetError("provenance_schema_unsupported")
    if any(not isinstance(value.get(field),str) or not re.fullmatch("[0-9a-f]{64}",value[field]) for field in fields): raise DatasetError("provenance_digest_invalid")
