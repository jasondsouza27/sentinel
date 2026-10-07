"""Explicit, lazy research stages; the normal application never calls these."""
import argparse
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path
from .contracts import DatasetError,load_config
from .storage import manifest_hash,read_json,sanitized,save_failure,sha256,write_json

class SanitizingWriter(io.TextIOBase):
    def __init__(self,target): self.target=target; self.pending=""
    def write(self,value):
        self.pending+=value
        while "\n" in self.pending:
            line,self.pending=self.pending.split("\n",1)
            try: result=sanitized(json.loads(line))
            except ValueError: result=sanitized(line)
            self.target.write(json.dumps(result,allow_nan=False)+"\n"); self.target.flush()
        return len(value)
    def flush(self): self.target.flush()

def _primary(root):
    from .catalog import load_catalog
    return load_catalog(root/"sources"/"phreshphish"/"catalog")

def _catalog(root):
    from .catalog import load_catalog,merge_catalogs
    primary=_primary(root); external_root=root/"sources"/"iscx"
    external=load_catalog(external_root) if external_root.exists() else None
    return merge_catalogs(primary,external),primary,external

def _parser(root,config):
    from sentinel.url_ml.urls import UrlParser
    psl=root/"sources"/"suffix.dat"
    if not psl.is_file() or sha256(psl)!=config["parser"]["psl_sha256"]: raise DatasetError("frozen_suffix_snapshot_missing_or_wrong")
    return UrlParser(psl)

def _load(root,config,*,protocol=True):
    from .audit import load_audit
    catalog,primary,external=_catalog(root); parser=_parser(root,config); audit=load_audit(root/"audited",catalog,parser)
    if not protocol: return catalog,parser,audit
    from .protocol import load_protocol
    return catalog,parser,audit,load_protocol(audit,catalog,root/"protocol",config)

def _execute(args,config):
    command=args.command; root=getattr(args,"root",None)
    if command=="predict":
        from sentinel.url_ml.service import UrlModelService
        return UrlModelService(args.artifact).assess(args.url).to_dict()
    if command=="catalog":
        from .catalog import fetch_phresh_catalog
        result=fetch_phresh_catalog(root/"sources"/"phreshphish"/"catalog",config)
        return {"schema":result.manifest["schema"],"source_catalog_sha256":manifest_hash(result.manifest),"source_files":len(result.files),"metadata_response_bytes":result.manifest["metadata_response_bytes"]}
    if command in ("project","project-pilot"):
        from .ranges import RangeSession
        from .projection import project_phresh
        pilot=command=="project-pilot"; purpose="pilot" if pilot else "full"; cache=root/"cache"/purpose
        output=root/"sources"/"phreshphish"/("projection-pilot" if pilot else "projection")
        if output.exists(): raise DatasetError("output_exists")
        resume=getattr(args,"resume",False)
        if cache.exists() and not resume and not pilot: raise DatasetError("projection_cache_exists_use_resume")
        catalog=_primary(root); session=RangeSession(catalog,cache,config,purpose=purpose)
        report=project_phresh(catalog,session,output,config,pilot=pilot)
        return {"schema":report["schema"],"status":report["status"],"purpose":report["purpose"],"rows":sum(s["rows"] for s in report["shards"]),"shards":len(report["shards"]),"response_bytes":report["transport"]["response_bytes"],"full_file_checksum_verified":False,"projection_sha256":manifest_hash(report)}
    if command=="admit-iscx":
        from .iscx import admit_iscx
        catalog=admit_iscx(args.mapping,root/"sources"/"iscx")
        return {"schema":catalog.manifest["schema"],"source_catalog_sha256":manifest_hash(catalog.manifest),"members":len(catalog.files),"excluded_categories":catalog.manifest["excluded_categories"]}
    if command=="audit":
        from .audit import audit_sources
        from .iscx import iter_iscx_observations
        from .projection import iter_phresh_observations
        if (root/"audited").exists(): raise DatasetError("output_exists")
        if not args.psl.is_file() or sha256(args.psl)!=config["parser"]["psl_sha256"]: raise DatasetError("frozen_suffix_snapshot_missing_or_wrong")
        target=root/"sources"/"suffix.dat"; target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if sha256(target)!=config["parser"]["psl_sha256"]: raise DatasetError("stored_suffix_snapshot_wrong")
        else:
            with args.psl.open("rb") as source,target.open("xb") as dest: shutil.copyfileobj(source,dest)
            if sha256(target)!=config["parser"]["psl_sha256"]: raise DatasetError("suffix_copy_hash_mismatch")
        catalog,primary,external=_catalog(root); parser=_parser(root,config)
        def observations():
            yield from iter_phresh_observations(root/"sources"/"phreshphish"/"projection",primary)
            if external is not None: yield from iter_iscx_observations(external,root/"sources"/"iscx")
        report=audit_sources(catalog,observations(),parser,root/"audited").manifest
        return {key:report[key] for key in ("schema","input_observations","included_observations","included_rows","excluded","duplicate_observations","class_counts","format_counts","date_status_counts")}|{"audit_manifest_sha256":manifest_hash(report)}
    if command=="freeze":
        from .protocol import freeze_protocol,assert_training_ready
        catalog,parser,audit=_load(root,config,protocol=False); splits=freeze_protocol(audit,catalog,config,root/"protocol")
        try: assert_training_ready(splits); ready=True
        except DatasetError: ready=False
        return {"schema":splits.manifest["schema"],"protocol_sha256":manifest_hash(splits.manifest),"training_ready":ready,"tracks":splits.manifest["tracks"],"development":splits.manifest["development"],"temporal":splits.manifest["temporal"],"cap_skipped_components":len(splits.manifest["cap_skipped_components"])}
    if command=="train" and args.artifact.exists(): raise DatasetError("output_exists")
    if command=="evaluate" and args.out.exists(): raise DatasetError("output_exists")
    if command=="evaluate" and ((args.v1_root is None)!=(args.v1_artifact is None)): raise DatasetError("v1_artifact_and_data_required_together")
    if command=="pilot" and (root/"runs"/"pilot.json").exists(): raise DatasetError("output_exists")
    catalog,parser,audit,splits=_load(root,config)
    if command=="pilot":
        from .training import pilot_v2
        report=pilot_v2(splits,config,parser); path=root/"runs"/"pilot.json"; path.parent.mkdir(exist_ok=True)
        with path.open("x",encoding="utf-8") as f: json.dump(report,f,sort_keys=True,allow_nan=False)
        return {key:report[key] for key in ("schema","status","rows","group_count","component_count","native_threads","max_peak_bytes","measurements","protocol_sha256")}
    if command=="train":
        from .training import train_v2
        from .artifacts import export_v2_artifact
        report=export_v2_artifact(train_v2(splits,config,parser),parser,args.artifact,args.version)
        return {"schema":report["schema"],"version":report["version"],"artifact_manifest_sha256":manifest_hash(report),"selected":report["selected"],"protocol_sha256":report["provenance"]["protocol_sha256"]}
    if command=="evaluate":
        from .artifacts import load_v2_artifact
        from .evaluation import evaluate_robustness,publish_evaluation
        v1_run=v1_data=None
        if args.v1_root is not None:
            from sentinel.url_ml.cli import _load_root
            from sentinel.url_ml.artifacts import load_artifact
            old_parser,dataset,old_splits=_load_root(args.v1_root); v1_run=load_artifact(args.v1_artifact); v1_data=(dataset,old_splits)
        research=load_v2_artifact(args.artifact); report=evaluate_robustness(research,splits,args.artifact,v1_run=v1_run,v1_data=v1_data)
        publish_evaluation(report,args.out)
        return {"schema":report["schema"],"artifact_manifest_sha256":report["artifact_manifest_sha256"],"protocol_sha256":report["protocol_sha256"],
          "tracks":{name:{"status":track["status"],"reasons":track["reasons"],"rows":track.get("rows",0)} for name,track in report["tracks"].items()},"evaluation_sha256":sha256(args.out/"evaluation.json")}
    raise DatasetError("unsupported_research_command")

