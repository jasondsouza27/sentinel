"""Frozen, source-specific research metrics; public reports contain aggregates only."""
import hashlib
import json
import re
import statistics
import time
from collections import Counter,defaultdict
from pathlib import Path
from uuid import uuid4
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_ml import training as legacy
from .artifacts import load_v2_artifact
from .audit import format_flags,iter_records
from .compat import development_bundle
from .contracts import AuditBundle,EVALUATION_SCHEMA
from .storage import cleanup_pending,manifest_hash,new_directory,publish_directory,read_json,sha256,verify_files,write_json

METRICS=("precision","recall","f1","macro_f1","pr_auc","fpr","coverage","brier","ece")

def component_metrics(labels,scores,threshold,groups,probabilities=None,*,replicates=1000,seed=42):
    import numpy as np
    from sentinel.url_ml.metrics import _arrays,point_metrics,predictions
    y,s,w=_arrays(labels,scores); group_array=np.asarray(groups)
    if group_array.shape!=y.shape: raise DatasetError("bootstrap_component_shape_invalid")
    report=point_metrics(y,s,threshold,probabilities); unique,inverse=np.unique(group_array,return_inverse=True)
    support={str(c):len(set(group_array[y==c])) for c in (0,1)}; values={key:[] for key in METRICS}
    predicted=predictions(s,threshold); masks=[(y==0)&~predicted,(y==0)&predicted,(y==1)&~predicted,(y==1)&predicted]
    # Reuse score order across replicas: exact weighted average precision, no repeated sort.
    order=np.argsort(-s,kind="stable"); ordered_y=y[order]; ends=np.flatnonzero(np.r_[s[order][:-1]!=s[order][1:],True])
    p=np.asarray(probabilities,dtype=float) if probabilities is not None else None
    if p is not None: _arrays(y,p)
    bins=np.minimum((p*10).astype(int),9) if p is not None else None
    rng=np.random.default_rng(seed)
    def divide(a,b): return float(a/b) if b>0 else None
    enough=all(support[str(c)]>=2 for c in (0,1))
    if enough:
        for _ in range(replicates):
            multiplicity=np.bincount(rng.integers(0,len(unique),size=len(unique)),minlength=len(unique)); weights=multiplicity[inverse]
            tn,fp,fn,tp=[float(weights[mask].sum()) for mask in masks]; positive=tp+fn; negative=tn+fp
            pos_f1=divide(2*tp,2*tp+fp+fn) if positive else None; neg_f1=divide(2*tn,2*tn+fp+fn) if negative else None
            ap=None
            if positive and negative:
                sw=weights[order]; cumulative_tp=np.cumsum(sw*(ordered_y==1))[ends]; cumulative_fp=np.cumsum(sw*(ordered_y==0))[ends]
                denominator=cumulative_tp+cumulative_fp; precision=np.divide(cumulative_tp,denominator,out=np.zeros_like(cumulative_tp,dtype=float),where=denominator>0)
                ap=float(np.sum(precision*np.diff(np.r_[0,cumulative_tp]))/positive)
            brier=ece=None
            if p is not None:
                total=float(weights.sum()); brier=float(np.sum(weights*(p-y)**2)/total); ece=float(np.sum(np.abs(np.bincount(bins,weights=weights*p,minlength=10)-np.bincount(bins,weights=weights*y,minlength=10)))/total)
            result={"precision":divide(tp,tp+fp),"recall":divide(tp,positive),"fpr":divide(fp,negative),"f1":pos_f1,
              "macro_f1":(pos_f1+neg_f1)/2 if pos_f1 is not None and neg_f1 is not None else None,"pr_auc":ap,"coverage":1.,"brier":brier,"ece":ece}
            for key,value in result.items():
                if value is not None: values[key].append(value)
    report["intervals"]={key:np.percentile(values[key],[2.5,97.5]).tolist() if len(values[key])>=max(2,replicates//2) else None for key in METRICS}
    constants=[key for key,v in values.items() if v and max(v)==min(v)]
    limitations=[]
    if not enough: limitations.append("insufficient_component_bootstrap_support")
    if min(support.values())<30 or any(int((y==c).sum())<100 for c in (0,1)): limitations.append("exploratory_small_support")
    if constants: limitations.append("constant_bootstrap_outcomes")
    report["bootstrap"]={"unit":"domain_connected_component","seed":seed,"replicates":replicates,"status":"complete" if enough else "unavailable", "class_component_support":support,"valid_replicates":{k:len(v) for k,v in values.items()},"constant_metrics":constants}
    report["limitations"]=limitations
    report["prevalence_scenarios"]=[{"assumed_prevalence":prevalence,"expected_precision":None if report["recall"] is None or report["fpr"] is None else divide(report["recall"]*prevalence,report["recall"]*prevalence+report["fpr"]*(1-prevalence))} for prevalence in (.001,.01,.05,.1)]
    return report

def _check_frozen(research,splits,artifact):
    if splits.root is None or splits.audit_root is None: raise DatasetError("evaluation_private_roots_required")
    protocol=read_json(splits.root/"manifest.json")
    if protocol!=splits.manifest: raise DatasetError("evaluation_protocol_changed")
    verify_files(splits.root,protocol["files"])
    actual_components={}; actual_sources={}
    with (splits.root/"components.jsonl").open(encoding="utf-8") as f:
        for line in f:
            value=json.loads(line)
            if manifest_hash({"case_ids":value["case_ids"]})!=value["component_id"]: raise DatasetError("evaluation_component_identity_invalid")
            for key in value["case_ids"]: actual_components[key]=value["component_id"]
    with (splits.root/"owners.jsonl").open(encoding="utf-8") as f:
        for line in f:
            value=json.loads(line); actual_sources[value["case_id"]]=tuple(value["source_ids"])
    if actual_components!=splits.component_by_case or actual_sources!=splits.sources_by_case: raise DatasetError("evaluation_components_or_owners_changed")
    audit_manifest=read_json(splits.audit_root/"manifest.json")
    verify_files(splits.audit_root,audit_manifest["files"])
    if manifest_hash(audit_manifest)!=protocol["audit_manifest_sha256"]: raise DatasetError("evaluation_audit_changed")
    bundle=development_bundle(splits)
    if research.run.provenance["protocol_sha256"]!=manifest_hash(protocol) or research.run.provenance["split_manifest_sha256"]!=manifest_hash(bundle.manifest): raise DatasetError("evaluation_model_protocol_mismatch")
    if research.protocol!=protocol: raise DatasetError("evaluation_research_protocol_mismatch")
    parts={**splits.development.partitions,**splits.tracks}; assignments={name:[r.case_id for r in rows] for name,rows in parts.items()}
    encoded=(json.dumps(assignments,sort_keys=True,ensure_ascii=True,allow_nan=False)+"\n").encode()
    if hashlib.sha256(encoded).hexdigest()!=protocol["files"]["assignments.json"]: raise DatasetError("evaluation_assignments_changed")
    lookup={r.case_id:r for rows in parts.values() for r in rows}; checked=set()
    for record in iter_records(AuditBundle(splits.audit_root,audit_manifest)):
        if record.row.case_id in lookup:
            if record.row!=lookup[record.row.case_id]: raise DatasetError("evaluation_rows_changed")
            checked.add(record.row.case_id)
    if checked!=set(lookup): raise DatasetError("evaluation_rows_missing")
    frozen=load_v2_artifact(artifact)
    for field in ("protocol_sha256","source_catalog_sha256","dataset_manifest_sha256","derived_sha256","training_config_sha256","split_manifest_sha256"):
        if frozen.run.provenance[field]!=research.run.provenance[field]: raise DatasetError("evaluation_artifact_mismatch")
    ids=[r.case_id for r in bundle.partitions["calibration"]]
    if hashlib.sha256(json.dumps(ids).encode()).hexdigest()!=frozen.run.provenance["calibration_ids_sha256"]: raise DatasetError("evaluation_calibration_ids_changed")
    return frozen

def _subgroups(rows,scores,threshold,probabilities,splits):
    import numpy as np
    from sentinel.url_ml.metrics import point_metrics
    result={"scope":"selected model at validation budget 0.05","source":{},"format":{},"class":{}}
    groups={"source":{source:[i for i,r in enumerate(rows) if source in splits.sources_by_case[r.case_id]] for source in sorted({s for r in rows for s in splits.sources_by_case[r.case_id]})},
      "format":{flag+"_"+str(present).lower():[i for i,r in enumerate(rows) if (flag in format_flags(r.url))==present] for flag in ("https","www_host","non_root_path","query_present") for present in (True,False)},
      "class":{str(c):[i for i,r in enumerate(rows) if r.label==c] for c in (0,1)}}
    for category,strata in groups.items():
        for name,indices in strata.items():
            selected=[rows[i] for i in indices]; support={str(c):{"rows":sum(r.label==c for r in selected),"components":len({splits.component_by_case[r.case_id] for r in selected if r.label==c})} for c in (0,1)}
            exploratory=any(v["rows"]<100 or v["components"]<30 for v in support.values())
            result[category][name]={"rows":len(selected),"class_support":support,"exploratory":exploratory,"metrics":point_metrics([r.label for r in selected],np.asarray(scores)[indices],threshold,np.asarray(probabilities)[indices] if probabilities is not None else None) if indices else None}
    return result

def _latency(artifact,rows):
    import numpy as np
    from sentinel.url_ml.service import UrlModelService
    started=time.perf_counter(); service=UrlModelService(artifact); result=service.assess(rows[0].url); cold=time.perf_counter()-started
    if result.state!="complete": raise DatasetError("cold_latency_assessment_failed")
    timings=[]; ordered=sorted(rows,key=lambda r:r.case_id)
    for index in range(100):
        row=ordered[index%len(ordered)]; start=time.perf_counter(); result=service.assess(row.url); timings.append(time.perf_counter()-start)
        if result.state!="complete": raise DatasetError("warm_latency_assessment_failed")
    return {"cold_load_and_first_seconds":cold,"warm_count":100,"warm_unique_urls":min(100,len(ordered)),"warm_median_seconds":statistics.median(timings),"warm_p95_seconds":float(np.percentile(timings,95)),"scope":"single URL, local CPU, deterministic case order"}

def _public_resources(record):
    return {key:record.get(key) for key in ("branch","params","status","peak_bytes","observed_rss_peak_bytes","fit_seconds","parent_wall_seconds","native_threads","max_peak_bytes","train_rows")}

def paired_rows(rows,splits,v1_development_domains):
    manifest=read_json(splits.audit_root/"manifest.json"); blocked=set()
    for record in iter_records(AuditBundle(splits.audit_root,manifest)):
        if record.row.domain_group in v1_development_domains: blocked.add(splits.component_by_case[record.row.case_id])
    return tuple(r for r in rows if splits.component_by_case[r.case_id] not in blocked),blocked

def paired_differences(labels,v1_scores,v1_threshold,v2_scores,v2_threshold,groups,*,replicates=1000,seed=42):
    import numpy as np
    from sentinel.url_ml.metrics import point_metrics,bootstrap_weights
    first=point_metrics(labels,v1_scores,v1_threshold); second=point_metrics(labels,v2_scores,v2_threshold)
    keys=("precision","recall","f1","macro_f1","pr_auc","fpr"); differences={key:[] for key in keys}
    for weights in bootstrap_weights(groups,replicates,seed):
        a=point_metrics(labels,v1_scores,v1_threshold,weights=weights); b=point_metrics(labels,v2_scores,v2_threshold,weights=weights)
        for key in keys:
            if a[key] is not None and b[key] is not None: differences[key].append(b[key]-a[key])
    return {"direction":"v2_minus_v1_on_identical_rows","unit":"domain_connected_component","replicates":replicates,"seed":seed,
      "point_difference":{key:second[key]-first[key] if second[key] is not None and first[key] is not None else None for key in keys},
      "intervals":{key:np.percentile(values,[2.5,97.5]).tolist() if len(values)>=max(2,replicates//2) else None for key,values in differences.items()},
      "valid_replicates":{key:len(values) for key,values in differences.items()},
      "limitations":["constant_bootstrap_outcomes"] if any(v and max(v)==min(v) for v in differences.values()) else []}

def _v1_binding(v1_run,v1_data):
    if v1_run is None or v1_data is None: raise DatasetError("v1_artifact_and_data_required_together")
    dataset,splits=v1_data; provenance=v1_run.provenance
    if not re.fullmatch("[0-9a-f]{64}",provenance.get("artifact_manifest_sha256","")): raise DatasetError("v1_verified_artifact_required")
    if provenance.get("split_manifest_sha256")!=manifest_hash(splits.manifest) or provenance.get("dataset_manifest_sha256")!=manifest_hash(dataset.manifest): raise DatasetError("v1_dataset_split_mismatch")
    expected={"source_sha256":dataset.manifest["source_sha256"],"derived_sha256":dataset.manifest["files"]["rows.jsonl"],"psl_sha256":dataset.manifest["psl_sha256"]}
    if any(provenance.get(key)!=value for key,value in expected.items()): raise DatasetError("v1_source_mismatch")
    development={r.domain_group for name,rows in splits.partitions.items() if name!="test" for r in rows}
    return dataset,development

def _v1_comparison(v1_run,v1_data,research,splits,track_rows,track_scores):
    import numpy as np
    dataset,development=_v1_binding(v1_run,v1_data); all_domains={r.domain_group for r in dataset.rows}; all_urls={r.url for r in dataset.rows}; result={}
    for name,rows in track_rows.items():
        if not rows:
            result[name]={"status":"unavailable","reason":"track_unavailable","transfer":None,"paired":None}; continue
        groups=[splits.component_by_case[r.case_id] for r in rows]; labels=[r.label for r in rows]
        scores=legacy.raw_scores(v1_run.selection.model,[r.url for r in rows])
        transfer={"entire_v1_dataset_overlap":{"domain_rows":sum(r.domain_group in all_domains for r in rows),"url_rows":sum(r.url in all_urls for r in rows),"components":len({splits.component_by_case[r.case_id] for r in rows if r.domain_group in all_domains})},
          "metrics":component_metrics(labels,scores,v1_run.selection.raw_threshold,groups),"interpretation":"Transfer diagnostic with measured overlap, not an improvement estimate."}
        paired,blocked=paired_rows(rows,splits,development); class_counts={str(c):sum(r.label==c for r in paired) for c in (0,1)}
        domains={str(c):len({r.domain_group for r in paired if r.label==c}) for c in (0,1)}
        record={"status":"unavailable","reasons":["paired_final_support_insufficient"],"rows":len(paired),"class_counts":class_counts,"domain_groups_per_class":domains,"excluded_components":len({splits.component_by_case[r.case_id] for r in rows}&blocked),"metrics":None,"differences":None}
        if all(class_counts[str(c)]>=100 and domains[str(c)]>=30 for c in (0,1)):
            indices=[i for i,r in enumerate(rows) if splits.component_by_case[r.case_id] not in blocked]; paired_labels=[r.label for r in paired]; paired_groups=[splits.component_by_case[r.case_id] for r in paired]
            first=scores[indices]; second=track_scores[name][research.run.selection.branch][indices]
            record.update({"status":"available","reasons":[],"metrics":{"v1":component_metrics(paired_labels,first,v1_run.selection.raw_threshold,paired_groups),
              "v2":component_metrics(paired_labels,second,research.run.selection.raw_threshold,paired_groups)},
              "differences":paired_differences(paired_labels,first,v1_run.selection.raw_threshold,second,research.run.selection.raw_threshold,paired_groups)})
        result[name]={"status":"available","transfer":transfer,"paired":record}
    return {"status":"available","v1_artifact_manifest_sha256":v1_run.provenance["artifact_manifest_sha256"],"tracks":result,
      "limitation":"Different historical test populations cannot estimate a v1-to-v2 improvement."}

def evaluate_robustness(research,splits,artifact_path,*,v1_run=None,v1_data=None):
    import numpy as np
    from sentinel.url_ml.calibration import apply_calibration
    frozen=_check_frozen(research,splits,artifact_path); run=frozen.run
    if (v1_run is None)!=(v1_data is None): raise DatasetError("v1_artifact_and_data_required_together")
    if v1_run is not None: _v1_binding(v1_run,v1_data)
    reports={}; retained={}; all_scores={}
    private=splits.root.parent/"runs"; private.mkdir(exist_ok=True)
    scores_path=private/("evaluation-scores-"+uuid4().hex+".jsonl")
    with scores_path.open("x",encoding="utf-8",newline="\n") as private_scores:
        for name in ("primary","external"):
            support=splits.manifest["tracks"][name]; rows=tuple(sorted(splits.tracks[name],key=lambda r:r.case_id)); retained[name]=rows if support["status"]=="available" else ()
            if support["status"]!="available":
                reports[name]={"status":"unavailable","reasons":support["reasons"],"support":support,"metrics":None,"subgroups":None}; continue
            labels=[r.label for r in rows]; groups=[splits.component_by_case[r.case_id] for r in rows]; urls=[r.url for r in rows]
            scores={branch:legacy.raw_scores(candidate[0],urls) for branch,candidate in run.selection.branch_candidates.items()}
            scores["phase0_rules"]=np.asarray(legacy.rule_predictions(rows),dtype=float); scores["format_only"]=legacy.raw_scores(frozen.format_model,urls); all_scores[name]=scores
            calibrated=apply_calibration(run.calibration,scores[run.selection.branch]); comparisons={}
            for branch,values in scores.items():
                points=run.selection.report["sensitivity"][branch] if branch in run.selection.branch_candidates else frozen.format_report["sensitivity"] if branch=="format_only" else {budget:{"raw_threshold":.5} for budget in ("0.05","0.01")}
                probabilities=calibrated if branch==run.selection.branch else None
                comparisons[branch]={budget:{**component_metrics(labels,values,point["raw_threshold"],groups,probabilities),"raw_threshold":point["raw_threshold"],
                  "operating_point_source":"fixed descriptive rules" if branch=="phase0_rules" else "frozen validation scores", "calibration_status":run.calibration.status if branch==run.selection.branch else "unavailable_not_selected"} for budget,point in points.items()}
            errors=Counter(); decisions=scores[run.selection.branch]>=run.selection.raw_threshold if run.selection.raw_threshold is not None else np.zeros(len(rows),dtype=bool)
            for i,row in enumerate(rows):
                private_scores.write(json.dumps({"case_id":row.case_id,"track":name,"label":row.label,"component_id":groups[i],"scores":{branch:float(values[i]) for branch,values in scores.items()}},sort_keys=True,allow_nan=False)+"\n")
                if int(decisions[i])!=row.label:
                    kind="false_positive" if decisions[i] else "false_negative"; errors[kind]+=1
                    for flag in format_flags(row.url): errors[kind+"_"+flag]+=1
            reports[name]={"status":"available","reasons":[],"support":support,"rows":len(rows),"domain_groups":len({r.domain_group for r in rows}),"components":len(set(groups)),
              "metrics":comparisons,"subgroups":_subgroups(rows,scores[run.selection.branch],run.selection.raw_threshold,calibrated,splits),"error_categories":dict(errors)}
            if name=="primary": reports[name]["temporal"]=splits.manifest["temporal"]
    available_rows=next((retained[name] for name in ("primary","external") if retained[name]),())
    report={"schema":EVALUATION_SCHEMA,"artifact_manifest_sha256":run.provenance["artifact_manifest_sha256"],"protocol_sha256":run.provenance["protocol_sha256"],
      "source_catalog_sha256":run.provenance["source_catalog_sha256"],"selected_branch":run.selection.branch,"tracks":reports,
      "bootstrap":{"unit":"domain_connected_component","replicates":1000,"seed":42},"latency":_latency(artifact_path,available_rows) if available_rows else None,
      "fit_resources":[_public_resources(r) for r in run.selection.report["configurations"]]+[_public_resources(frozen.format_report["resources"])],
      "v1_comparison":_v1_comparison(v1_run,v1_data,frozen,splits,retained,all_scores) if v1_run is not None else {"status":"unavailable","reason":"verified_v1_artifact_and_data_not_supplied"},
      "limitations":["Historical source URL labels do not verify current sites.","Release separation does not prove independence; unknown campaigns may overlap.",
        "Temporal claims require authenticated collection semantics and strict interval separation.","Tiny subgroups are exploratory; constant bootstrap intervals are not certainty.",
        "Conditional prevalence scenarios assume unchanged rates and are not deployment estimates.","URL-only results do not establish message-link fusion benefit.","V2 remains a research candidate; learned live warnings are disabled."]}
    return report

def render_card(report):
    lines=["# Sentinel URL v2 frozen robustness evaluation","",f"Selected branch: **{report['selected_branch']}**. Thresholds were selected on validation only.",
      f"Artifact manifest SHA-256: `{report['artifact_manifest_sha256']}`.",f"Protocol SHA-256: `{report['protocol_sha256']}`.",""]
    for name,track in report["tracks"].items():
        if track["status"]!="available": lines.append(f"{name}: unavailable ({', '.join(track['reasons'])}); metrics remain null."); continue
        metric=track["metrics"][report["selected_branch"]]["0.05"]
        lines.append(f"{name}: {track['rows']} URLs / {track['domain_groups']} domain groups / {track['components']} connected components. Precision {metric['precision']}, recall {metric['recall']}, F1 {metric['f1']}, actual FPR {metric['fpr']}.")
        lines.append(f"Calibration: {metric['calibration_status']}; Brier {metric['brier']}, ECE {metric['ece']}. Temporal: {track.get('temporal',{}).get('status','not claimed')}.")
    lines += ["","The JSON includes both learned branches, fixed rules, the format-only diagnostic, 5%/1% validation operating points, whole-component bootstrap support and subgroup counts.","",*report["limitations"],""]
    return "\n".join(lines)

def publish_evaluation(report,output_dir):
    if report.get("schema")!=EVALUATION_SCHEMA: raise DatasetError("evaluation_schema_invalid")
    serialized=json.dumps(report,sort_keys=True,allow_nan=False)
    if re.search(r"https?://|[A-Za-z]:[\\/]|\"(?:case_id|case_ids|observation_id|url|original_url)\"\s*:",serialized): raise DatasetError("public_evaluation_contains_private_data")
    output=Path(output_dir); temp=new_directory(output)
    try:
        write_json(temp/"evaluation.json",report); (temp/"model-card.md").write_text(render_card(report),encoding="utf-8")
        publish_directory(temp,output); return report
    finally: cleanup_pending(temp,output.parent)
