"""Deterministic protected cohorts, source ownership and mandatory coverage gates."""
import hashlib
import json
import re
from collections import Counter,defaultdict
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError,SplitBundle
from sentinel.url_v2.audit import iter_records,iter_provenance
from sentinel.url_v2.protocol import Union,choose_components,_allocation,_support
from sentinel.url_v2.storage import manifest_hash,publish_jsonl_directory,read_json,verify_files
from .contracts import (V3Splits,PROTOCOL_SCHEMA,PROVENANCE_SCHEMA,DEVELOPMENT_SCHEMA,
                        DEVELOPMENT_NAMES,FINAL_NAMES,MENDELEY_ID)

NAMES=(*DEVELOPMENT_NAMES,*FINAL_NAMES)

def supplemental_reserved(component_id):
    if not isinstance(component_id,str) or not re.fullmatch("[0-9a-f]{64}",component_id):
        raise DatasetError("v3_component_identity_invalid")
    digest=hashlib.sha256(b"url-v3-mendeley-final|42|"+component_id.encode("ascii")).digest()
    return int.from_bytes(digest[:8],"big")<2**63

def select_development(groups,mandatory,cap,seed):
    mandatory=set(mandatory)
    if not mandatory<=set(groups): raise DatasetError("mandatory_component_missing")
    count=sum(len(groups[c]) for c in mandatory)
    if count>cap: raise DatasetError("mandatory_development_components_exceed_cap",
                                     {"mandatory_rows":count,"development_max_rows":cap})
    optional={c:keys for c,keys in groups.items() if c not in mandatory}
    chosen,skips=choose_components(optional,cap-count,seed)
    return sorted(mandatory)+chosen,skips

def track_support(rows,components,config,*,training=False,formats=False):
    return _support(rows,components,config,training=training,formats=formats)

def _connected(records,audit):
    union=Union(records); domains={}; opaque={}; observations=defaultdict(list)
    for key,record in records.items():
        domain=record.row.domain_group
        if domain in domains: union.connect(key,domains[domain])
        else: domains[domain]=key
    for value in iter_provenance(audit):
        if value["reason"]: continue
        key=value["canonical_case_id"]
        if key not in records or value["observation_id"] not in records[key].observation_ids:
            raise DatasetError("v3_protocol_provenance_incomplete")
        observations[key].append({k:value[k] for k in
                                  ("observation_id","source_id","original_partition","opaque_id")})
        if value["opaque_id"]:
            identity=(value["source_id"],value["opaque_id"])
            if identity in opaque: union.connect(key,opaque[identity])
            else: opaque[identity]=key
    if any({o["observation_id"] for o in observations[k]}!=set(r.observation_ids) for k,r in records.items()):
        raise DatasetError("v3_protocol_provenance_incomplete")
    groups=defaultdict(list)
    for key in sorted(records): groups[union.find(key)].append(key)
    component_cases={manifest_hash({"case_ids":keys}):keys for keys in groups.values()}
    components={key:c for c,keys in component_cases.items() for key in keys}
    return component_cases,components,observations

