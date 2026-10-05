"""Checked immutable persistence for locally trusted research artifacts.

Hashes detect corruption; they do not authenticate a pickle from another person.
Only load directories produced locally by this workflow. There is no upload API.
"""
import math
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict
from importlib.metadata import version as dependency_version
from pathlib import Path
from .contracts import DatasetError,RunBundle,Selection,Calibration,ARTIFACT_SCHEMA,FEATURE_SCHEMA
from .source import new_directory,publish_directory,write_json,read_json,verify_files,sha256,PARSER_VERSION
from .splits import manifest_hash

REQUIRED_FILES={"pipeline.joblib","suffix.dat","calibration.json","selection.json","requirements.lock","model-card.md"}
HASH_FIELDS=("source_sha256","psl_sha256","derived_sha256","dataset_manifest_sha256","split_manifest_sha256")
BRANCHES={"char_tfidf","lexical_hgb"}

def runtime_versions():
    lock=Path(__file__).resolve().parents[2] / "requirements-ml-win-py311.lock.txt"
    names=[line.split("==")[0] for line in lock.read_text(encoding="utf-8").splitlines() if "==" in line]
    return {name:dependency_version(name) for name in names}

def _threshold(value):
    if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1):
        raise DatasetError("invalid_threshold")

def _validate_metadata(m):
    if m.get("schema")!=ARTIFACT_SCHEMA or m.get("feature_schema")!=FEATURE_SCHEMA or m.get("parser_version")!=PARSER_VERSION:
        raise DatasetError("artifact_schema_mismatch")
    if m.get("trusted_local_only") is not True or m.get("labels")!={"0":"legitimate_url","1":"phishing_url"}:
        raise DatasetError("artifact_label_or_trust_contract")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}",m.get("version", "")):
        raise DatasetError("artifact_version_invalid")
    if m.get("python_minor")!=f"{sys.version_info.major}.{sys.version_info.minor}" or m["python_minor"]!="3.11":
        raise DatasetError("artifact_python_mismatch")
    if m.get("platform")!={"system":platform.system(),"machine":platform.machine()}: raise DatasetError("artifact_platform_mismatch")
    if m.get("dependencies")!=runtime_versions(): raise DatasetError("artifact_dependency_mismatch")
    if set(m.get("files",{}))!=REQUIRED_FILES: raise DatasetError("artifact_required_files")
    provenance=m.get("provenance",{})
    if any(not re.fullmatch(r"[0-9a-f]{64}",provenance.get(name,"")) for name in HASH_FIELDS):
        raise DatasetError("artifact_provenance_invalid")
    if provenance.get("psl_sha256")!=m["files"]["suffix.dat"]: raise DatasetError("artifact_suffix_mismatch")
    selected=m.get("selected",{})
    if selected.get("branch") not in BRANCHES or not isinstance(selected.get("params"),dict) or "raw_threshold" not in selected:
        raise DatasetError("artifact_selection_invalid")
    _threshold(selected["raw_threshold"])
    baselines=m.get("baselines",{})
    if selected["branch"] not in baselines or not set(baselines)<=BRANCHES: raise DatasetError("artifact_baselines_invalid")
    for entry in baselines.values():
        if not isinstance(entry,dict) or "raw_threshold" not in entry or not isinstance(entry.get("params"),dict): raise DatasetError("artifact_baselines_invalid")
        _threshold(entry["raw_threshold"])

