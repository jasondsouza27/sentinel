"""Explicit commands; no acquisition or training on application startup."""
import argparse
import json
from pathlib import Path
from .contracts import DatasetError

def main(argv=None):
    p=argparse.ArgumentParser(description="Sentinel URL-only research workflow")
    commands=p.add_subparsers(dest="command",required=True)
    for name in ("fetch","audit","split","pilot"):
        s=commands.add_parser(name); s.add_argument("--root",type=Path,required=True)
        if name!="fetch": s.add_argument("--config",type=Path,default=Path("configs/url-ml-v1.json"))
    args=p.parse_args(argv)
    try:
        from .source import fetch_sources,import_phiusiil,load_dataset
        if args.command=="fetch": result=fetch_sources(args.root)
        else:
            from .urls import UrlParser
            parser=UrlParser(args.root / "raw" / "suffix.dat")
            if args.command=="audit": result=import_phiusiil(args.root / "raw" / "source.csv",parser,args.root / "audited").manifest
            else:
                from .splits import freeze_splits,load_splits
                from .source import write_json
                config=json.loads(args.config.read_text(encoding="utf-8"))
                dataset=load_dataset(args.root / "audited",parser)
                if args.command=="split": result=freeze_splits(dataset,args.root / "splits",config["seed"]).manifest
                else:
                    from .training import resource_pilot
                    out=args.root / "pilot.json"
                    if out.exists(): raise DatasetError("output_exists")
                    result=resource_pilot(load_splits(dataset,args.root / "splits"),config,parser)
                    write_json(out,result)
                    result={k:v for k,v in result.items() if k!="case_ids"}
        print(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
        return 0
    except (DatasetError,OSError,ImportError) as e:
        print(json.dumps({"error":getattr(e,"reason",type(e).__name__)})); return 2

if __name__=="__main__": raise SystemExit(main())
