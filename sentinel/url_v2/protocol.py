"""Freeze connected components, observation ownership, and research availability."""
import hashlib
import json
import random
from collections import Counter,defaultdict
from dataclasses import asdict
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError,SplitBundle
from .audit import format_flags,iter_records,iter_provenance
from .contracts import PROTOCOL_SCHEMA,PROVENANCE_SCHEMA,V2Splits
from .storage import manifest_hash,publish_jsonl_directory,read_json,verify_files

DEVELOPMENT_SCHEMA="url-development-envelope-v2"
NAMES=("train","validation","calibration","primary","external")

class Union:
    def __init__(self,keys): self.parents={key:key for key in keys}
    def find(self,key):
        while self.parents[key]!=key:
            self.parents[key]=self.parents[self.parents[key]]; key=self.parents[key]
        return key
    def connect(self,a,b):
        a=self.find(a); b=self.find(b)
        if a!=b: self.parents[max(a,b)]=min(a,b)

def choose_components(component_rows,cap,seed):
    order=sorted(component_rows); random.Random(seed).shuffle(order); used=0; selected=[]; skipped={}
    for key in order:
        size=len(component_rows[key])
        if used+size<=cap: selected.append(key); used+=size
        else: skipped[key]="development_cap"
    return selected,skipped

def _allocation(groups,rows,config):
    ratios=config["split"]["fractions"]; seed=config["split"]["seed"]
    ordered=sorted(groups); random.Random(seed).shuffle(ordered); ordered.sort(key=lambda key:-len(groups[key]))
    totals=[sum(rows[k].row.label==c for values in groups.values() for k in values) for c in (0,1)]
    targets={name:[ratio*n for n in totals] for name,ratio in ratios.items()}; counts={name:[0,0] for name in ratios}; result={}
    for key in ordered:
        addition=[sum(rows[k].row.label==c for k in groups[key]) for c in (0,1)]
        def delta(name): return sum(((counts[name][c]+addition[c]-targets[name][c])**2-(counts[name][c]-targets[name][c])**2)/max(targets[name][c],1) for c in (0,1))
        name=min(("train","validation","calibration"),key=delta); result[key]=name
        counts[name]=[counts[name][c]+addition[c] for c in (0,1)]
    return result

def _support(rows,components,config,*,training=False,formats=False):
    support=config["support"]; row_min=support["train_min_rows_per_class" if training else "other_min_rows_per_class"]
    group_min=support["train_min_groups_per_class" if training else "other_min_groups_per_class"]
    counts={str(c):sum(r.label==c for r in rows) for c in (0,1)}
    domains={str(c):len({r.domain_group for r in rows if r.label==c}) for c in (0,1)}
    groups={str(c):len({components[r.case_id] for r in rows if r.label==c}) for c in (0,1)}
    benign=[r for r in rows if r.label==0]
    format_counts={"non_root_path":sum("non_root_path" in format_flags(r.url) for r in benign),
      "non_www_host":sum("www_host" not in format_flags(r.url) for r in benign),"query_present":sum("query_present" in format_flags(r.url) for r in benign)}
    reasons=[]
    if any(counts[str(c)]<row_min or domains[str(c)]<group_min for c in (0,1)): reasons.append("missing_class_or_support")
    if formats and (format_counts["non_root_path"]<support["benign_min_non_root_path"] or format_counts["non_www_host"]<support["benign_min_non_www_host"] or format_counts["query_present"]<support["benign_min_query"]): reasons.append("benign_format_coverage_insufficient")
    return {"status":"unavailable" if reasons else "available","reasons":reasons,"rows":len(rows),"class_counts":counts,"domain_groups_per_class":domains,
      "component_groups_per_class":groups,"components":len({components[r.case_id] for r in rows}),"benign_format_counts":format_counts}

