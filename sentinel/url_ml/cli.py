"""Explicit research commands; startup never acquires data or trains models."""
import argparse
import json
import statistics
import time
from pathlib import Path
from .contracts import DatasetError

def _load_root(root):
    from .source import read_json,verify_files,load_dataset
    from .urls import UrlParser
    from .splits import load_splits
    acquisition=read_json(root / "raw" / "acquisition.json")
    verify_files(root / "raw",acquisition["files"])
    parser=UrlParser(root / "raw" / "suffix.dat")
    dataset=load_dataset(root / "audited",parser)
    if dataset.manifest["source_sha256"]!=acquisition["files"]["source.csv"]: raise DatasetError("acquisition_dataset_mismatch")
    splits=load_splits(dataset,root / "splits")
    return parser,dataset,splits

def _evaluate(run,splits,artifact):
    import numpy as np
    from .contracts import Selection,Calibration,RunBundle
    from .metrics import evaluate_frozen,grouped_metrics
    from .training import rule_predictions
    from .splits import manifest_hash
    if run.provenance["split_manifest_sha256"]!=manifest_hash(splits.manifest): raise DatasetError("artifact_split_mismatch")
    if any(run.provenance[k]!=v for k,v in splits.manifest["provenance"].items()): raise DatasetError("artifact_source_mismatch")
    rows=splits.partitions["test"]
    selected=evaluate_frozen(run,rows,run.provenance["seed"]); comparison={}
    for branch,(model,threshold,params,record,rank) in run.selection.branch_candidates.items():
        if branch==run.selection.branch: comparison[branch]=selected
        else:
            other=RunBundle(Selection(model,branch,threshold,params,run.selection.report),
                            Calibration("unavailable",None,None,None,{"reason":"only_selected_model_calibrated"}),run.provenance)
            comparison[branch]=evaluate_frozen(other,rows,run.provenance["seed"])
    scores=np.asarray(rule_predictions(rows),dtype=float)
    comparison["phase0_rules"]=grouped_metrics([r.label for r in rows],scores,.5,[r.domain_group for r in rows],
                                             replicates=run.selection.report.get("bootstrap_replicates",1000),seed=run.provenance["seed"])
    from .service import UrlModelService
    cold_start=time.perf_counter(); service=UrlModelService(artifact)
    service.assess(rows[0].url); cold=time.perf_counter()-cold_start
    timings=[]
    for row in rows[:100]:
        started=time.perf_counter(); result=service.assess(row.url); timings.append(time.perf_counter()-started)
        if result.state!="complete": raise DatasetError("latency_assessment_failed")
    latency={"cold_load_and_first_seconds":cold,"warm_count":len(timings),"warm_median_seconds":statistics.median(timings),
             "warm_p95_seconds":float(np.percentile(timings,95)),"scope":"single URL, local CPU"}
    return {"schema":"url-final-evaluation-v1","artifact_manifest_sha256":run.provenance["artifact_manifest_sha256"],
            "source_provenance":{k:run.provenance[k] for k in ("source_sha256","derived_sha256","psl_sha256","split_manifest_sha256")},
            "selected_branch":run.selection.branch,"selected":selected,"comparison":comparison,"latency":latency,
            "selection_report":run.selection.report,"calibration":run.calibration.report,
            "limitations":["Historical single-source URL annotations, not live-site verification.",
                           "URL-only benchmark does not establish message-URL fusion benefit.",
                           "Phase 0 rule flag means any structural warning; it is a descriptive baseline.",
                           "Prevalence scenarios assume unchanged true/false positive rates.",
                           "No test-driven tuning or retraining was performed."]}

def final_card(report):
    m=report["selected"]
    return f"""# Sentinel URL-only final benchmark

Artifact manifest SHA-256: `{report['artifact_manifest_sha256']}`.
Selected model: **{report['selected_branch']}**, on validation only.
Final test: {m['rows']} URLs, {m['groups']} domain groups, threshold {m['raw_threshold']}.
Precision {m['precision']}, recall {m['recall']}, F1 {m['f1']}, actual FPR {m['fpr']}.
Calibration status: {m['calibration_status']}; Brier {m['brier']}, ECE {m['ece']}.
The JSON report contains both trained baselines, fixed rules and 1,000 whole-domain
bootstrap intervals. PR area is reported as average precision.

This historical, single-source result is not evidence of current deployment accuracy,
identity detection, contextual harassment detection or message-plus-URL fusion benefit.
A not-flagged URL does not establish safety. Probabilities refer to this benchmark.
"""

