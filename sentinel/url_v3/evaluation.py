"""Fixed two-cohort evaluation, private score evidence and aggregate publication."""
import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_ml import training as legacy
from sentinel.url_v2.audit import format_flags,iter_provenance
from sentinel.url_v2.contracts import AuditBundle
from sentinel.url_v2.evaluation import component_metrics,_subgroups,_latency
from sentinel.url_v2.storage import (cleanup_pending,manifest_hash,new_directory,publish_directory,
                                     read_json,sha256,verify_files,write_json,save_failure)
from .access import study_guard,begin_final_access,finish_final_access
from .artifacts import load_v3_artifact,validate_research_sidecars
from .compat import verify_frozen_splits
from .protocol import assert_training_ready
from .contracts import EVALUATION_SCHEMA

def legitimate_query_metrics(rows,scores,threshold,groups,*,replicates=1000,seed=42):
    import numpy as np
    from sentinel.url_ml.metrics import _arrays,bootstrap_weights,predictions
    if len(rows)!=len(groups): raise DatasetError("v3_query_groups_invalid")
    _,values,_=_arrays([r.label for r in rows],scores)
    indices=[i for i,r in enumerate(rows) if r.label==0 and "query_present" in format_flags(r.url)]
    count=len(indices); group_array=np.asarray(groups)[indices]; predicted=predictions(values,threshold)[indices]
    components=len(set(group_array)); fp=int(predicted.sum()); rates=[]; limitations=[]
    if components>=2:
        for weights in bootstrap_weights(group_array,replicates,seed):
            rates.append(float(np.average(predicted,weights=weights)))
    if count<100 or components<30: limitations.append("exploratory_small_support")
    if not rates: limitations.append("insufficient_component_bootstrap_support")
    if rates and max(rates)==min(rates): limitations.append("constant_bootstrap_outcomes")
    return {"rows":count,"false_positives":fp,"false_positive_rate":fp/count if count else None,
            "components":components,"interval":np.percentile(rates,[2.5,97.5]).tolist() if rates else None,
            "bootstrap":{"unit":"domain_connected_component","replicates":replicates,"seed":seed,
                         "status":"complete" if rates else "unavailable","valid_replicates":len(rates)},
            "limitations":limitations,"scope":"legitimate URLs with a nonempty query; phishing recall is not measured"}

def _settings(config):
    return {"schema":"url-evaluation-settings-v3","tracks":["primary","supplemental"],
            "budgets":["0.05","0.01"],"bootstrap_replicates":1000,"bootstrap_seed":42,
            "rule_threshold":.5,"latency_warm_count":100,
            "training_config_sha256":manifest_hash(config["training"])}

def _metadata(path):
    from sentinel.url_ml.artifacts import _validate_metadata
    root=Path(path); m=read_json(root/"manifest.json")
    if m.get("schema")!="url-artifact-v3": raise DatasetError("v3_evaluation_artifact_required")
    try: _validate_metadata(m)
    except (TypeError,KeyError): raise DatasetError("v3_evaluation_artifact_invalid") from None
    verify_files(root,m["files"]); validate_research_sidecars(root,m)
    return m

def _check_model(research,splits,config):
    provenance=research.run.provenance
    if research.protocol!=splits.manifest: raise DatasetError("v3_evaluation_protocol_mismatch")
    expected={**splits.development.manifest["provenance"],
              "split_manifest_sha256":manifest_hash(splits.development.manifest),
              "training_config_sha256":manifest_hash(config["training"]),
              "calibration_ids_sha256":hashlib.sha256(json.dumps([r.case_id for r in splits.development.partitions["calibration"]]).encode()).hexdigest()}
    if any(provenance.get(k)!=v for k,v in expected.items()) or provenance["training_config"]!=config["training"]:
        raise DatasetError("v3_evaluation_model_binding_mismatch")