def _assemble(audit,catalog,config):
    if read_json(audit.root/"manifest.json")!=audit.manifest or audit.manifest["source_catalog_sha256"]!=manifest_hash(catalog.manifest) or audit.manifest["psl_sha256"]!=config["parser"]["psl_sha256"]: raise DatasetError("protocol_audit_identity_mismatch")
    verify_files(audit.root,audit.manifest["files"])
    records={record.row.case_id:record for record in iter_records(audit)}; union=Union(records); domain_first={}; opaque_first={}; observations=defaultdict(list)
    for key,record in records.items():
        domain=record.row.domain_group
        if domain in domain_first: union.connect(key,domain_first[domain])
        else: domain_first[domain]=key
    for value in iter_provenance(audit):
        key=value["canonical_case_id"]
        if value["reason"]: continue
        if key not in records or value["observation_id"] not in records[key].observation_ids: raise DatasetError("protocol_provenance_incomplete")
        observations[key].append({field:value[field] for field in ("observation_id","source_id","original_partition","opaque_id","date_interval","date_status")})
        if value["opaque_id"]:
            identity=(value["source_id"],value["opaque_id"])
            if identity in opaque_first: union.connect(key,opaque_first[identity])
            else: opaque_first[identity]=key
    if any({o["observation_id"] for o in observations[key]}!=set(record.observation_ids) for key,record in records.items()): raise DatasetError("protocol_provenance_incomplete")
    grouped=defaultdict(list)
    for key in sorted(records): grouped[union.find(key)].append(key)
    component_cases={manifest_hash({"case_ids":sorted(keys)}):sorted(keys) for keys in grouped.values()}
    components={key:component for component,keys in component_cases.items() for key in keys}
    candidate={}; candidate_owners={}; dropped={}; pruning=[]; dev_groups={}
    for component,keys in sorted(component_cases.items()):
        values=[o for key in keys for o in observations[key]]
        reserved=any(o["source_id"]=="phreshphish" and o["original_partition"]=="test" for o in values)
        development=any(o["source_id"]=="phreshphish" and o["original_partition"]=="train" for o in values)
        track="primary" if reserved else "development" if development else "external"
        for key in keys:
            def owns(o):
                return (o["source_id"]=="phreshphish" and o["original_partition"]==("test" if reserved else "train")) if track!="external" else o["source_id"]=="iscx-url2016"
            owners=sorted((o for o in observations[key] if owns(o)),key=lambda o:o["observation_id"])
            if owners:
                candidate[key]=track; candidate_owners[key]=owners
                if track=="development": dev_groups.setdefault(component,[]).append(key)
            else: dropped[key]="heldout_component_overlap" if reserved else "development_component_overlap" if development else "no_eligible_owner"
            owned={o["observation_id"] for o in owners}
            for o in observations[key]:
                if o["observation_id"] not in owned: pruning.append({"case_id":key,"observation_id":o["observation_id"],"reason":track+"_ownership_priority"})
    chosen,skipped=choose_components(dev_groups,config["split"]["development_max_rows"],config["split"]["seed"])
    allocation=_allocation({key:dev_groups[key] for key in chosen},records,config)
    assignments={name:[] for name in NAMES}; owners=[]; sources={}
    for key in sorted(records):
        track=candidate.get(key); component=components[key]
        if track=="development":
            track=allocation.get(component)
            if track is None: dropped[key]="development_cap"
        if track is not None: assignments[track].append(key)
        owned=candidate_owners.get(key,[]) if track is not None else []
        sources[key]=tuple(sorted({o["source_id"] for o in owned}))
        owners.append({"case_id":key,"component_id":component,"track":track,"owner_observation_ids":[o["observation_id"] for o in owned],
          "source_ids":list(sources[key]),"date_intervals":[o["date_interval"] for o in owned],"date_statuses":[o["date_status"] for o in owned]})
    parts={name:tuple(records[k].row for k in assignments[name]) for name in NAMES}
    reports={name:_support(parts[name],components,config,training=name=="train",formats=name=="primary") for name in NAMES}
    dev_rows=tuple(r for name in ("train","validation","calibration") for r in parts[name])
    dev_report=_support(dev_rows,components,config,training=True,formats=True)
    if not any(s["source_id"]=="iscx-url2016" for s in catalog.sources): reports["external"]["reasons"].append("source_access_pending"); reports["external"]["status"]="unavailable"
    dev_intervals=[interval for o in owners if o["track"] in ("train","validation","calibration") for interval in o["date_intervals"]]
    primary_intervals=[interval for o in owners if o["track"]=="primary" for interval in o["date_intervals"]]
    temporal={"status":"unavailable","reason":"missing_or_unauthenticated_collection_dates"}
    if dev_intervals and primary_intervals and all(i is not None for i in dev_intervals+primary_intervals):
        end=max(i[1] for i in dev_intervals); start=min(i[0] for i in primary_intervals)
        temporal={"status":"available" if end<start else "unavailable","reason":None if end<start else "date_intervals_overlap_or_interleave","max_development_interval_end":end,"min_primary_interval_start":start}
    excluded=[{"case_id":key,"reason":reason} for key,reason in sorted(dropped.items())]
    total=len(dev_rows)
    manifest={"schema":PROTOCOL_SCHEMA,"source_catalog_sha256":manifest_hash(catalog.manifest),"audit_manifest_sha256":manifest_hash(audit.manifest),
      "config_sha256":manifest_hash(config),"parser_code_sha256":audit.manifest["parser_code_sha256"],"psl_sha256":audit.manifest["psl_sha256"],
      "seed":config["split"]["seed"],"fractions":config["split"]["fractions"],"development_max_rows":config["split"]["development_max_rows"],
      "tracks":reports,"development":dev_report,"temporal":temporal,"observed_development_fractions":{name:len(parts[name])/total if total else None for name in ("train","validation","calibration")},
      "development_eligible_rows":sum(len(values) for values in dev_groups.values()),"cap_skipped_components":dict(sorted(skipped.items())),
      "exclusions":dict(sorted(Counter(dropped.values()).items())),"pruned_observations":dict(sorted(Counter(p["reason"] for p in pruning).items())),
      "limitations":["Release separation does not establish statistical independence.","Unknown campaigns or templates may still connect sources."]}
    sidecars={"assignments.json":[assignments],"components.jsonl":[{"component_id":c,"case_ids":keys} for c,keys in sorted(component_cases.items())],
      "owners.jsonl":owners,"pruning.jsonl":sorted(pruning,key=lambda p:p["observation_id"]),"exclusions.jsonl":excluded}
    return parts,components,sources,manifest,sidecars

