"""Pinned Mendeley URL/status projection. Publisher code and features are unused."""
import csv
import hashlib
import json
import shutil
from dataclasses import asdict
from html.parser import HTMLParser
from itertools import zip_longest
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2.contracts import SourceCatalog,SourceFile,Observation
from sentinel.url_v2.storage import (cleanup_pending,manifest_hash,new_directory,publish_directory,
                                     read_json,sha256,verify_files,write_json)
from .transport import AcquisitionSession

class _Page(HTMLParser):
    def __init__(self): super().__init__(); self.active=False; self.buffer=[]; self.objects=[]
    def handle_starttag(self,tag,attrs):
        if tag=="script" and dict(attrs).get("type")=="application/ld+json":
            self.active=True; self.buffer=[]
    def handle_data(self,data):
        if self.active: self.buffer.append(data)
    def handle_endtag(self,tag):
        if tag=="script" and self.active:
            self.objects.append(json.loads("".join(self.buffer))); self.active=False

def _metadata(root,source):
    try:
        inventory=json.loads((root/"inventory.json").read_text(encoding="utf-8"))
        page=_Page(); page.feed((root/"page.html").read_text(encoding="utf-8"))
        if not isinstance(inventory,list) or any(not isinstance(x,dict) for x in inventory):
            raise DatasetError("mendeley_inventory_invalid")
        entries=[x for x in inventory if x.get("id")==source["file_id"] or x.get("filename")==source["filename"]]
        if len(entries)!=1: raise DatasetError("mendeley_file_identity_invalid")
        entry=entries[0]; details=entry["content_details"]
        expected={"id":source["file_id"],"filename":source["filename"],"size":source["size"],"status":"COMPLETED"}
        if any(entry.get(k)!=v for k,v in expected.items()) or type(entry.get("size")) is not int:
            raise DatasetError("mendeley_file_identity_invalid")
        expected={"size":source["size"],"sha256_hash":source["sha256"],"download_url":source["download_url"]}
        if any(details.get(k)!=v for k,v in expected.items()) or type(details.get("size")) is not int:
            raise DatasetError("mendeley_file_identity_invalid")
        datasets=[d for d in page.objects if isinstance(d,dict) and d.get("@type")=="Dataset"]
        if len(datasets)!=1: raise DatasetError("mendeley_page_identity_invalid")
        d=datasets[0]
        if (d.get("name")!="Web page phishing detection" or d.get("version")!="3" or
            d.get("sameAs")!=source["landing_page"] or d.get("url")!="http://doi.org/"+source["doi"] or
            d.get("license",{}).get("text")!=source["license"] or
            d.get("license",{}).get("url") not in ("http://creativecommons.org/licenses/by/4.0","https://creativecommons.org/licenses/by/4.0") or
            d.get("author",{}).get("name")!="Abdelhakim Hannousse" or
            "Yahiouche, Salima" not in d.get("citation",{}).get("text","")):
            raise DatasetError("mendeley_page_attribution_invalid")
    except DatasetError: raise
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        raise DatasetError("mendeley_metadata_invalid") from None

def _observations(path,source,limits):
    old=csv.field_size_limit(limits["max_field_bytes"])
    try:
        with path.open(encoding="utf-8-sig",newline="") as f:
            reader=csv.reader(f,strict=True)
            headers=next(reader,None)
            if (headers is None or any(not h for h in headers) or len(headers)!=len(set(headers)) or
                headers.count("url")!=1 or headers.count("status")!=1 or
                any(len(h.encode("utf-8"))>limits["max_field_bytes"] for h in headers)):
                raise DatasetError("mendeley_csv_headers_invalid")
            url_index=headers.index("url"); label_index=headers.index("status")
            for ordinal,values in enumerate(reader,1):
                if ordinal>limits["max_records"]: raise DatasetError("mendeley_csv_record_cap_exceeded")
                if len(values)!=len(headers): raise DatasetError("mendeley_csv_width_invalid")
                if any(len(value.encode("utf-8"))>limits["max_field_bytes"] for value in values):
                    raise DatasetError("mendeley_csv_field_bytes_exceeded")
                reference={"file_id":source["file_id"],"file_sha256":source["sha256"],"record":ordinal}
                identity={"source_id":source["source_id"],"revision":source["revision"],"reference":reference}
                yield Observation(manifest_hash(identity),source["source_id"],source["revision"],"source",
                                  reference,values[url_index],values[label_index],None,None)
    except DatasetError: raise
    except (OSError,UnicodeError,csv.Error): raise DatasetError("mendeley_csv_invalid") from None
    finally: csv.field_size_limit(old)

def _source_file(source):
    return SourceFile(source["source_id"],source["revision"],source["filename"],"source",
                      source["size"],source["sha256"],source["file_id"])