def main(argv=None):
    parser=argparse.ArgumentParser(description="Sentinel URL v2 explicit research workflow")
    commands=parser.add_subparsers(dest="command",required=True)
    for name in ("catalog","project-pilot","project","admit-iscx","audit","freeze","pilot","train","evaluate","predict"):
        stage=commands.add_parser(name)
        if name!="predict":
            stage.add_argument("--root",type=Path,required=True); stage.add_argument("--config",type=Path,default=Path("configs/url-ml-v2.json"))
        if name=="project": stage.add_argument("--resume",action="store_true")
        if name=="admit-iscx": stage.add_argument("--mapping",type=Path,required=True)
        if name=="audit": stage.add_argument("--psl",type=Path,required=True)
        if name in ("train","evaluate","predict"): stage.add_argument("--artifact",type=Path,required=True)
        if name=="train": stage.add_argument("--version",required=True)
        if name=="evaluate":
            stage.add_argument("--out",type=Path,required=True); stage.add_argument("--v1-root",type=Path); stage.add_argument("--v1-artifact",type=Path)
        if name=="predict": stage.add_argument("--url",required=True)
    args=parser.parse_args(argv)
    try:
        if args.command!="predict" and sys.version_info[:2]!=(3,11): raise DatasetError("url_v2_requires_python311")
        config=load_config(args.config) if args.command!="predict" else None
        with contextlib.redirect_stdout(SanitizingWriter(sys.stdout)): result=_execute(args,config)
        print(json.dumps(sanitized(result),indent=2,sort_keys=True,allow_nan=False)); return 0
    except (DatasetError,OSError,ImportError,ValueError,KeyError,TypeError) as exc:
        detail={"command":args.command,"reason":getattr(exc,"reason",type(exc).__name__),"error_type":type(exc).__name__,"error_message":str(exc),"diagnostics":getattr(exc,"diagnostics",None)}
        result={"error":detail["reason"]}; root=getattr(args,"root",None)
        if root is not None:
            try: result["diagnostic_path"]=str(save_failure(root,args.command,detail))
            except (OSError,ValueError) as error: result.update({"diagnostic_error":type(error).__name__,"diagnostics":sanitized(detail)})
        else: result["diagnostics"]=sanitized(detail)
        print(json.dumps(result,sort_keys=True,allow_nan=False)); return 2

if __name__=="__main__": raise SystemExit(main())
