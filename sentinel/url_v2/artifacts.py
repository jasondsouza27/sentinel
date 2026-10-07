"""Research-only v2 sidecars, checked before shared or diagnostic deserialization."""
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_ml.provenance import validate_provenance
from .contracts import ARTIFACT_SCHEMA,PROTOCOL_SCHEMA,ResearchRun
from .storage import manifest_hash,read_json,sha256

SIDECARS={"protocol.json","diagnostic.json","diagnostic.joblib"}
FEATURE_NAMES=["https","www_host","non_root_path","query_present"]

def validate_research_metadata(provenance,protocol,diagnostic,selection,baselines):
    if any(not isinstance(v,dict) for v in (provenance,protocol,diagnostic,selection,baselines)): raise DatasetError("artifact_research_metadata_invalid")
    from sentinel.url_ml.artifacts import _threshold
    from sentinel.url_ml import urls
    validate_provenance(provenance,stage="artifact")
    if protocol.get("schema")!=PROTOCOL_SCHEMA or manifest_hash(protocol)!=provenance["protocol_sha256"]: raise DatasetError("artifact_protocol_mismatch")
    for field in ("source_catalog_sha256","parser_code_sha256","psl_sha256"):
        if protocol.get(field)!=provenance[field]: raise DatasetError("artifact_research_digest_mismatch")
    if provenance["parser_code_sha256"]!=sha256(Path(urls.__file__)): raise DatasetError("artifact_parser_code_mismatch")
    if diagnostic.get("schema")!="url-format-diagnostic-v2" or diagnostic.get("feature_names")!=FEATURE_NAMES or diagnostic.get("eligible_for_deployment") is not False: raise DatasetError("artifact_diagnostic_contract_invalid")
    if set(baselines)!={"char_tfidf","lexical_hgb"}: raise DatasetError("artifact_v2_branches_missing")
    if selection.get("protocol_sha256")!=provenance["protocol_sha256"] or set(selection.get("sensitivity",{}))!=set(baselines): raise DatasetError("artifact_sensitivity_contract_invalid")
    for name,points in list(selection["sensitivity"].items())+[("format_only",diagnostic.get("sensitivity",{}))]:
        if set(points)!={"0.05","0.01"}: raise DatasetError("artifact_sensitivity_contract_invalid")
        for point in points.values():
            if not isinstance(point,dict) or "raw_threshold" not in point: raise DatasetError("artifact_sensitivity_contract_invalid")
            _threshold(point["raw_threshold"])
        if name in baselines and points["0.05"]["raw_threshold"]!=baselines[name]["raw_threshold"]: raise DatasetError("artifact_selection_threshold_mismatch")
    resources=diagnostic.get("resources",{})
    if resources.get("status")!="ok" or resources.get("native_threads")!=4 or resources.get("max_peak_bytes")!=8589934592: raise DatasetError("artifact_diagnostic_resources_invalid")

def validate_research_sidecars(root,manifest):
    protocol=read_json(Path(root)/"protocol.json"); diagnostic=read_json(Path(root)/"diagnostic.json"); selection=read_json(Path(root)/"selection.json")
    validate_research_metadata(manifest["provenance"],protocol,diagnostic,selection,manifest["baselines"])
    return protocol,diagnostic

def export_v2_artifact(research,parser,output_dir,version):
    from sentinel.url_ml.artifacts import export_artifact
    payload={"format_model":research.format_model,"format_report":research.format_report,"protocol":research.protocol}
    return export_artifact(research.run,parser,output_dir,version,research_payload=payload)

def load_v2_artifact(path):
    root=Path(path); manifest=read_json(root/"manifest.json")
    if manifest.get("schema")!=ARTIFACT_SCHEMA: raise DatasetError("v2_artifact_schema_required")
    from sentinel.url_ml.artifacts import load_artifact
    run=load_artifact(root); protocol,diagnostic=validate_research_sidecars(root,manifest)
    import joblib
    from sklearn.pipeline import Pipeline
    from sentinel.url_ml.urls import UrlParser
    model=joblib.load(root/"diagnostic.joblib")
    if not isinstance(model,Pipeline) or set(model.named_steps)!={"canonical","format","classifier"} or set(model.classes_)!={0,1}: raise DatasetError("artifact_diagnostic_pipeline_invalid")
    if model.named_steps["format"].get_feature_names_out().tolist()!=FEATURE_NAMES or model.named_steps["classifier"].n_features_in_!=4: raise DatasetError("artifact_diagnostic_features_invalid")
    parser=UrlParser(root/"suffix.dat")
    for step in model.named_steps.values():
        if hasattr(step,"parser"): step.parser=parser
    return ResearchRun(run,model,diagnostic,protocol)