def _source_counts(splits):
    audit=AuditBundle(splits.audit_root,read_json(splits.audit_root/"manifest.json"))
    with (splits.root/"pruning.jsonl").open(encoding="utf-8") as f:
        pruned={json.loads(line)["observation_id"] for line in f}
    counts=Counter()
    for observation in iter_provenance(audit):
        if observation["observation_id"] in pruned: counts[observation["source_id"]]+=1
    return {"full_observations":audit.manifest["source_observation_counts"],
            "pruned_accepted_observations":dict(sorted(counts.items())),
            "source_partition_support":splits.manifest["source_partitions"]}

def _resources(record):
    return {k:record.get(k) for k in ("branch","params","status","peak_bytes","worker_peak_bytes",
            "observed_rss_peak_bytes","observed_tree_rss_peak_bytes","conservative_tree_peak_bytes",
            "monitored_process_count","fit_seconds","parent_wall_seconds","native_threads","max_peak_bytes","train_rows")}

def _score(research,splits,artifact_path,identity,stage):
    import numpy as np
    from sentinel.url_ml.calibration import apply_calibration
    run=research.run; reports={}
    with (stage/"scores.jsonl").open("x",encoding="utf-8",newline="\n") as scores_file:
        scores_file.write(json.dumps({"schema":"url-final-scores-v3","kind":"binding",**identity},sort_keys=True)+"\n")
        for name in ("primary","supplemental"):
            rows=tuple(sorted(splits.tracks[name],key=lambda r:r.case_id))
            labels=[r.label for r in rows]; groups=[splits.component_by_case[r.case_id] for r in rows]
            urls=[r.url for r in rows]
            scores={b:legacy.raw_scores(candidate[0],urls) for b,candidate in run.selection.branch_candidates.items()}
            scores["phase0_rules"]=np.asarray(legacy.rule_predictions(rows),dtype=float)
            scores["format_only"]=legacy.raw_scores(research.format_model,urls)
            calibrated=apply_calibration(run.calibration,scores[run.selection.branch]); comparisons={}
            for branch,values in scores.items():
                points=(run.selection.report["sensitivity"][branch] if branch in run.selection.branch_candidates else
                        research.format_report["sensitivity"] if branch=="format_only" else
                        {budget:{"raw_threshold":.5} for budget in ("0.05","0.01")})
                probabilities=calibrated if branch==run.selection.branch else None
                by_threshold={}; comparisons[branch]={}
                for budget,point in points.items():
                    threshold=point["raw_threshold"]
                    if threshold not in by_threshold:
                        metric=component_metrics(labels,values,threshold,groups,probabilities,replicates=1000,seed=42)
                        metric["legitimate_queries"]=legitimate_query_metrics(rows,values,threshold,groups)
                        by_threshold[threshold]=metric
                    comparisons[branch][budget]={**copy.deepcopy(by_threshold[threshold]),"raw_threshold":threshold,
                          "operating_point_source":"fixed descriptive rules" if branch=="phase0_rules" else "frozen validation scores",
                          "calibration_status":run.calibration.status if branch==run.selection.branch else "unavailable_not_selected"}
            errors=Counter(); decisions=(scores[run.selection.branch]>=run.selection.raw_threshold
                                         if run.selection.raw_threshold is not None else np.zeros(len(rows),dtype=bool))
            for i,row in enumerate(rows):
                record={"kind":"case","case_id":row.case_id,"track":name,"label":row.label,"component_id":groups[i],
                        "source_ids":list(splits.sources_by_case[row.case_id]),"scores":{b:float(v[i]) for b,v in scores.items()}}
                scores_file.write(json.dumps(record,sort_keys=True,allow_nan=False)+"\n")
                if int(decisions[i])!=row.label:
                    kind="false_positive" if decisions[i] else "false_negative"; errors[kind]+=1
                    for flag in format_flags(row.url): errors[kind+"_"+flag]+=1
            subgroups=_subgroups(rows,scores[run.selection.branch],run.selection.raw_threshold,calibrated,splits)
            subgroups["legitimate_queries"]=comparisons[run.selection.branch]["0.05"]["legitimate_queries"]
            reports[name]={"status":"available","support":splits.manifest["tracks"][name],"rows":len(rows),
                           "domain_groups":len({r.domain_group for r in rows}),"components":len(set(groups)),
                           "metrics":comparisons,"subgroups":subgroups,"error_categories":dict(errors),
                           "temporal":splits.manifest["temporal"]}
            print(json.dumps({"evaluation_progress":{"track":name,"status":"scored","rows":len(rows)}}),flush=True)
    return {"schema":EVALUATION_SCHEMA,"status":"complete",**identity,
            "source_catalog_sha256":run.provenance["source_catalog_sha256"],
            "config_sha256":run.provenance["config_sha256"],
            "parent_v2_protocol_sha256":run.provenance["parent_v2_protocol_sha256"],
            "protected_domains_sha256":run.provenance["protected_domains_sha256"],
            "selected_branch":run.selection.branch,"tracks":reports,
            "source_counts":_source_counts(splits),
            "bootstrap":{"unit":"domain_connected_component","replicates":1000,"seed":42},
            "latency":_latency(artifact_path,splits.tracks["primary"]),
            "fit_resources":[_resources(r) for r in run.selection.report["configurations"]]+[_resources(research.format_report["resources"])],
            "v1_comparison":{"status":"deferred","reason":"historical cohorts are not headline comparators"},
            "limitations":["Historical URL annotations do not verify present-day sites.",
                           "Supplemental is group-held-out from a source also used in development; it is not source-independent.",
                           "Collection-month documentation is not a row date; temporal validation is unavailable.",
                           "Unknown campaigns and popular-domain sampling restrict generalization.",
                           "Small subgroups and constant bootstrap intervals do not establish certainty.",
                           "Prevalence scenarios assume stable rates; they are not deployment estimates.",
                           "URL-only results do not establish message-link fusion benefit.",
                           "Research candidate only; learned live warnings remain disabled."]}