def acquire_mendeley(root,config):
    root=Path(root).resolve()
    if root.exists(): return load_mendeley(root,config)
    source=config["sources"]["mendeley"]; stage=new_directory(root)
    acquisition=root.parent/"acquisition-mendeley"
    names={"inventory":"inventory.json","page":"page.html","csv":source["filename"]}
    try:
        with AcquisitionSession(acquisition,config) as session:
            for resource,key in (("inventory","inventory_url"),("page","landing_page"),("csv","download_url")):
                cap=config["acquisition"]["max_csv_bytes" if resource=="csv" else "max_metadata_bytes"]
                session.fetch(source[key],acquisition/names[resource],resource=resource,max_bytes=cap)
                shutil.copyfile(acquisition/names[resource],stage/names[resource])
            receipts=session.snapshot()
        _metadata(stage,source)
        count=0
        with (stage/"observations.jsonl").open("x",encoding="utf-8",newline="\n") as out:
            for obs in _observations(stage/source["filename"],source,config["csv"]):
                count+=1; out.write(json.dumps(asdict(obs),sort_keys=True,ensure_ascii=True,allow_nan=False)+"\n")
        write_json(stage/"receipts.json",receipts)
        description={**source,"use":"URL-only anti-phishing research"}
        manifest={"schema":"url-source-catalog-v2","adapter_schema":"url-mendeley-projection-v3",
                  "config_sha256":manifest_hash(config),"sources":[description],
                  "source_files":[asdict(_source_file(source))],"csv_limits":config["csv"],
                  "rows":count,"full_file_checksum_verified":True,
                  "metadata_response_bytes":sum(receipts["receipts"][k]["size"] for k in ("inventory","page")),
                  "measured_received_body_bytes":receipts["received_body_bytes"],
                  "interrupted_body_bytes_upper_bound":receipts["interrupted_body_bytes_upper_bound"],
                  "files":{name:sha256(stage/name) for name in (*names.values(),"observations.jsonl","receipts.json")}}
        write_json(stage/"manifest.json",manifest); publish_directory(stage,root)
        return load_mendeley(root,config)
    finally: cleanup_pending(stage,root.parent)

def _check_receipts(root,manifest,source,config):
    state=read_json(root/"receipts.json")
    keys={"inventory":("inventory_url","inventory.json"),"page":("landing_page","page.html"),
          "csv":("download_url",source["filename"])}
    if (state.get("schema")!="url-acquisition-v3" or state.get("config_sha256")!=manifest_hash(config) or
        set(state.get("receipts",{}))!=set(keys) or state.get("inflight_bytes")!=0):
        raise DatasetError("mendeley_receipts_invalid")
    measured=state.get("received_body_bytes"); uncertain=state.get("interrupted_body_bytes_upper_bound")
    if (type(measured) is not int or type(uncertain) is not int or min(measured,uncertain)<0 or
        measured+uncertain>config["acquisition"]["max_received_body_bytes"] or
        manifest.get("measured_received_body_bytes")!=measured or
        manifest.get("interrupted_body_bytes_upper_bound")!=uncertain):
        raise DatasetError("mendeley_receipt_budget_invalid")
    if sum(x["received_bytes"] for x in state["attempts"])!=measured:
        raise DatasetError("mendeley_receipt_budget_invalid")
    for resource,(key,name) in keys.items():
        receipt=state["receipts"][resource]
        if (receipt.get("complete") is not True or receipt.get("resource")!=resource or receipt.get("path")!=name or
            receipt.get("url_sha256")!=hashlib.sha256(source[key].encode()).hexdigest() or
            receipt.get("size")!=(root/name).stat().st_size or receipt.get("sha256")!=sha256(root/name) or
            not 1<=len([a for a in state["attempts"] if a["resource"]==resource])<=config["acquisition"]["max_attempts"]):
            raise DatasetError("mendeley_receipts_invalid")

def load_mendeley(root,config):
    root=Path(root); m=read_json(root/"manifest.json"); source=config["sources"]["mendeley"]
    names={"inventory.json","page.html",source["filename"],"observations.jsonl","receipts.json"}
    if (m.get("schema")!="url-source-catalog-v2" or m.get("adapter_schema")!="url-mendeley-projection-v3" or
        m.get("config_sha256")!=manifest_hash(config) or m.get("csv_limits")!=config["csv"] or
        m.get("sources")!=[{**source,"use":"URL-only anti-phishing research"}] or
        m.get("source_files")!=[asdict(_source_file(source))] or m.get("full_file_checksum_verified") is not True or
        set(m.get("files",{}))!=names):
        raise DatasetError("mendeley_catalog_identity_invalid")
    verify_files(root,m["files"]); _metadata(root,source); _check_receipts(root,m,source,config)
    if (root/source["filename"]).stat().st_size!=source["size"] or sha256(root/source["filename"])!=source["sha256"]:
        raise DatasetError("mendeley_csv_pin_mismatch")
    catalog=SourceCatalog(tuple(m["sources"]),(_source_file(source),),m)
    count=sum(1 for _ in iter_mendeley_observations(root,catalog))
    if type(m.get("rows")) is not int or count!=m["rows"]: raise DatasetError("mendeley_projection_count_invalid")
    return catalog

def iter_mendeley_observations(root,catalog):
    root=Path(root); source=catalog.sources[0]; verify_files(root,catalog.manifest["files"])
    try:
        with (root/"observations.jsonl").open(encoding="utf-8") as saved:
            actual=(json.loads(line) for line in saved)
            expected=_observations(root/source["filename"],source,catalog.manifest["csv_limits"])
            for obs,value in zip_longest(expected,actual):
                if obs is None or value!=asdict(obs): raise DatasetError("mendeley_projection_semantic_mismatch")
                yield obs
    except DatasetError: raise
    except (OSError,ValueError,TypeError): raise DatasetError("mendeley_projection_invalid") from None
