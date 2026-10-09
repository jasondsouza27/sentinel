"""Synthetic software fixtures, never research accuracy evidence."""

import json
from dataclasses import asdict
from pathlib import Path

def synthetic_v2_root(root: Path):
    from sentinel.url_ml.urls import UrlParser
    from url_ml_fixtures import fixture_psl
    from sentinel.url_v2.contracts import SourceFile,SourceCatalog,Observation,default_config as old_config
    from sentinel.url_v3.contracts import default_config
    from sentinel.url_v2.storage import write_json,sha256,manifest_hash,publish_jsonl_directory
    from sentinel.url_v2.catalog import merge_catalogs
    from sentinel.url_v2.audit import audit_sources
    from sentinel.url_v2.protocol import freeze_protocol
    parser=UrlParser(fixture_psl(root)); previous=old_config()
    previous["parser"]["psl_sha256"]=parser.psl_sha256
    config=default_config(); config["parser"]["psl_sha256"]=parser.psl_sha256
    v2=root/"v2"; catdir=v2/"sources/phreshphish/catalog"; catdir.mkdir(parents=True)
    source={**previous["sources"]["phreshphish"],"license":"CC BY 4.0","attribution":"synthetic software fixture"}
    files=tuple(SourceFile("phreshphish",source["revision"],f"data/{part}-00000-of-00001.parquet",part,12,None,None) for part in ("train","test"))
    write_json(catdir/"inventory.json",{"sha":source["revision"],"cardData":{"license":"cc-by-4.0"},
        "siblings":[{"rfilename":f.path,"size":f.size} for f in files]})
    (catdir/"card.md").write_text("license: cc-by-4.0\nSynthetic software fixture\n",encoding="utf-8")
    manifest={"schema":"url-source-catalog-v2","sources":[source],"source_files":[asdict(f) for f in files],
      "metadata_response_bytes":(catdir/"inventory.json").stat().st_size+(catdir/"card.md").stat().st_size,
      "files":{name:sha256(catdir/name) for name in ("inventory.json","card.md")}}
    write_json(catdir/"manifest.json",manifest); primary=SourceCatalog((source,),files,manifest)
    examples=[("train","https://dev.example/article?x=1","benign",None),
              ("train","https://heldout.example/train","benign","join"),
              ("train","https://linked.example/train","benign","join"),
              ("train","https://devbad.example/login","phish",None),
              ("test","https://heldout.example/test","phish","join"),
              ("test","https://final.example/article?x=1","benign",None)]
    observations=[]; ordinals={"train":0,"test":0}
    for partition,url,label,opaque in examples:
        ordinals[partition]+=1
        reference={"shard":f"data/{partition}-00000-of-00001.parquet","row":ordinals[partition]}
        identity={"source_id":"phreshphish","revision":source["revision"],"reference":reference}
        observations.append(Observation(manifest_hash(identity),"phreshphish",source["revision"],partition,reference,url,label,None,opaque))
    projection={"schema":"url-projection-v2","status":"complete","purpose":"full","source_catalog_sha256":manifest_hash(manifest),
        "config_sha256":manifest_hash(previous),"projected_columns":["url","label","date","sha256"],
        "full_file_checksum_verified":False,"shards":[{"path":f.path,"rows":ordinals[f.original_partition]} for f in files]}
    publish_jsonl_directory(v2/"sources/phreshphish/projection",{"observations.jsonl":map(asdict,observations)},projection)
    joint=merge_catalogs(primary,None); audit=audit_sources(joint,observations,parser,v2/"audited")
    freeze_protocol(audit,joint,previous,v2/"protocol")
    return v2,config,parser

def hashes(root: Path):
    from sentinel.url_ml.source import sha256
    return {str(p.relative_to(root)):sha256(p) for p in root.rglob("*") if p.is_file()}