def evaluate_v3(splits,config,parser,artifact_path):
    from .training import safe_diagnostics
    with study_guard(splits,stage="evaluate"):
        verify_frozen_splits(splits,config,parser); assert_training_ready(splits)
        m=_metadata(artifact_path); asset=manifest_hash(m); settings=manifest_hash(_settings(config)); protocol=manifest_hash(splits.manifest)
        identity={"artifact_manifest_sha256":asset,"protocol_sha256":protocol,"evaluation_settings_sha256":settings}
        out=splits.study_root/"runs"/("evaluation-"+manifest_hash(identity))
        receipt_path=splits.study_root/"final-access"/(protocol+".json")
        if receipt_path.exists():
            receipt=read_json(receipt_path)
            if receipt.get("artifact_sha256")!=asset or receipt.get("settings_sha256")!=settings:
                raise DatasetError("v3_final_resume_identity_mismatch")
            if out.exists():
                private=read_json(out/"manifest.json")
                if private.get("schema")!="url-private-evaluation-v3" or set(private.get("files",{}))!={"scores.jsonl","report.json"}:
                    raise DatasetError("v3_completed_report_manifest_invalid")
                verify_files(out,private["files"]); report=read_json(out/"report.json"); digest=manifest_hash(report)
                if (private.get("status")!="complete" or private.get("report_sha256")!=digest or
                    any(private.get(k)!=v for k,v in identity.items()) or
                    any(report.get(k)!=v for k,v in identity.items()) or
                    report.get("schema")!=EVALUATION_SCHEMA or report.get("status")!="complete" or
                    set(report.get("tracks",{}))!={"primary","supplemental"} or
                    any(report.get(k)!=m["provenance"][k] for k in
                        ("source_catalog_sha256","config_sha256","parent_v2_protocol_sha256","protected_domains_sha256")) or
                    (receipt.get("report_sha256") is not None and receipt["report_sha256"]!=digest)):
                    raise DatasetError("v3_completed_report_identity_invalid")
                _public(report)
                if receipt.get("status")!="complete":
                    begin_final_access(splits,asset,settings)
                    finish_final_access(splits,status="complete",report_sha256=digest)
                return report
            if receipt.get("status")=="complete": raise DatasetError("v3_completed_report_missing")
        research=load_v3_artifact(artifact_path); _check_model(research,splits,config)
        snapshot=copy.deepcopy(splits); verify_frozen_splits(snapshot,config,parser)
        begin_final_access(splits,asset,settings); stage=None
        try:
            stage=new_directory(out)
            report=_score(research,snapshot,artifact_path,identity,stage)
            verify_frozen_splits(splits,config,parser)
            write_json(stage/"report.json",report)
            manifest={"schema":"url-private-evaluation-v3","status":"complete",**identity,
                      "report_sha256":manifest_hash(report),"files":{n:sha256(stage/n) for n in ("scores.jsonl","report.json")}}
            write_json(stage/"manifest.json",manifest); publish_directory(stage,out)
            finish_final_access(splits,status="complete",report_sha256=manifest_hash(report))
            return report
        except Exception as exc:
            save_failure(splits.study_root,"evaluate",safe_diagnostics({"reason":getattr(exc,"reason",type(exc).__name__),
                         "error_message":str(exc),**identity}))
            finish_final_access(splits,status="failed")
            if isinstance(exc,DatasetError): raise
            raise DatasetError("v3_final_scoring_failed",safe_diagnostics({"error_type":type(exc).__name__,"error_message":str(exc)})) from None
        finally:
            if stage is not None: cleanup_pending(stage,out.parent)