def _save_failure(root,command,diagnostics):
    from datetime import datetime,timezone
    from uuid import uuid4
    directory=Path(root) / "failed-runs"
    directory.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path=directory / f"{command}-{stamp}-{uuid4().hex}.json"
    with path.open("x",encoding="utf-8") as f:
        f.write(json.dumps(diagnostics,indent=2,sort_keys=True,allow_nan=False)+"\n")
    return str(path.resolve())


def main(argv=None):
    p=argparse.ArgumentParser(description="Sentinel URL-only research workflow")
    commands=p.add_subparsers(dest="command",required=True)
    for name in ("fetch","audit","split","pilot","train","evaluate","predict"):
        s=commands.add_parser(name)
        if name!="predict": s.add_argument("--root",type=Path,required=True)
        if name in ("audit","split","pilot","train"): s.add_argument("--config",type=Path,default=Path("configs/url-ml-v1.json"))
        if name in ("train","evaluate","predict"): s.add_argument("--artifact",type=Path,required=True)
        if name=="train": s.add_argument("--version",required=True)
        if name=="evaluate": s.add_argument("--out",type=Path,required=True)
        if name=="predict": s.add_argument("--url",required=True)
    args=p.parse_args(argv)
    try:
        from .source import fetch_sources,import_phiusiil,load_dataset,write_json,read_json,verify_files
        if args.command=="fetch": result=fetch_sources(args.root)
        elif args.command=="predict":
            from .service import UrlModelService
            result=UrlModelService(args.artifact).assess(args.url).to_dict()
        elif args.command=="audit":
            from .urls import UrlParser
            raw=args.root / "raw"; acquisition=read_json(raw / "acquisition.json"); verify_files(raw,acquisition["files"])
            parser=UrlParser(raw / "suffix.dat")
            result=import_phiusiil(raw / "source.csv",parser,args.root / "audited").manifest
        elif args.command=="split":
            from .urls import UrlParser
            from .splits import freeze_splits
            config=read_json(args.config); parser=UrlParser(args.root / "raw" / "suffix.dat")
            result=freeze_splits(load_dataset(args.root / "audited",parser),args.root / "splits",config["seed"]).manifest
        else:
            if args.command=="train" and args.artifact.exists(): raise DatasetError("output_exists")
            if args.command=="evaluate" and (args.out.exists() or args.out.with_suffix(".md").exists()): raise DatasetError("output_exists")
            if args.command=="pilot" and (args.root / "pilot.json").exists(): raise DatasetError("output_exists")
            parser,dataset,splits=_load_root(args.root)
            if args.command=="pilot":
                from .training import resource_pilot
                result=resource_pilot(splits,read_json(args.config),parser)
                write_json(args.root / "pilot.json",result)
                result={k:v for k,v in result.items() if k!="case_ids"}
            elif args.command=="train":
                from .training import train_run
                from .artifacts import export_artifact
                result=export_artifact(train_run(splits,read_json(args.config),parser),parser,args.artifact,args.version)
            else:
                from .artifacts import load_artifact
                result=_evaluate(load_artifact(args.artifact),splits,args.artifact)
                args.out.parent.mkdir(parents=True,exist_ok=True)
                with args.out.open("x",encoding="utf-8") as f: f.write(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
                with args.out.with_suffix(".md").open("x",encoding="utf-8") as f: f.write(final_card(result))
        print(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
        return 0
    except (DatasetError,OSError,ImportError,ValueError,KeyError) as error:
        result={"error":getattr(error,"reason",type(error).__name__)}
        diagnostics=getattr(error,"diagnostics",None)
        if diagnostics is not None:
            try: result["diagnostic_path"]=_save_failure(args.root,args.command,diagnostics)
            except (OSError,ValueError) as save_error:
                result.update({"diagnostic_error":type(save_error).__name__,"diagnostics":diagnostics})
        print(json.dumps(result,allow_nan=False)); return 2

if __name__=="__main__": raise SystemExit(main())
