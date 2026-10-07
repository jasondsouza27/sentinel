"""Reuse CPU model selection with explicit development boundaries and controls."""
import json
from collections import defaultdict
from sentinel.url_ml.contracts import DatasetError,SplitBundle
from sentinel.url_ml import training as legacy
from sentinel.url_ml.provenance import validate_provenance
from .compat import development_bundle
from .contracts import ResearchRun
from .protocol import choose_components
from .storage import manifest_hash,sanitized

def _bound(splits,config,parser):
    bundle=development_bundle(splits)
    if splits.manifest["config_sha256"]!=manifest_hash(config) or bundle.manifest["provenance"]["psl_sha256"]!=parser.psl_sha256: raise DatasetError("v2_training_identity_mismatch")
    return bundle

def component_pilot_rows(splits,maximum=2000):
    groups=defaultdict(list)
    for row in splits.development.partitions["train"]: groups[splits.component_by_case[row.case_id]].append(row)
    selected,skipped=choose_components(groups,maximum,42); rows=tuple(row for key in selected for row in groups[key])
    if not rows or {r.label for r in rows}!={0,1}: raise DatasetError("pilot_insufficient_classes_or_component_budget")
    return rows

def pilot_v2(splits,config,parser):
    bundle=_bound(splits,config,parser); rows=component_pilot_rows(splits,config["training"]["pilot_max_rows"])
    subset=SplitBundle({**bundle.partitions,"train":rows},bundle.manifest)
    try: report=legacy.resource_pilot(subset,config["training"],parser)
    except DatasetError as exc: raise DatasetError(exc.reason,sanitized(exc.diagnostics)) from None
    return {**report,"schema":"url-pilot-v2","component_count":len({splits.component_by_case[r.case_id] for r in rows}),"protocol_sha256":manifest_hash(splits.manifest)}

def _operating_points(model,validation,budgets):
    import numpy as np
    from sentinel.url_ml.metrics import choose_threshold,point_metrics
    scores=legacy.raw_scores(model,[r.url for r in validation]); labels=np.asarray([r.label for r in validation])
    return {str(budget):{"raw_threshold":threshold,"validation":point_metrics(labels,scores,threshold)}
      for budget in budgets for threshold in [choose_threshold(labels,scores,budget)]}

def train_v2(splits,config,parser):
    from .format_baseline import FEATURE_NAMES,build_format_pipeline
    bundle=_bound(splits,config,parser); settings=config["training"]
    run=legacy.train_run(bundle,settings,parser)
    if set(run.selection.branch_candidates)!={"char_tfidf","lexical_hgb"}: raise DatasetError("v2_comparison_branch_unavailable",{"configurations":run.selection.report["configurations"]})
    run.provenance["training_config_sha256"]=manifest_hash(run.provenance["training_config"])
    validate_provenance(run.provenance,stage="artifact")
    validation=bundle.partitions["validation"]
    run.selection.report["sensitivity"]={branch:_operating_points(candidate[0],validation,settings["sensitivity_budgets"]) for branch,candidate in run.selection.branch_candidates.items()}
    run.selection.report["protocol_sha256"]=manifest_hash(splits.manifest)
    try:
        model,record=legacy.fit_candidate(bundle.partitions["train"],"format_only",{},parser,settings["native_threads"],settings["max_peak_bytes"],pipeline_factory=build_format_pipeline)
    except Exception as exc:
        raise DatasetError("format_diagnostic_fit_failed",sanitized({"error_type":type(exc).__name__,"error_message":str(exc),"configurations":run.selection.report["configurations"]})) from None
    if model is None or record["status"]!="ok": raise DatasetError("format_diagnostic_fit_failed",sanitized({"resources":record,"configurations":run.selection.report["configurations"]}))
    diagnostic={"schema":"url-format-diagnostic-v2","feature_names":FEATURE_NAMES,"eligible_for_deployment":False,"resources":record,
      "sensitivity":_operating_points(model,validation,settings["sensitivity_budgets"]),"calibration":"unavailable_diagnostic_only"}
    return ResearchRun(run,model,diagnostic,splits.manifest)