def _assemble(audit,catalog,binding,config):
    if (read_json(audit.root/"manifest.json")!=audit.manifest or
        audit.manifest["source_catalog_sha256"]!=manifest_hash(catalog.manifest) or
        audit.manifest["psl_sha256"]!=config["parser"]["psl_sha256"] or
        catalog.manifest.get("parent_v2_protocol_sha256")!=binding.manifest["parent_v2_protocol_sha256"] or
        catalog.manifest.get("protected_domains_sha256")!=binding.manifest["protected_domains_sha256"]):
        raise DatasetError("v3_protocol_input_identity_mismatch")
    verify_files(audit.root,audit.manifest["files"])
    records={r.row.case_id:r for r in iter_records(audit)}
    component_cases,components,observations=_connected(records,audit)
    anchors=set(binding.anchor_domains); candidates={}; eligible_owners={}; dropped={}; reservations={}; dev_groups={}
    mandatory=set()
    for component,keys in sorted(component_cases.items()):
        has_mendeley=any(o["source_id"]==MENDELEY_ID for key in keys for o in observations[key])
        primary=any(records[key].row.domain_group in anchors for key in keys)
        track="primary" if primary else "supplemental" if has_mendeley and supplemental_reserved(component) else "development"
        reservations[component]=track
        for key in keys:
            def owns(o):
                if track=="primary":
                    return (o["source_id"]=="phreshphish" and o["original_partition"]=="test" and
                            o["observation_id"] in binding.primary_owners.get(key,()))
                if track=="supplemental": return o["source_id"]==MENDELEY_ID
                return (key not in binding.primary_owners and
                        (o["source_id"]==MENDELEY_ID or (o["source_id"]=="phreshphish" and o["original_partition"]=="train")))
            owned=sorted((o for o in observations[key] if owns(o)),key=lambda o:o["observation_id"])
            eligible_owners[key]=owned
            if owned:
                candidates[key]=track
                if track=="development":
                    dev_groups.setdefault(component,[]).append(key)
                    if has_mendeley: mandatory.add(component)
            else:
                dropped[key]="heldout_component_overlap" if track=="primary" else "supplemental_component_overlap" if track=="supplemental" else "no_eligible_owner"
    chosen,skips=select_development(dev_groups,mandatory,config["split"]["development_max_rows"],config["split"]["seed"])
    allocation=_allocation({c:dev_groups[c] for c in chosen},records,config)
    assignments={name:[] for name in NAMES}; owners=[]; pruning=[]; sources={}
    for key in sorted(records):
        component=components[key]; track=candidates.get(key)
        if track=="development":
            track=allocation.get(component)
            if track is None: dropped[key]="development_cap"
        if track is not None: assignments[track].append(key)
        owned=eligible_owners[key] if track is not None else []
        owned_ids={o["observation_id"] for o in owned}
        sources[key]=tuple(sorted({o["source_id"] for o in owned}))
        owners.append({"case_id":key,"component_id":component,"track":track,
                       "owner_observation_ids":[o["observation_id"] for o in owned],"source_ids":list(sources[key])})
        for obs in observations[key]:
            if obs["observation_id"] not in owned_ids:
                pruning.append({"case_id":key,"observation_id":obs["observation_id"],
                                "reason":dropped.get(key,reservations[component]+"_ownership_priority")})
    parts={name:tuple(records[k].row for k in assignments[name]) for name in NAMES}
    tracks={name:track_support(parts[name],components,config,training=name=="train",
                              formats=name in ("train","primary","supplemental")) for name in NAMES}
    development=tuple(row for name in DEVELOPMENT_NAMES for row in parts[name])
    development_report=track_support(development,components,config,training=True,formats=True)
    source_config={**config,"support":{**config["support"],
                      "other_min_rows_per_class":config["support"]["source_min_rows_per_class"],
                      "other_min_groups_per_class":config["support"]["source_min_groups_per_class"]}}
    source_ids=("phreshphish",MENDELEY_ID)
    source_development={source:track_support(tuple(r for r in development if source in sources[r.case_id]),
                                            components,source_config) for source in source_ids}
    source_partitions={name:{source:track_support(tuple(r for r in parts[name] if source in sources[r.case_id]),
                                                 components,source_config) for source in source_ids} for name in NAMES}
    removed=[{"case_id":key,"reason":"absent_after_joint_audit" if key not in records else "original_primary_owner_unavailable"}
             for key in sorted(set(binding.primary_owners)-set(assignments["primary"]))]
    total=len(development)
    ready=all(report["status"]=="available" for report in (*tracks.values(),development_report,*source_development.values()))
    manifest={"schema":PROTOCOL_SCHEMA,"source_catalog_sha256":manifest_hash(catalog.manifest),
              "audit_manifest_sha256":manifest_hash(audit.manifest),"config_sha256":manifest_hash(config),
              "parser_code_sha256":audit.manifest["parser_code_sha256"],"psl_sha256":audit.manifest["psl_sha256"],
              "parent_v2_protocol_sha256":binding.manifest["parent_v2_protocol_sha256"],
              "protected_domains_sha256":binding.manifest["protected_domains_sha256"],
              "parent_source_catalog_sha256":binding.manifest["source_catalog_sha256"],
              "parent_projection_manifest_sha256":binding.manifest["projection_manifest_sha256"],
              "parent_audit_manifest_sha256":binding.manifest["audit_manifest_sha256"],
              "parent_primary_owners_sha256":binding.manifest["files"]["primary-owners.jsonl"],
              "seed":config["split"]["seed"],"fractions":config["split"]["fractions"],
              "development_max_rows":config["split"]["development_max_rows"],
              "protected_domain_groups":len(anchors),"original_primary_cases":len(binding.primary_owners),
              "original_primary_removed":len(removed),
              "supplemental_reservation":{"prefix":"url-v3-mendeley-final|42|","first_bytes":8,"byte_order":"big","boundary":2**63},
              "tracks":tracks,"development":development_report,"source_development":source_development,
              "source_partitions":source_partitions,"training_ready":ready,
              "temporal":{"status":"unavailable","reason":"missing_or_unauthenticated_collection_dates"},
              "observed_development_fractions":{name:len(parts[name])/total if total else None for name in DEVELOPMENT_NAMES},
              "mandatory_development_components":len(mandatory),
              "mandatory_development_rows":sum(len(dev_groups[c]) for c in mandatory),
              "development_eligible_rows":sum(len(keys) for keys in dev_groups.values()),
              "cap_skipped_components":dict(sorted(skips.items())),
              "exclusions":dict(sorted(Counter(dropped.values()).items())),
              "pruned_observations":dict(sorted(Counter(p["reason"] for p in pruning).items())),
              "limitations":["Supplemental is group-held-out from a source also used in development.",
                             "Neither final cohort establishes source independence or temporal generalization.",
                             "Source annotations are historical; v1 and v2 scores are not headline comparators."]}
    sidecars={"assignments.json":[assignments],
              "components.jsonl":[{"component_id":c,"case_ids":keys,"reservation":reservations[c]} for c,keys in sorted(component_cases.items())],
              "owners.jsonl":owners,"pruning.jsonl":sorted(pruning,key=lambda p:p["observation_id"]),
              "exclusions.jsonl":[{"case_id":key,"reason":reason} for key,reason in sorted(dropped.items())],
              "primary-removals.jsonl":removed}
    return parts,components,sources,manifest,sidecars

