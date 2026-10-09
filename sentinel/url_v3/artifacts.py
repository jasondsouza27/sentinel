"""V3 research metadata checked before any trusted local pickle is loaded."""
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_ml.provenance import validate_provenance
from sentinel.url_v2.contracts import ResearchRun
from sentinel.url_v2.storage import manifest_hash,read_json,sha256,verify_files
from .contracts import ARTIFACT_SCHEMA,PROTOCOL_SCHEMA,DIAGNOSTIC_SCHEMA,MENDELEY_ID

SIDECARS={"protocol.json","diagnostic.json","diagnostic.joblib"}
FEATURE_NAMES=["https","www_host","non_root_path","query_present"]

def _resources(record):
    if (not isinstance(record,dict) or record.get("status")!="ok" or type(record.get("native_threads")) is not int or
        record["native_threads"]!=4 or record.get("max_peak_bytes")!=8589934592):
        raise DatasetError("v3_artifact_fit_resources_invalid")
    for field in ("peak_bytes","observed_tree_rss_peak_bytes","conservative_tree_peak_bytes"):
        value=record.get(field)
        if type(value) is not int or not 0<value<=8589934592: raise DatasetError("v3_artifact_fit_resources_invalid")
    if not record["observed_tree_rss_peak_bytes"]<=record["conservative_tree_peak_bytes"]<=record["peak_bytes"]:
        raise DatasetError("v3_artifact_fit_resources_invalid")

def validate_research_metadata(provenance,protocol,diagnostic,selection,baselines):
    try: _validate(provenance,protocol,diagnostic,selection,baselines)
    except DatasetError: raise
    except (KeyError,TypeError,ValueError,AttributeError):
        raise DatasetError("v3_artifact_research_metadata_invalid") from None

def _validate(provenance,protocol,diagnostic,selection,baselines):
    if any(not isinstance(v,dict) for v in (provenance,protocol,diagnostic,selection,baselines)):
        raise DatasetError("v3_artifact_research_metadata_invalid")
    from sentinel.url_ml import urls
    from sentinel.url_ml.artifacts import _threshold
    from sentinel.url_ml.training import candidate_grid
    validate_provenance(provenance,stage="artifact")
    if provenance.get("provenance_schema")!="url-provenance-v3" or protocol.get("schema")!=PROTOCOL_SCHEMA:
        raise DatasetError("v3_artifact_schema_pair_invalid")
    if manifest_hash(protocol)!=provenance["protocol_sha256"]: raise DatasetError("v3_artifact_protocol_mismatch")
    for field in ("source_catalog_sha256","parser_code_sha256","psl_sha256","config_sha256",
                  "parent_v2_protocol_sha256","protected_domains_sha256"):
        if protocol.get(field)!=provenance[field]: raise DatasetError("v3_artifact_digest_mismatch")
    if protocol.get("audit_manifest_sha256")!=provenance["dataset_manifest_sha256"]:
        raise DatasetError("v3_artifact_audit_digest_mismatch")
    if provenance["parser_code_sha256"]!=sha256(Path(urls.__file__)): raise DatasetError("v3_artifact_parser_code_mismatch")
    names={"train","validation","calibration","primary","supplemental"}
    if (set(protocol.get("tracks",{}))!=names or protocol.get("training_ready") is not True or
        set(protocol.get("source_development",{}))!={"phreshphish",MENDELEY_ID} or
        any(r.get("status")!="available" for r in (protocol["development"],*protocol["tracks"].values(),*protocol["source_development"].values()))):
        raise DatasetError("v3_artifact_support_or_tracks_invalid")
    settings=provenance["training_config"]
    if settings.get("native_threads")!=4 or settings.get("max_peak_bytes")!=8589934592 or settings.get("sensitivity_budgets")!=[.05,.01]:
        raise DatasetError("v3_artifact_training_limits_invalid")
    if (diagnostic.get("schema")!=DIAGNOSTIC_SCHEMA or diagnostic.get("feature_names")!=FEATURE_NAMES or
        diagnostic.get("eligible_for_deployment") is not False or diagnostic.get("calibration")!="unavailable_diagnostic_only"):
        raise DatasetError("v3_artifact_diagnostic_contract_invalid")
    _resources(diagnostic.get("resources"))
    if set(baselines)!={"char_tfidf","lexical_hgb"}: raise DatasetError("v3_artifact_branches_missing")
    if selection.get("protocol_sha256")!=provenance["protocol_sha256"] or set(selection.get("sensitivity",{}))!=set(baselines):
        raise DatasetError("v3_artifact_sensitivity_invalid")
    grid=candidate_grid(settings); records=selection.get("configurations")
    if not isinstance(records,list) or len(records)!=len(grid): raise DatasetError("v3_artifact_grid_invalid")
    for i,((branch,params),record) in enumerate(zip(grid,records)):
        if record.get("branch")!=branch or record.get("params")!=params or record.get("configuration_index")!=i:
            raise DatasetError("v3_artifact_grid_invalid")
        if record.get("status")=="ok": _resources(record)
    for branch,entry in baselines.items():
        matching=[r for r in records if r["branch"]==branch and r["status"]=="ok" and r["params"]==entry["params"] and r["raw_threshold"]==entry["raw_threshold"]]
        if not matching: raise DatasetError("v3_artifact_baseline_not_fitted")
    for branch,points in (*selection["sensitivity"].items(),("format_only",diagnostic.get("sensitivity",{}))):
        if set(points)!={"0.05","0.01"}: raise DatasetError("v3_artifact_sensitivity_invalid")
        for point in points.values():
            if not isinstance(point,dict) or "raw_threshold" not in point: raise DatasetError("v3_artifact_sensitivity_invalid")
            _threshold(point["raw_threshold"])
        if branch in baselines and points["0.05"]["raw_threshold"]!=baselines[branch]["raw_threshold"]:
            raise DatasetError("v3_artifact_threshold_mismatch")

