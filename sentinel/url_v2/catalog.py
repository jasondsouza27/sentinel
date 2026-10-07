"""Acquire and load the approved pinned release metadata, never source row URLs."""
import json
import re
import urllib.request
from dataclasses import asdict
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from .contracts import CATALOG_SCHEMA,PHRESH_REPOSITORY,PHRESH_REVISION,SourceCatalog,SourceFile
from .ranges import MEMBER,approved_url,open_response
from .storage import cleanup_pending,new_directory,publish_directory,read_json,sha256,verify_files,write_json

def _metadata(url,limit,config):
    response=None
    try:
        response=open_response(urllib.request.Request(url,headers={"Accept-Encoding":"identity"}),config["allow_hosts"],config["timeout_seconds"])
        host=approved_url(response.geturl(),config["allow_hosts"])
        if response.status!=200 or response.headers.get("Content-Encoding","identity").lower()!="identity": raise DatasetError("catalog_response_invalid")
        body=response.read(limit+1)
        if len(body)>limit: raise DatasetError("catalog_payload_too_large",{"received_bytes":len(body)})
        return body,host
    except DatasetError: raise
    except (OSError,ValueError) as exc: raise DatasetError("catalog_transport_failed",{"error_type":type(exc).__name__}) from None
    finally:
        if response is not None: response.close()

def fetch_phresh_catalog(output_dir:Path,config:dict)->SourceCatalog:
    output=Path(output_dir); temp=new_directory(output)
    try:
        limits=config["projection"]
        api=f"https://huggingface.co/api/datasets/{PHRESH_REPOSITORY}/revision/{PHRESH_REVISION}?blobs=true"
        raw,api_host=_metadata(api,limits["max_inventory_bytes"],limits)
        try: inventory=json.loads(raw)
        except ValueError: raise DatasetError("catalog_inventory_invalid") from None
        if inventory.get("sha")!=PHRESH_REVISION: raise DatasetError("catalog_revision_mismatch")
        if inventory.get("cardData",{}).get("license")!="cc-by-4.0": raise DatasetError("catalog_license_unverified")
        siblings=inventory.get("siblings")
        if not isinstance(siblings,list): raise DatasetError("catalog_members_invalid")
        files=[]; seen=set()
        for item in siblings:
            name=item.get("rfilename","")
            if not isinstance(name,str): raise DatasetError("catalog_member_invalid")
            match=MEMBER.fullmatch(name)
            if not match:
                if name.startswith("data/") and name.endswith(".parquet"): raise DatasetError("catalog_undeclared_parquet")
                continue
            size=item.get("size"); lfs=item.get("lfs") or {}; expected=lfs.get("sha256"); obj=item.get("blobId")
            if name in seen or type(size) is not int or size<12 or (lfs and lfs.get("size")!=size): raise DatasetError("catalog_size_or_member_invalid")
            if expected is not None and not re.fullmatch("[0-9a-f]{64}",expected): raise DatasetError("catalog_hash_invalid")
            if obj is not None and not re.fullmatch("[0-9a-f]{40,64}",obj): raise DatasetError("catalog_object_invalid")
            seen.add(name); files.append(SourceFile("phreshphish",PHRESH_REVISION,name,match[1],size,expected,obj))
        if set(x.original_partition for x in files)!={"train","test"}: raise DatasetError("catalog_train_test_missing")
        card,card_host=_metadata(f"https://huggingface.co/datasets/{PHRESH_REPOSITORY}/resolve/{PHRESH_REVISION}/README.md",limits["max_card_bytes"],limits)
        (temp/"inventory.json").write_bytes(raw); (temp/"card.md").write_bytes(card)
        source={**config["sources"]["phreshphish"],"license":"CC BY 4.0","attribution":"PhreshPhish authors, https://arxiv.org/abs/2507.10854","use":"anti-phishing research","source_url":f"https://huggingface.co/datasets/{PHRESH_REPOSITORY}"}
        files=tuple(sorted(files,key=lambda x:x.path))
        manifest={"schema":CATALOG_SCHEMA,"sources":[source],"source_files":[asdict(x) for x in files],"metadata_response_bytes":len(raw)+len(card),"response_hosts":[api_host,card_host],"files":{name:sha256(temp/name) for name in ("inventory.json","card.md")}}
        write_json(temp/"manifest.json",manifest); publish_directory(temp,output)
        return SourceCatalog((source,),files,manifest)
    finally: cleanup_pending(temp,output.parent)

def load_catalog(root:Path)->SourceCatalog:
    manifest=read_json(Path(root)/"manifest.json")
    if manifest.get("schema")!=CATALOG_SCHEMA: raise DatasetError("catalog_schema_unsupported")
    verify_files(Path(root),manifest.get("files",{}))
    try: files=tuple(SourceFile(**item) for item in manifest["source_files"]); sources=tuple(manifest["sources"])
    except (TypeError,KeyError): raise DatasetError("catalog_records_invalid") from None
    return SourceCatalog(sources,files,manifest)
