"""User-invoked, lazy stages for the immutable Sentinel URL-v3 study."""
import argparse
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2.storage import manifest_hash,read_json,save_failure,sha256,write_json
from .contracts import load_config

class AggregateWriter(io.TextIOBase):
    def __init__(self,target): self.target=target; self.pending=""
    def write(self,value):
        self.pending+=value
        while "\n" in self.pending:
            line,self.pending=self.pending.split("\n",1)
            try: result=json.loads(line)
            except ValueError: result=line
            self.target.write(json.dumps(_safe(result),allow_nan=False)+"\n"); self.target.flush()
        return len(value)
    def flush(self): self.target.flush()

def _safe(value):
    from .training import safe_diagnostics
    return safe_diagnostics(value)

def _paths(args):
    """Establish write separation before creating config, diagnostics or outputs."""
    if args.command=="predict": return
    root=args.root.resolve(); args.root=root
    old=getattr(args,"v2_root",None)
    binding=root/"binding/manifest.json"
    if old is None and binding.is_file(): old=Path(read_json(binding)["v2_root"])
    if old is not None:
        old=old.resolve()
        if root.is_relative_to(old) or old.is_relative_to(root): raise DatasetError("v2_input_read_only")
    elif (root/"sources/phreshphish").exists():
        raise DatasetError("v2_input_read_only")
    for value in (getattr(args,"output",None),getattr(args,"artifact",None) if args.command=="train" else None):
        if value is None: continue
        path=value.resolve()
        if old is not None and (path.is_relative_to(old) or old.is_relative_to(path)): raise DatasetError("v2_input_read_only")
        if root.is_relative_to(path) or any(path.is_relative_to(root/name) for name in ("binding","sources","audited","protocol","final-access")):
            raise DatasetError("v3_output_overlaps_input")
    args._diagnostics_allowed=True

def _prepare(args,config):
    from sentinel.url_ml.urls import UrlParser
    root=args.root
    stored=root/"config.json"
    if stored.exists():
        if read_json(stored)!=config: raise DatasetError("v3_stored_config_mismatch")
    else:
        if args.command!="bind-v2": raise DatasetError("v3_binding_stage_required")
        root.mkdir(parents=True,exist_ok=True)
        with stored.open("x",encoding="utf-8",newline="\n") as f: json.dump(config,f,sort_keys=True,allow_nan=False); f.write("\n")
    psl=root/"sources/suffix.dat"
    if not psl.exists():
        if args.command!="bind-v2": raise DatasetError("v3_frozen_suffix_missing")
        if not args.psl.is_file() or sha256(args.psl)!=config["parser"]["psl_sha256"]: raise DatasetError("v3_supplied_suffix_invalid")
        psl.parent.mkdir(parents=True,exist_ok=True)
        with args.psl.open("rb") as source,psl.open("xb") as dest: shutil.copyfileobj(source,dest)
    if sha256(psl)!=config["parser"]["psl_sha256"]: raise DatasetError("v3_frozen_suffix_changed")
    return UrlParser(psl)

def _load(root,config,parser,*,protocol=True):
    from .binding import load_v2_binding
    from .mendeley import load_mendeley
    from .sources import joint_catalog
    from sentinel.url_v2.audit import load_audit
    binding=load_v2_binding(root/"binding",config,parser)
    source=load_mendeley(root/"sources/mendeley",config); catalog=joint_catalog(binding,source)
    audit=load_audit(root/"audited",catalog,parser)
    if not protocol: return binding,catalog,audit
    from .protocol import load_protocol
    return load_protocol(audit,catalog,binding,root/"protocol",config,study_root=root)

