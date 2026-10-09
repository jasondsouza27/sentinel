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

def mendeley_fixture(root,config,body,*,metadata_change=None):
    """Official metadata shape with explicitly synthetic bytes and pins."""
    import copy,hashlib
    from unittest.mock import patch
    from sentinel.url_v3.mendeley import acquire_mendeley
    from test_url_v3_transport import Response
    cfg=copy.deepcopy(config); source=cfg["sources"]["mendeley"]
    source["size"]=len(body); source["sha256"]=hashlib.sha256(body).hexdigest()
    entry={"id":source["file_id"],"filename":source["filename"],"size":len(body),"status":"COMPLETED",
           "content_details":{"size":len(body),"sha256_hash":source["sha256"],"download_url":source["download_url"]}}
    page={"@type":"Dataset","name":"Web page phishing detection","version":"3","sameAs":source["landing_page"],
          "url":"http://doi.org/"+source["doi"],"license":{"text":"CC BY 4.0","url":"http://creativecommons.org/licenses/by/4.0"},
          "author":{"name":"Abdelhakim Hannousse"},"citation":{"text":"Hannousse, Abdelhakim; Yahiouche, Salima (2021)"}}
    if metadata_change: metadata_change(entry,page)
    html='<script type="application/ld+json">'+json.dumps(page)+'</script>'
    responses=[Response(json.dumps([entry]).encode()),Response(html.encode()),Response(body)]
    with patch("sentinel.url_v3.transport.open_response",side_effect=responses) as requests:
        catalog=acquire_mendeley(root,cfg)
    return catalog,cfg,requests.call_args_list

def synthetic_study(root: Path, *, scenario="balanced"):
    from sentinel.url_v3.binding import bind_v2
    from sentinel.url_v3.sources import audit_v3,joint_catalog
    from sentinel.url_v3.protocol import freeze_protocol
    root.mkdir(parents=True,exist_ok=True)
    v2,cfg,parser=synthetic_v2_root(root)
    for key in cfg["support"]: cfg["support"][key]=1
    cfg["training"]["char_tfidf"]["max_features"]=200
    binding=bind_v2(v2,root/"binding",cfg,parser)
    examples=[f"https://m{label}-{i}.example/article?q={i},{'phishing' if label else 'legitimate'}"
              for label in (0,1) for i in range(40)]
    if scenario=="primary_conflict":
        examples.extend(["https://final.example/article?x=1,phishing","https://final.example/new?q=1,legitimate"])
    if scenario=="missing_source_class": examples.append("https://devbad.example/login,legitimate")
    if scenario=="no_queries": examples=[x.replace("/article?q=","/article/") for x in examples]
    body=("url,status\n"+"\n".join(examples)+"\n").encode()
    cat,cfg,_=mendeley_fixture(root/"sources/mendeley",cfg,body)
    audit=audit_v3(binding,root/"sources/mendeley",cfg,parser,root/"audited")
    splits=freeze_protocol(audit,joint_catalog(binding,cat),binding,cfg,root/"protocol",study_root=root)
    (root/"config.json").write_text(json.dumps(cfg,sort_keys=True)+"\n",encoding="utf-8")
    return splits,cfg,parser