def _bundle(parts,components,sources,manifest,audit,root,study_root):
    provenance={"provenance_schema":PROVENANCE_SCHEMA,
                "source_catalog_sha256":manifest["source_catalog_sha256"],
                "dataset_manifest_sha256":manifest["audit_manifest_sha256"],
                "derived_sha256":audit.manifest["files"]["rows.jsonl"],
                "parser_code_sha256":manifest["parser_code_sha256"],"psl_sha256":manifest["psl_sha256"],
                "protocol_sha256":manifest_hash(manifest),"config_sha256":manifest["config_sha256"],
                "parent_v2_protocol_sha256":manifest["parent_v2_protocol_sha256"],
                "protected_domains_sha256":manifest["protected_domains_sha256"],"seed":manifest["seed"]}
    development=SplitBundle({name:parts[name] for name in DEVELOPMENT_NAMES},
                             {"schema":DEVELOPMENT_SCHEMA,"provenance":provenance,
                              "partitions":{name:manifest["tracks"][name] for name in DEVELOPMENT_NAMES}})
    return V3Splits(development,{name:parts[name] for name in FINAL_NAMES},components,sources,manifest,
                    Path(root).resolve(),audit.root.resolve(),Path(study_root).resolve())

def freeze_protocol(audit,catalog,binding,config,output_dir,*,study_root):
    parts,components,sources,manifest,sidecars=_assemble(audit,catalog,binding,config)
    manifest=publish_jsonl_directory(Path(output_dir),sidecars,manifest)
    return _bundle(parts,components,sources,manifest,audit,output_dir,study_root)

def load_protocol(audit,catalog,binding,root,config,*,study_root):
    root=Path(root); actual=read_json(root/"manifest.json")
    if actual.get("schema")!=PROTOCOL_SCHEMA: raise DatasetError("v3_protocol_schema_unsupported")
    verify_files(root,actual.get("files"))
    parts,components,sources,expected,sidecars=_assemble(audit,catalog,binding,config)
    if set(actual["files"])!=set(sidecars) or any(actual.get(k)!=v for k,v in expected.items()):
        raise DatasetError("v3_protocol_identity_or_counts_mismatch")
    for name,values in sidecars.items():
        digest=hashlib.sha256()
        for value in values: digest.update((json.dumps(value,sort_keys=True,ensure_ascii=True,allow_nan=False)+"\n").encode())
        if digest.hexdigest()!=actual["files"][name]: raise DatasetError("v3_protocol_semantic_integrity_failed")
    return _bundle(parts,components,sources,actual,audit,root,study_root)

def assert_training_ready(splits):
    m=splits.manifest
    if (m.get("schema")!=PROTOCOL_SCHEMA or m.get("training_ready") is not True or
        set(m.get("tracks",{}))!=set(NAMES) or
        any(report["status"]!="available" for report in
            (m["development"],*m["tracks"].values(),*m["source_development"].values()))):
        raise DatasetError("v3_training_support_incomplete",
                           {"development":m.get("development"),"tracks":m.get("tracks"),
                            "source_development":m.get("source_development")})
