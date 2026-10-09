"""Verified historical input binding; validation writes only in the new study."""
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2 import audit as legacy_audit
from sentinel.url_v2 import protocol as legacy_protocol
from sentinel.url_v2.catalog import load_catalog,merge_catalogs
from sentinel.url_v2.contracts import Observation,default_config as v2_config
from sentinel.url_v2.projection import iter_phresh_observations
from sentinel.url_v2.storage import manifest_hash,publish_jsonl_directory,read_json,verify_files
from .contracts import V2Binding

BINDING_SCHEMA="url-v2-binding-v3"

def _fingerprint(observations):
    count=0; total=0
    for observation in observations:
        count+=1
        total=(total+int(manifest_hash(asdict(observation)),16)) % (1<<256)
    return count,format(total,"064x")

def _history(v2_root, config, parser, scratch_root):
    root=Path(v2_root).resolve()
    if parser.psl_sha256!=config["parser"]["psl_sha256"]:
        raise DatasetError("binding_psl_mismatch")
    primary=load_catalog(root/"sources/phreshphish/catalog")
    pin=config["sources"]["phreshphish"]
    if len(primary.sources)!=1 or any(primary.sources[0].get(k)!=pin[k] for k in ("source_id","revision","label_map","date_semantics")):
        raise DatasetError("binding_source_mismatch")
    if not primary.files or any(f.source_id!=pin["source_id"] or f.revision!=pin["revision"] for f in primary.files):
        raise DatasetError("binding_source_files_invalid")
    previous=v2_config(); previous["parser"]=dict(config["parser"])
    projection_root=root/"sources/phreshphish/projection"
    projected=read_json(projection_root/"manifest.json")
    if projected.get("purpose")!="full" or projected.get("projected_columns")!=["url","label","date","sha256"] or projected.get("config_sha256")!=manifest_hash(previous):
        raise DatasetError("binding_projection_contract_invalid")
    file_by_path={f.path:f for f in primary.files}; counts=Counter(); seen=set()
    def original():
        for obs in iter_phresh_observations(projection_root,primary):
            ref=obs.reference
            if not isinstance(ref,dict) or set(ref)!={"shard","row"} or ref.get("shard") not in file_by_path or type(ref.get("row")) is not int or ref["row"]<1:
                raise DatasetError("binding_projection_reference_invalid")
            file=file_by_path[ref["shard"]]
            if obs.source_id!=file.source_id or obs.revision!=file.revision or obs.original_partition!=file.original_partition:
                raise DatasetError("binding_projection_source_invalid")
            if obs.observation_id in seen: raise DatasetError("binding_duplicate_observation")
            seen.add(obs.observation_id); counts[file.path]+=1
            if ref["row"]!=counts[file.path]: raise DatasetError("binding_projection_ordinal_invalid")
            yield obs
    projected_fingerprint=_fingerprint(original())
    if counts!=Counter({s["path"]:s["rows"] for s in projected["shards"]}):
        raise DatasetError("binding_projection_counts_mismatch")
    joint=merge_catalogs(primary,None)
    audit=legacy_audit.load_audit(root/"audited",joint,parser,scratch_root=scratch_root)
    fields=Observation.__dataclass_fields__
    audited_fingerprint=_fingerprint(Observation(**{k:v[k] for k in fields}) for v in legacy_audit.iter_provenance(audit))
    if audited_fingerprint!=projected_fingerprint:
        raise DatasetError("binding_projection_audit_mismatch")
    frozen=legacy_protocol.load_protocol(audit,joint,root/"protocol",previous)
    owners=[]; reserved=set()
    with (frozen.root/"owners.jsonl").open(encoding="utf-8") as f:
        for line in f:
            value=json.loads(line)
            if value["track"]=="primary":
                reserved.add(value["component_id"])
                owners.append({"case_id":value["case_id"],"owner_observation_ids":value["owner_observation_ids"]})
    primary_owners={v["case_id"]:tuple(v["owner_observation_ids"]) for v in owners}
    if set(primary_owners)!={r.case_id for r in frozen.tracks["primary"]}:
        raise DatasetError("binding_primary_owners_invalid")
    anchors=set()
    for record in legacy_audit.iter_records(audit):
        if frozen.component_by_case[record.row.case_id] in reserved: anchors.add(record.row.domain_group)
    required=[frozen.manifest["development"]]+[frozen.manifest["tracks"][n] for n in ("train","validation","calibration","primary")]
    manifest={"schema":BINDING_SCHEMA,"v2_root":str(root),
      "source_catalog_sha256":manifest_hash(primary.manifest),
      "projection_manifest_sha256":manifest_hash(projected),
      "audit_manifest_sha256":manifest_hash(audit.manifest),
      "parent_v2_protocol_sha256":manifest_hash(frozen.manifest),
      "parser_code_sha256":audit.manifest["parser_code_sha256"],"psl_sha256":parser.psl_sha256,
      "protected_domain_groups":len(anchors),"original_primary_cases":len(primary_owners),
      "historical_training_ready":all(v["status"]=="available" for v in required),
      "legacy_transfer_metering":"unknown_actual_total"}
    sidecars={"anchors.jsonl":[{"domain_group":d} for d in sorted(anchors)],
              "primary-owners.jsonl":sorted(owners,key=lambda v:v["case_id"])}
    return primary,tuple(sorted(anchors)),primary_owners,manifest,sidecars

def _sidecar_hash(values):
    return hashlib.sha256("".join(json.dumps(v,sort_keys=True,ensure_ascii=True,allow_nan=False)+"\n" for v in values).encode()).hexdigest()

def bind_v2(v2_root: Path, output_dir: Path, config: dict, parser) -> V2Binding:
    output=Path(output_dir).resolve(); original=Path(v2_root).resolve()
    if output.is_relative_to(original) or original.is_relative_to(output):
        raise DatasetError("v2_input_read_only")
    primary,anchors,owners,manifest,sidecars=_history(original,config,parser,output.parent)
    manifest["protected_domains_sha256"]=_sidecar_hash(sidecars["anchors.jsonl"])
    actual=publish_jsonl_directory(output,sidecars,manifest)
    return V2Binding(output,original,primary,anchors,owners,actual)

def load_v2_binding(root: Path, config: dict, parser) -> V2Binding:
    root=Path(root).resolve(); actual=read_json(root/"manifest.json")
    if actual.get("schema")!=BINDING_SCHEMA: raise DatasetError("binding_schema_invalid")
    verify_files(root,actual.get("files"))
    if not isinstance(actual.get("v2_root"),str): raise DatasetError("binding_root_invalid")
    original=Path(actual["v2_root"]).resolve()
    if root.is_relative_to(original) or original.is_relative_to(root):
        raise DatasetError("v2_input_read_only")
    primary,anchors,owners,expected,sidecars=_history(original,config,parser,root.parent)
    expected["protected_domains_sha256"]=_sidecar_hash(sidecars["anchors.jsonl"])
    expected["files"]={name:_sidecar_hash(values) for name,values in sidecars.items()}
    if actual!=expected: raise DatasetError("binding_identity_mismatch")
    return V2Binding(root,original,primary,anchors,owners,actual)