def export_artifact(run,parser,output_dir:Path,version):
    if Path(output_dir).exists(): raise DatasetError("output_exists")
    import joblib
    dependencies=runtime_versions()
    candidates=run.selection.branch_candidates or {run.selection.branch:(run.selection.model,run.selection.raw_threshold,run.selection.config,{},())}
    models={branch:candidate[0] for branch,candidate in candidates.items()}
    baselines={branch:{"raw_threshold":candidate[1],"params":candidate[2]} for branch,candidate in candidates.items()}
    temp=new_directory(output_dir)
    try:
        shutil.copyfile(parser.psl_path,temp / "suffix.dat")
        joblib.dump({"selected":run.selection.model,"baselines":models},temp / "pipeline.joblib",compress=3)
        write_json(temp / "calibration.json",asdict(run.calibration))
        write_json(temp / "selection.json",run.selection.report)
        (temp / "requirements.lock").write_text("".join(f"{name}=={value}\n" for name,value in sorted(dependencies.items())),encoding="utf-8")
        card=f"""# Sentinel URL model {version}

Research candidate: {run.selection.branch}. Label 1 = historical source phishing annotation.
Selected on validation with FPR budget 5%; raw threshold = {run.selection.raw_threshold}.
Calibration status = {run.calibration.status}; numerical probabilities, when present,
apply to the source benchmark distribution. Live confidence is unvalidated.

No submitted website, DNS lookup or redirect is fetched. Not flagged does not establish
safety. Reputation, site behaviour and account history are unavailable to this model.
The source URL-string experiment is distinct from paired-message fusion research.
Final test results must be written outside this immutable artifact with its manifest hash.

Trusted local joblib only; checksums detect byte changes, not a malicious replacement.
"""
        (temp / "model-card.md").write_text(card,encoding="utf-8")
        try:
            git=subprocess.run(["git","rev-parse","HEAD"],cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True,check=True).stdout.strip()
        except (OSError,subprocess.CalledProcessError): git="unavailable"
        m={"schema":ARTIFACT_SCHEMA,"feature_schema":FEATURE_SCHEMA,"parser_version":PARSER_VERSION,"version":version,
           "labels":{"0":"legitimate_url","1":"phishing_url"},"trusted_local_only":True,"git_commit":git,
           "python_minor":f"{sys.version_info.major}.{sys.version_info.minor}","python_version":platform.python_version(),
           "platform":{"system":platform.system(),"machine":platform.machine()},"dependencies":dependencies,
           "provenance":run.provenance,"selected":{"branch":run.selection.branch,"params":run.selection.config,"raw_threshold":run.selection.raw_threshold},
           "baselines":baselines,"files":{name:sha256(temp/name) for name in sorted(REQUIRED_FILES)}}
        _validate_metadata(m); write_json(temp / "manifest.json",m); publish_directory(temp,output_dir)
        return m
    finally:
        if temp.exists(): shutil.rmtree(temp)

def _rebind(model,parser,branch):
    from sklearn.pipeline import Pipeline
    if not isinstance(model,Pipeline) or set(model.classes_)!={0,1}: raise DatasetError("artifact_pipeline_invalid")
    required={"canonical","tfidf","classifier"} if branch=="char_tfidf" else {"lexical","classifier"}
    if set(model.named_steps)!=required: raise DatasetError("artifact_pipeline_invalid")
    for step in model.named_steps.values():
        if hasattr(step,"parser"): step.parser=parser
    return model

def load_artifact(path:Path):
    root=Path(path); m=read_json(root / "manifest.json")
    try: _validate_metadata(m)
    except (TypeError,KeyError): raise DatasetError("artifact_metadata_invalid") from None
    verify_files(root,m["files"])
    expected_lock="".join(f"{name}=={value}\n" for name,value in sorted(m["dependencies"].items()))
    if (root / "requirements.lock").read_text(encoding="utf-8")!=expected_lock: raise DatasetError("artifact_lock_mismatch")
    try:
        calibration=Calibration(**read_json(root / "calibration.json"))
        if calibration.status not in ("available","unavailable"): raise DatasetError("artifact_calibration_invalid")
        _threshold(calibration.threshold)
        if calibration.status=="available":
            from .calibration import apply_calibration
            mapped=apply_calibration(calibration,[m["selected"]["raw_threshold"] if m["selected"]["raw_threshold"] is not None else .5])
            if m["selected"]["raw_threshold"] is None:
                if calibration.threshold is not None: raise DatasetError("artifact_calibration_threshold")
            elif calibration.threshold is None or abs(float(mapped[0])-calibration.threshold)>1e-10: raise DatasetError("artifact_calibration_threshold")
        elif any(v is not None for v in (calibration.slope,calibration.intercept,calibration.threshold)): raise DatasetError("artifact_calibration_invalid")
        from .urls import UrlParser
        parser=UrlParser(root / "suffix.dat")
        report=read_json(root / "selection.json")
    except (ValueError,TypeError,KeyError): raise DatasetError("artifact_metadata_invalid") from None
    # Deserialization is deliberately last, after all integrity/compatibility checks.
    import joblib
    payload=joblib.load(root / "pipeline.joblib")
    if not isinstance(payload,dict) or set(payload)!={"selected","baselines"} or set(payload["baselines"])!=set(m["baselines"]):
        raise DatasetError("artifact_payload_invalid")
    selected=m["selected"]
    model=_rebind(payload["selected"],parser,selected["branch"])
    selection=Selection(model,selected["branch"],selected["raw_threshold"],selected["params"],report)
    selection.branch_candidates={branch:(_rebind(payload["baselines"][branch],parser,branch),entry["raw_threshold"],entry["params"],{},()) for branch,entry in m["baselines"].items()}
    return RunBundle(selection,calibration,{**m["provenance"],"artifact_version":m["version"],"artifact_manifest_sha256":manifest_hash(m),"git_commit":m["git_commit"]})
