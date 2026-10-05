"""Deterministic whole-domain allocation, frozen before modelling."""
import hashlib
import json
import random
import shutil
from collections import Counter,defaultdict
from pathlib import Path
from .contracts import SplitBundle,DatasetError,SPLIT_SCHEMA
from .source import new_directory,publish_directory,write_json,read_json,sha256,verify_files

RATIOS={"train":.7,"validation":.1,"calibration":.1,"test":.1}

def manifest_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def summary(rows):
    return {"rows":len(rows),"groups":len({r.domain_group for r in rows}),
            "class_counts":dict(sorted(Counter(str(r.label) for r in rows).items()))}

def provenance(dataset):
    return {"dataset_manifest_sha256":manifest_hash(dataset.manifest),
            "source_sha256":dataset.manifest["source_sha256"],"psl_sha256":dataset.manifest["psl_sha256"],
            "derived_sha256":dataset.manifest["files"]["rows.jsonl"]}

def freeze_splits(dataset,output_dir:Path,seed=42):
    if Path(output_dir).exists(): raise DatasetError("output_exists")
    groups=defaultdict(list)
    for r in dataset.rows: groups[r.domain_group].append(r)
    if len({r.case_id for r in dataset.rows})!=len(dataset.rows): raise DatasetError("duplicate_case_id")
    if len(groups)<4 or any(sum(any(r.label==label for r in rows) for rows in groups.values())<4 for label in (0,1)):
        raise DatasetError("insufficient_label_groups_for_four_partitions")
    # Seeded shuffle breaks equal-size ties; big components are allocated first.
    ordered=sorted(groups); random.Random(seed).shuffle(ordered); ordered.sort(key=lambda key:-len(groups[key]))
    totals=[sum(r.label==c for r in dataset.rows) for c in (0,1)]
    targets={name:[ratio*n for n in totals] for name,ratio in RATIOS.items()}
    counts={name:[0,0] for name in RATIOS}; parts={name:[] for name in RATIOS}
    for key in ordered:
        rows=groups[key]; addition=[sum(r.label==c for r in rows) for c in (0,1)]
        def delta(name):
            return sum(((counts[name][c]+addition[c]-targets[name][c])**2 - (counts[name][c]-targets[name][c])**2)/max(targets[name][c],1) for c in (0,1))
        name=min(RATIOS,key=delta); parts[name].extend(rows)
        counts[name]=[counts[name][c]+addition[c] for c in (0,1)]
    parts={name:tuple(sorted(rows,key=lambda r:r.case_id)) for name,rows in parts.items()}
    if any({r.label for r in rows}!={0,1} for rows in parts.values()):
        raise DatasetError("allocation_missing_class_use_more_independent_groups")
    assignments={name:[r.case_id for r in rows] for name,rows in parts.items()}
    temp=new_directory(output_dir)
    try:
        write_json(temp / "assignments.json",assignments)
        m={"schema":SPLIT_SCHEMA,"seed":seed,"ratios":RATIOS,"provenance":provenance(dataset),
           "partitions":{name:summary(rows) for name,rows in parts.items()},
           "largest_groups":[{"group_sha256":hashlib.sha256(k.encode()).hexdigest(),**summary(tuple(groups[k]))} for k in ordered[:10]],
           "files":{"assignments.json":sha256(temp / "assignments.json")}}
        write_json(temp / "manifest.json",m); publish_directory(temp,output_dir)
        return SplitBundle(parts,m)
    finally:
        if temp.exists(): shutil.rmtree(temp)

def load_splits(dataset,output_dir:Path):
    root=Path(output_dir); m=read_json(root / "manifest.json")
    if m.get("schema")!=SPLIT_SCHEMA or m.get("provenance")!=provenance(dataset): raise DatasetError("split_provenance_mismatch")
    verify_files(root,m.get("files")); ids=read_json(root / "assignments.json")
    if set(ids)!=set(RATIOS): raise DatasetError("split_partition_names")
    lookup={r.case_id:r for r in dataset.rows}; seen=set(); owners={}; urls={}; parts={}
    try:
        for name,values in ids.items():
            if not isinstance(values,list): raise DatasetError("split_assignment_format")
            rows=[]
            for key in values:
                if key in seen or key not in lookup: raise DatasetError("split_id_integrity")
                seen.add(key); r=lookup[key]; rows.append(r)
                for mapping,value in ((owners,r.domain_group),(urls,r.url)):
                    if value in mapping and mapping[value]!=name: raise DatasetError("split_overlap")
                    mapping[value]=name
            parts[name]=tuple(rows)
            if {r.label for r in rows}!={0,1} or summary(rows)!=m["partitions"][name]: raise DatasetError("split_class_or_count_mismatch")
        if seen!=set(lookup): raise DatasetError("split_incomplete")
    except (KeyError,TypeError): raise DatasetError("split_assignment_format") from None
    return SplitBundle(parts,m)
