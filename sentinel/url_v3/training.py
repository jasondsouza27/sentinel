"""Guarded CPU research; every learner receives verified development rows."""
import hashlib
import json
import re
import time
from collections import defaultdict
from sentinel.url_ml import training as legacy
from sentinel.url_ml.contracts import DatasetError,SplitBundle,Selection,RunBundle
from sentinel.url_ml.provenance import validate_provenance
from sentinel.url_v2.contracts import ResearchRun
from sentinel.url_v2.protocol import choose_components
from sentinel.url_v2.storage import manifest_hash,sanitized
from .access import study_guard,assert_unscored,assert_fitting_guard
from .compat import development_bundle

def safe_diagnostics(value):
    value=sanitized(value)
    if isinstance(value,dict): return {k:safe_diagnostics(v) for k,v in value.items()}
    if isinstance(value,list): return [safe_diagnostics(v) for v in value]
    if isinstance(value,str):
        value=re.sub(r"(?i)\b[a-z]:[\\/][^\r\n\"'<>]+","<redacted-path>",value)
        value=re.sub(r"(?<!\w)/(?:Users|home|tmp|mnt|private|var)/[^\s\"'<>]+","<redacted-path>",value)
        return re.sub(r"(?i)(?:signature|token|api[_-]?key|authorization|x-amz-[a-z-]+)[=:]\S+","<redacted-secret>",value)
    return value

def component_pilot_rows(splits,maximum=2000):
    groups=defaultdict(list)
    for row in splits.development.partitions["train"]: groups[splits.component_by_case[row.case_id]].append(row)
    selected,_=choose_components(groups,maximum,42)
    rows=tuple(r for component in selected for r in groups[component])
    if not rows or {r.label for r in rows}!={0,1}: raise DatasetError("v3_pilot_insufficient_classes_or_component_budget")
    return rows

def fit_checked(splits,config,parser,rows,branch,params,*,pipeline_factory=None):
    assert_fitting_guard(splits)
    bundle=development_bundle(splits,config,parser); assert_unscored(splits)
    lookup={r.case_id:r for r in bundle.partitions["train"]}
    if (not isinstance(rows,tuple) or not rows or len({r.case_id for r in rows})!=len(rows) or
        any(lookup.get(r.case_id)!=r for r in rows)):
        raise DatasetError("v3_fit_rows_not_training")
    selected={r.case_id for r in rows}; components={splits.component_by_case[r.case_id] for r in rows}
    if selected!={r.case_id for r in lookup.values() if splits.component_by_case[r.case_id] in components}:
        raise DatasetError("v3_fit_component_truncated")
    settings=config["training"]
    if branch=="format_only":
        if params!={} or pipeline_factory is None: raise DatasetError("v3_format_fit_contract_invalid")
    elif (branch,params) not in legacy.candidate_grid(settings) or pipeline_factory is not None:
        raise DatasetError("v3_candidate_not_predeclared")
    context={"branch":branch,"params":params,"train_rows":len(rows),"native_threads":settings["native_threads"],
             "max_peak_bytes":settings["max_peak_bytes"]}
    started=time.perf_counter()
    try:
        model,record=legacy.fit_candidate(rows,branch,params,parser,settings["native_threads"],settings["max_peak_bytes"],
                                          pipeline_factory=pipeline_factory)
        return model,safe_diagnostics({**context,**record})
    except Exception as exc:
        return None,safe_diagnostics({**context,"status":"fit_failed","error_type":type(exc).__name__,
                                     "error_message":str(exc),"peak_bytes":None,"fit_seconds":time.perf_counter()-started})

def pilot_v3(splits,config,parser):
    with study_guard(splits,stage="pilot"):
        development_bundle(splits,config,parser); assert_unscored(splits)
        rows=component_pilot_rows(splits,config["training"]["pilot_max_rows"]); ids=[r.case_id for r in rows]
        report={"schema":"url-pilot-v3","rows":len(rows),"component_count":len({splits.component_by_case[r.case_id] for r in rows}),
                "case_ids":ids,"ids_sha256":hashlib.sha256(json.dumps(ids,separators=(",",":")).encode()).hexdigest(),
                "protocol_sha256":manifest_hash(splits.manifest),"measurements":[],"native_threads":4,
                "max_peak_bytes":config["training"]["max_peak_bytes"]}
        for branch in ("char_tfidf","lexical_hgb"):
            params=next(p for b,p in legacy.candidate_grid(config["training"]) if b==branch)
            model,record=fit_checked(splits,config,parser,rows,branch,params)
            report["measurements"].append(record)
            if model is None or record["status"]!="ok":
                report.update(status="failed",reason="resource_pilot_failed_"+record["status"])
                raise DatasetError(report["reason"],safe_diagnostics(report))
        return {**report,"status":"ok"}