def render_card(report):
    lines=["# Sentinel URL v3 frozen evaluation","",
           "Selected branch: "+report["selected_branch"]+". Thresholds were frozen on validation.",
           "Artifact manifest SHA-256: "+report["artifact_manifest_sha256"],
           "Protocol SHA-256: "+report["protocol_sha256"],""]
    for name,track in report["tracks"].items():
        metric=track["metrics"][report["selected_branch"]]["0.05"]; query=track["subgroups"]["legitimate_queries"]
        lines.append(f"{name}: {track['rows']} URLs, {track['components']} components. Precision {metric['precision']}, recall {metric['recall']}, F1 {metric['f1']}, FPR {metric['fpr']}.")
        lines.append(f"Legitimate queries: {query['false_positives']} false positives / {query['rows']} URLs; FPR {query['false_positive_rate']}.")
        lines.append(f"Calibration {metric['calibration_status']}; Brier {metric['brier']}, ECE {metric['ece']}; temporal validation unavailable.")
    lines+=["","Both learned branches, fixed rules and the format diagnostic are compared at 5%/1% validation budgets.",
            "Uncertainty resamples whole connected components with 1,000 replicates, seed 42.","",
            *report["limitations"],"","Sources: PhreshPhish authors; Hannousse, Abdelhakim and Yahiouche, Salima, Web page phishing detection V3, CC BY 4.0.",
            "https://data.mendeley.com/datasets/c2gw7fy2j4/3",""]
    return "\n".join(lines)

def _public(value,key=""):
    raw_keys={"case_id","case_ids","observation_id","observation_ids","component_id","component_ids",
              "owner_observation_ids","url","original_url","source_ref","source_date"}
    if isinstance(value,dict):
        for k,v in value.items():
            if k in raw_keys or re.fullmatch("[0-9a-f]{64}",str(k)): raise DatasetError("v3_public_report_contains_private_data")
            _public(v,str(k))
    elif isinstance(value,(list,tuple)):
        for v in value: _public(v,key)
    elif isinstance(value,str):
        if (re.search(r"https?://|[a-z]:[\\/]|/(?:Users|home|tmp|private|mnt)/",value,re.I) or
            (re.fullmatch("[0-9a-f]{64}",value) and not key.endswith("_sha256"))):
            raise DatasetError("v3_public_report_contains_private_data")