def _bundle(parts,components,sources,manifest,audit,root):
    provenance={"provenance_schema":PROVENANCE_SCHEMA,"source_catalog_sha256":manifest["source_catalog_sha256"],"dataset_manifest_sha256":manifest["audit_manifest_sha256"],
      "derived_sha256":audit.manifest["files"]["rows.jsonl"],"parser_code_sha256":manifest["parser_code_sha256"],"psl_sha256":manifest["psl_sha256"],"protocol_sha256":manifest_hash(manifest),"seed":manifest["seed"]}
    development=SplitBundle({name:parts[name] for name in ("train","validation","calibration")},
      {"schema":DEVELOPMENT_SCHEMA,"provenance":provenance,"partitions":{name:manifest["tracks"][name] for name in ("train","validation","calibration")}})
    return V2Splits(development,{name:parts[name] for name in ("primary","external")},components,sources,manifest,Path(root).resolve(),audit.root.resolve())

def freeze_protocol(audit,catalog,config,output_dir):
    parts,components,sources,manifest,sidecars=_assemble(audit,catalog,config)
    manifest=publish_jsonl_directory(Path(output_dir),sidecars,manifest)
    return _bundle(parts,components,sources,manifest,audit,output_dir)

def load_protocol(audit,catalog,root,config):
    root=Path(root); actual=read_json(root/"manifest.json")
    if actual.get("schema")!=PROTOCOL_SCHEMA: raise DatasetError("protocol_schema_unsupported")
    verify_files(root,actual.get("files"))
    parts,components,sources,expected,sidecars=_assemble(audit,catalog,config)
    if set(actual["files"])!=set(sidecars) or any(actual.get(k)!=v for k,v in expected.items()): raise DatasetError("protocol_identity_or_counts_mismatch")
    for name,values in sidecars.items():
        digest=hashlib.sha256()
        for value in values: digest.update((json.dumps(value,sort_keys=True,ensure_ascii=True,allow_nan=False)+"\n").encode())
        if digest.hexdigest()!=actual["files"][name]: raise DatasetError("protocol_assignment_integrity_failed")
    return _bundle(parts,components,sources,actual,audit,root)

def assert_training_ready(splits):
    required=[splits.manifest["development"]]+[splits.manifest["tracks"][name] for name in ("train","validation","calibration","primary")]
    if any(track["status"]!="available" for track in required): raise DatasetError("training_support_incomplete",{"development":splits.manifest["development"],"tracks":splits.manifest["tracks"]})