def _operating_points(model,rows,budgets):
    from sentinel.url_ml.metrics import choose_threshold,point_metrics
    scores=legacy.raw_scores(model,[r.url for r in rows]); labels=[r.label for r in rows]
    return {str(b):{"raw_threshold":threshold,"validation":point_metrics(labels,scores,threshold)}
            for b in budgets for threshold in [choose_threshold(labels,scores,b)]}

def _selection(splits,config,parser,bundle):
    from sentinel.url_ml.metrics import choose_threshold,point_metrics
    train=bundle.partitions["train"]; validation=bundle.partitions["validation"]; settings=config["training"]
    labels=[r.label for r in validation]; urls=[r.url for r in validation]; records=[]; branches={}; best=None
    for index,(branch,params) in enumerate(legacy.candidate_grid(settings)):
        model,record=fit_checked(splits,config,parser,train,branch,params); record["configuration_index"]=index
        if model is not None and record["status"]=="ok":
            try:
                scores=legacy.raw_scores(model,urls); threshold=choose_threshold(labels,scores,settings["max_fpr"])
                metrics=point_metrics(labels,scores,threshold); rank=(metrics["recall"] or 0,metrics["precision"] or 0,-index)
                record.update(raw_threshold=threshold,validation=metrics)
                candidate=(model,threshold,params,record,rank)
                if branch not in branches or rank>branches[branch][-1]: branches[branch]=candidate
                if best is None or rank>best[-1]: best=(model,branch,threshold,params,index,rank)
            except Exception as exc:
                record.update(status="scoring_failed",error_type=type(exc).__name__,error_message=safe_diagnostics(str(exc)))
        records.append(record)
        progress={k:record.get(k) for k in ("branch","params","status","peak_bytes","fit_seconds","native_threads",
                                          "observed_tree_rss_peak_bytes","error_type","error_message")}
        print(json.dumps({"training_progress":{"configuration":index+1,**safe_diagnostics(progress)}},allow_nan=False),flush=True)
    if best is None or set(branches)!={"char_tfidf","lexical_hgb"}:
        raise DatasetError("v3_comparison_branch_unavailable",safe_diagnostics({"configurations":records}))
    model,branch,threshold,params,index,_=best
    report={"configurations":records,"selected_configuration":index,"max_fpr":settings["max_fpr"],
            "bootstrap_replicates":settings["bootstrap_replicates"],"selection_partitions":["train","validation"],
            "rule_validation":point_metrics(labels,legacy.rule_predictions(validation),.5),
            "sensitivity":{b:_operating_points(candidate[0],validation,settings["sensitivity_budgets"]) for b,candidate in branches.items()},
            "protocol_sha256":manifest_hash(splits.manifest)}
    return Selection(model,branch,threshold,params,report,branches)

def train_v3(splits,config,parser):
    from sentinel.url_v2.format_baseline import FEATURE_NAMES,build_format_pipeline
    from sentinel.url_ml.calibration import fit_calibration
    from threadpoolctl import threadpool_limits
    with study_guard(splits,stage="train"):
        bundle=development_bundle(splits,config,parser); assert_unscored(splits)
        selection=_selection(splits,config,parser,bundle); settings=config["training"]
        diagnostic,resources=fit_checked(splits,config,parser,bundle.partitions["train"],"format_only",{},
                                         pipeline_factory=build_format_pipeline)
        if diagnostic is None or resources["status"]!="ok":
            raise DatasetError("v3_format_diagnostic_fit_failed",safe_diagnostics({"resources":resources,
                                                                         "configurations":selection.report["configurations"]}))
        report={"schema":"url-format-diagnostic-v3","feature_names":FEATURE_NAMES,"eligible_for_deployment":False,
                "resources":resources,"sensitivity":_operating_points(diagnostic,bundle.partitions["validation"],settings["sensitivity_budgets"]),
                "calibration":"unavailable_diagnostic_only"}
        # Calibration is also a learner entry, with its own physical verification.
        bundle=development_bundle(splits,config,parser); assert_unscored(splits)
        calibration_rows=bundle.partitions["calibration"]
        with threadpool_limits(limits=4):
            calibration=fit_calibration([r.label for r in calibration_rows],
                                       legacy.raw_scores(selection.model,[r.url for r in calibration_rows]),selection.raw_threshold)
        provenance={**bundle.manifest["provenance"],"split_manifest_sha256":manifest_hash(bundle.manifest),
                    "training_config":settings,"training_config_sha256":manifest_hash(settings),
                    "calibration_ids_sha256":hashlib.sha256(json.dumps([r.case_id for r in calibration_rows]).encode()).hexdigest()}
        validate_provenance(provenance,stage="artifact")
        return ResearchRun(RunBundle(selection,calibration,provenance),diagnostic,report,splits.manifest)