def _execute(args,config):
    command=args.command
    if command=="predict":
        from sentinel.url_ml.service import UrlModelService
        service=UrlModelService(args.artifact)
        if service.health()["state"]!="ready": raise DatasetError("artifact_unavailable",service.health())
        return service.assess(args.url).to_dict()
    root=args.root
    targets={"bind-v2":root/"binding","audit":root/"audited","freeze":root/"protocol","pilot":root/"runs/pilot.json"}
    if command in targets and targets[command].exists(): raise DatasetError("output_exists")
    if command=="train" and args.artifact.exists(): raise DatasetError("output_exists")
    if getattr(args,"output",None) is not None and args.output.exists(): raise DatasetError("output_exists")
    parser=_prepare(args,config)
    if command=="bind-v2":
        from .binding import bind_v2
        binding=bind_v2(args.v2_root,root/"binding",config,parser); m=binding.manifest
        return {k:m[k] for k in ("schema","parent_v2_protocol_sha256","protected_domains_sha256","protected_domain_groups",
                                "original_primary_cases","historical_training_ready","legacy_transfer_metering")}
    if command=="acquire-mendeley":
        if not (root/"binding/manifest.json").is_file(): raise DatasetError("v3_binding_stage_required")
        from .mendeley import acquire_mendeley
        source=acquire_mendeley(root/"sources/mendeley",config); m=source.manifest
        return {"schema":m["schema"],"source_catalog_sha256":manifest_hash(m),"observations":m["rows"],
                "acquisition":{"measured_received_body_bytes":m["measured_received_body_bytes"],
                               "interrupted_body_bytes_upper_bound":m["interrupted_body_bytes_upper_bound"],
                               "full_file_checksum_verified":m["full_file_checksum_verified"]},"csv_sha256":config["sources"]["mendeley"]["sha256"]}
    if command=="audit":
        from .binding import load_v2_binding
        from .sources import audit_v3
        binding=load_v2_binding(root/"binding",config,parser)
        m=audit_v3(binding,root/"sources/mendeley",config,parser,root/"audited").manifest
        return {k:m[k] for k in ("schema","input_observations","included_observations","included_rows","excluded",
                   "duplicate_observations","class_counts","format_counts","date_status_counts","source_observation_counts")}|{"audit_manifest_sha256":manifest_hash(m)}
    if command=="freeze":
        from .protocol import freeze_protocol
        binding,catalog,audit=_load(root,config,parser,protocol=False)
        splits=freeze_protocol(audit,catalog,binding,config,root/"protocol",study_root=root); args._splits=splits
        result={"schema":splits.manifest["schema"],"protocol_sha256":manifest_hash(splits.manifest),
                "training_ready":splits.manifest["training_ready"],"metrics":None,"models_fitted":False,
                "tracks":splits.manifest["tracks"],"development":splits.manifest["development"],
                "source_development":splits.manifest["source_development"],"source_partitions":splits.manifest["source_partitions"]}
        if args.output is not None:
            from .evaluation import publish_research_status
            publish_research_status(splits,config,args.output,stage="freeze",
                                    status="ready" if result["training_ready"] else "unavailable",
                                    reason=None if result["training_ready"] else "v3_training_support_incomplete")
        return result
    splits=_load(root,config,parser); args._splits=splits
    if command=="pilot":
        from .training import pilot_v3
        report=pilot_v3(splits,config,parser); path=root/"runs/pilot.json"; path.parent.mkdir(exist_ok=True)
        with path.open("x",encoding="utf-8") as f: json.dump(report,f,sort_keys=True,allow_nan=False)
        return {k:report[k] for k in ("schema","status","rows","component_count","protocol_sha256","native_threads","max_peak_bytes")}|{
                "measurements":[{k:v for k,v in r.items() if k not in ("monitored_processes",)} for r in report["measurements"]]}
    if command=="train":
        from .training import train_v3
        from .artifacts import export_v3_artifact
        m=export_v3_artifact(train_v3(splits,config,parser),parser,args.artifact,args.version)
        return {"schema":m["schema"],"models_fitted":True,"version":m["version"],"selected":m["selected"],
                "artifact_manifest_sha256":manifest_hash(m),"protocol_sha256":m["provenance"]["protocol_sha256"]}
    if command=="evaluate":
        from .evaluation import evaluate_v3,publish_evaluation
        report=evaluate_v3(splits,config,parser,args.artifact); publish_evaluation(report,args.output)
        return {"schema":report["schema"],"status":report["status"],"artifact_manifest_sha256":report["artifact_manifest_sha256"],
                "protocol_sha256":report["protocol_sha256"],"tracks":{n:{"status":r["status"],"rows":r["rows"]} for n,r in report["tracks"].items()},
                "evaluation_sha256":sha256(args.output/"evaluation.json")}
    raise DatasetError("v3_command_unsupported")

def main(argv=None):
    parser=argparse.ArgumentParser(description="Sentinel URL v3 explicit research stages; no automatic fitting")
    commands=parser.add_subparsers(dest="command",required=True)
    for name in ("bind-v2","acquire-mendeley","audit","freeze","pilot","train","evaluate","predict"):
        stage=commands.add_parser(name)
        if name!="predict":
            stage.add_argument("--root",type=Path,required=True)
            stage.add_argument("--config",type=Path,default=Path("configs/url-ml-v3.json"))
            stage.add_argument("--psl",type=Path,default=Path("resources/url-v2-suffix.dat"))
            stage.add_argument("--output",type=Path,required=name=="evaluate")
        if name=="bind-v2": stage.add_argument("--v2-root",type=Path,required=True)
        if name in ("train","evaluate","predict"): stage.add_argument("--artifact",type=Path,required=True)
        if name=="train": stage.add_argument("--version",required=True)
        if name=="predict": stage.add_argument("--url",required=True)
    args=parser.parse_args(argv); config=None
    try:
        _paths(args)
        if sys.version_info[:2]!=(3,11): raise DatasetError("url_v3_requires_python311")
        config=load_config(args.config) if args.command!="predict" else None
        with contextlib.redirect_stdout(AggregateWriter(sys.stdout)): result=_execute(args,config)
        print(json.dumps(_safe(result),sort_keys=True,indent=2,allow_nan=False)); return 0
    except Exception as exc:
        reason=getattr(exc,"reason",type(exc).__name__)
        detail=_safe({"stage":args.command,"reason":reason,"error_type":type(exc).__name__,"error_message":str(exc),
                      "diagnostics":getattr(exc,"diagnostics",None)})
        result={"stage":args.command,"status":"failed","reason":reason,"diagnostic_saved":False}
        if getattr(args,"_diagnostics_allowed",False):
            try: save_failure(args.root,args.command,detail); result["diagnostic_saved"]=True
            except (OSError,ValueError): result["diagnostic_error"]="persistence_failed"
            if config is not None and args.output is not None and not args.output.exists():
                try:
                    from .evaluation import publish_research_status
                    report=publish_research_status(getattr(args,"_splits",None),config,args.output,stage=args.command,status="failed",reason=reason)
                    result.update(models_fitted=report["models_fitted"],metrics=None)
                except Exception as error: result["status_publication_error"]=getattr(error,"reason",type(error).__name__)
        print(json.dumps(_safe(result),sort_keys=True,allow_nan=False)); return 2

if __name__=="__main__": raise SystemExit(main())