def publish_evaluation(report,output_dir):
    if (report.get("schema")!=EVALUATION_SCHEMA or report.get("status")!="complete" or
        set(report.get("tracks",{}))!={"primary","supplemental"}):
        raise DatasetError("v3_public_evaluation_incomplete")
    _public(report); json.dumps(report,allow_nan=False)
    output=Path(output_dir); stage=new_directory(output)
    try:
        write_json(stage/"evaluation.json",report)
        from .contracts import STATUS_SCHEMA
        completed={"schema":STATUS_SCHEMA,"stage":"evaluate","status":"complete","reason":None,
                   "models_fitted":True,"metrics":report,"training_ready":True,
                   "support":{"tracks":{n:t["support"] for n,t in report["tracks"].items()},
                              "source_counts":report["source_counts"]},
                   "identities":{k:v for k,v in report.items() if k.endswith("_sha256")},
                   "limitations":report["limitations"]}
        write_json(stage/"research-status.json",completed)
        (stage/"model-card.md").write_text(render_card(report),encoding="utf-8")
        publish_directory(stage,output); return report
    finally: cleanup_pending(stage,output.parent)


def publish_research_status(splits,config,output_dir,*,stage,status,reason=None,metrics=None):
    """Publish measured support even when a frozen study cannot be fitted."""
    from .contracts import STATUS_SCHEMA
    stages=("bind-v2","acquire-mendeley","audit","freeze","pilot","train","evaluate")
    if stage not in stages or status not in ("ready","unavailable","failed","complete"):
        raise DatasetError("v3_research_status_invalid")
    if metrics is not None and (stage!="evaluate" or status!="complete" or
          metrics.get("schema")!=EVALUATION_SCHEMA or metrics.get("status")!="complete"):
        raise DatasetError("v3_status_metrics_not_completed")
    m=splits.manifest if splits is not None else None
    if metrics is not None and (m is None or metrics.get("protocol_sha256")!=manifest_hash(m)):
        raise DatasetError("v3_status_metrics_protocol_mismatch")
    fitted=True if metrics is not None else False if stage in stages[:4] or reason=="v3_training_support_incomplete" else None
    identities={"config_sha256":manifest_hash(config)}
    support=None
    if m is not None:
        identities.update({k:m[k] for k in ("parent_v2_protocol_sha256","protected_domains_sha256","source_catalog_sha256",
                                            "audit_manifest_sha256","parser_code_sha256","psl_sha256")})
        identities["protocol_sha256"]=manifest_hash(m)
        support={k:m[k] for k in ("tracks","development","source_development","source_partitions","protected_domain_groups",
                                  "original_primary_cases","original_primary_removed","mandatory_development_rows",
                                  "development_eligible_rows","pruned_observations","exclusions","observed_development_fractions","temporal")}
        support["cap_skipped_components"]=len(m["cap_skipped_components"])
    report={"schema":STATUS_SCHEMA,"stage":stage,"status":status,"reason":reason,"models_fitted":fitted,"metrics":metrics,
            "training_ready":m["training_ready"] if m is not None else None,"support":support,"identities":identities,
            "limitations":["Historical annotations do not verify current sites.",
                           "Supplemental is group-held-out from a development source, not source-independent.",
                           "Temporal validation is unavailable; no row dates were invented.",
                           "Learned application warnings remain disabled.",
                           "Unknown fitting completion is null rather than a claim that no partial fits occurred."]}
    _public(report); json.dumps(report,allow_nan=False)
    if metrics is not None: card=render_card(metrics)
    else:
        fit_text="No model was fitted." if fitted is False else "Fitting completion is unavailable; consult preserved private diagnostics."
        card="\n".join(["# Sentinel URL v3 research status","",f"Stage: {stage}; status: {status}; reason: {reason}.",
                        fit_text,"Accuracy, recall, F1, calibration and final latency are unavailable.",
                        "Measured frozen support is in research-status.json. Failed gates do not authorize another seed, cap or final reservation.",
                        "",*report["limitations"],"","Hannousse and Yahiouche, Web page phishing detection V3, CC BY 4.0.",
                        "https://data.mendeley.com/datasets/c2gw7fy2j4/3",""])
    output=Path(output_dir); pending=new_directory(output)
    try:
        write_json(pending/"research-status.json",report); (pending/"model-card.md").write_text(card,encoding="utf-8")
        publish_directory(pending,output); return report
    finally: cleanup_pending(pending,output.parent)