def validate_selected_metadata(selected,report):
    try:
        index=report["selected_configuration"]
        if type(index) is not int or not 0<=index<len(report["configurations"]): raise DatasetError("v3_artifact_selected_index_invalid")
        record=report["configurations"][index]
        if (record["status"]!="ok" or selected["branch"]!=record["branch"] or selected["params"]!=record["params"] or
            selected["raw_threshold"]!=record["raw_threshold"]):
            raise DatasetError("v3_artifact_selected_record_mismatch")
    except DatasetError: raise
    except (TypeError,KeyError): raise DatasetError("v3_artifact_selected_record_invalid") from None

def validate_research_sidecars(root,manifest):
    from sentinel.url_ml.artifacts import REQUIRED_FILES
    root=Path(root)
    if {p.name for p in root.iterdir()}!=REQUIRED_FILES|SIDECARS|{"manifest.json"}:
        raise DatasetError("v3_artifact_directory_membership_invalid")
    protocol=read_json(root/"protocol.json"); diagnostic=read_json(root/"diagnostic.json"); report=read_json(root/"selection.json")
    validate_research_metadata(manifest["provenance"],protocol,diagnostic,report,manifest["baselines"])
    validate_selected_metadata(manifest["selected"],report)
    return protocol,diagnostic

def export_v3_artifact(research,parser,output_dir,version):
    if research.run.provenance.get("provenance_schema")!="url-provenance-v3":
        raise DatasetError("v3_artifact_provenance_required")
    from sentinel.url_ml.artifacts import export_artifact
    payload={"format_model":research.format_model,"format_report":research.format_report,"protocol":research.protocol}
    return export_artifact(research.run,parser,output_dir,version,research_payload=payload)

def load_v3_artifact(path):
    root=Path(path); manifest=read_json(root/"manifest.json")
    if manifest.get("schema")!=ARTIFACT_SCHEMA: raise DatasetError("v3_artifact_schema_required")
    from sentinel.url_ml.artifacts import load_artifact
    run=load_artifact(root); verify_files(root,manifest["files"])
    protocol,diagnostic=validate_research_sidecars(root,manifest)
    import joblib
    from sklearn.pipeline import Pipeline
    from sentinel.url_ml.urls import UrlParser
    model=joblib.load(root/"diagnostic.joblib")
    if (not isinstance(model,Pipeline) or set(model.named_steps)!={"canonical","format","classifier"} or
        set(model.classes_)!={0,1} or model.named_steps["format"].get_feature_names_out().tolist()!=FEATURE_NAMES or
        model.named_steps["classifier"].n_features_in_!=4):
        raise DatasetError("v3_artifact_diagnostic_pipeline_invalid")
    parser=UrlParser(root/"suffix.dat")
    for step in model.named_steps.values():
        if hasattr(step,"parser"): step.parser=parser
    return ResearchRun(run,model,diagnostic,protocol)
