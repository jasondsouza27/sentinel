"""Explicit local official-member admission; no network or archive extraction."""
import codecs
import csv
import re
import shutil
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from .contracts import CATALOG_SCHEMA,Observation,SourceCatalog,SourceFile,default_config
from .storage import cleanup_pending,manifest_hash,new_directory,publish_directory,read_json,safe_file,sha256,verify_files,write_json

OFFICIAL="https://www.unb.ca/cic/datasets/url-2016.html"
CATEGORIES={"benign","phishing","spam","malware","defacement"}

def _member_rows(path,fmt):
    try:
        codecs.lookup(fmt["encoding"])
        with Path(path).open(encoding=fmt["encoding"],newline="") as f:
            if fmt["kind"]=="lines":
                ordinal=0
                while True:
                    line=f.readline(1048577)
                    if not line: break
                    if len(line)>1048576: raise DatasetError("iscx_line_too_large")
                    ordinal+=1; yield ordinal,line.rstrip("\r\n")
            else:
                csv.field_size_limit(1048576); reader=csv.reader(f)
                column=fmt["url_column"]
                if fmt["header"]:
                    header=next(reader,None)
                    if header is None or header.count(column)!=1: raise DatasetError("iscx_csv_header_invalid")
                    column=header.index(column)
                for row in reader:
                    if column>=len(row): raise DatasetError("iscx_csv_row_invalid")
                    yield reader.line_num,row[column]
    except DatasetError: raise
    except (OSError,UnicodeError,LookupError,csv.Error,KeyError): raise DatasetError("iscx_member_format_invalid") from None

def _mapping(path):
    value=read_json(path)
    if value.get("schema")!="iscx-local-mapping-v1" or value.get("official_url")!=OFFICIAL: raise DatasetError("iscx_mapping_unsupported")
    for key in ("acquisition_basis","original_archive"):
        if not isinstance(value.get(key),str) or not value[key].strip(): raise DatasetError("iscx_identity_evidence_missing")
    try: date.fromisoformat(value["acquired_at"])
    except (KeyError,TypeError,ValueError): raise DatasetError("iscx_acquisition_date_invalid") from None
    if not isinstance(value.get("members"),list) or not value["members"]: raise DatasetError("iscx_members_missing")
    seen=set()
    for member in value["members"]:
        if not isinstance(member,dict) or set(member)!={"local_path","sha256","original_member","category","evidence_ref","format"}: raise DatasetError("iscx_member_schema_invalid")
        name=member["original_member"]; safe_file(Path(path).parent,name)
        if name in seen or not isinstance(member["evidence_ref"],str) or not member["evidence_ref"].strip(): raise DatasetError("iscx_member_evidence_missing")
        seen.add(name)
        if member["category"] not in CATEGORIES: raise DatasetError("iscx_category_unsupported")
        digest=member["sha256"]
        if not isinstance(digest,str) or not re.fullmatch("[0-9a-f]{64}",digest): raise DatasetError("iscx_hash_invalid")
        local=Path(member["local_path"])
        if not local.is_absolute(): local=Path(path).parent/local
        if not local.is_file() or sha256(local)!=digest: raise DatasetError("iscx_member_hash_mismatch")
        fmt=member["format"]
        if not isinstance(fmt,dict) or fmt.get("kind") not in ("csv","lines"): raise DatasetError("iscx_format_unsupported")
        keys={"kind","encoding"} if fmt["kind"]=="lines" else {"kind","encoding","header","url_column"}
        if set(fmt)!=keys or not isinstance(fmt.get("encoding"),str): raise DatasetError("iscx_format_schema_invalid")
        if fmt["kind"]=="csv":
            if type(fmt["header"]) is not bool or (fmt["header"] and not isinstance(fmt["url_column"],str)) or (not fmt["header"] and (type(fmt["url_column"]) is not int or fmt["url_column"]<0)): raise DatasetError("iscx_csv_schema_invalid")
        member=dict(member); member["resolved_local_path"]=local
    return value

def admit_iscx(mapping_path,output_dir):
    mapping_path=Path(mapping_path); mapping=_mapping(mapping_path); output=Path(output_dir); temp=new_directory(output)
    try:
        revision=sha256(mapping_path); files=[]; members=[]; excluded=Counter()
        for index,member in enumerate(sorted(mapping["members"],key=lambda x:x["original_member"])):
            local=Path(member["local_path"])
            if not local.is_absolute(): local=mapping_path.parent/local
            name=f"members/{index:04d}-{member['sha256']}.source"; target=safe_file(temp,name); target.parent.mkdir(exist_ok=True)
            shutil.copyfile(local,target)
            if sha256(target)!=member["sha256"]: raise DatasetError("iscx_copy_hash_mismatch")
            count=sum(1 for _ in _member_rows(target,member["format"]))
            if member["category"] not in ("benign","phishing"): excluded[member["category"]]+=count
            entry={k:v for k,v in member.items() if k!="local_path"}; entry.update({"path":name,"rows":count}); members.append(entry)
            files.append(SourceFile("iscx-url2016",revision,name,member["category"],target.stat().st_size,member["sha256"],member["original_member"]))
        source={**default_config()["sources"]["iscx"],"revision":revision,"acquisition_basis":mapping["acquisition_basis"],"acquired_at":mapping["acquired_at"],
          "original_archive":mapping["original_archive"],"mapping_verified_externally":False,"attribution":"Canadian Institute for Cybersecurity, ISCX-URL2016"}
        (temp/"mapping.json").write_bytes(mapping_path.read_bytes())
        hashes={f.path:sha256(safe_file(temp,f.path)) for f in files}; hashes["mapping.json"]=sha256(temp/"mapping.json")
        manifest={"schema":CATALOG_SCHEMA,"sources":[source],"source_files":[asdict(f) for f in files],"members":members,
          "excluded_categories":dict(excluded),"metadata_response_bytes":0,"files":hashes}
        write_json(temp/"manifest.json",manifest); publish_directory(temp,output); return SourceCatalog((source,),tuple(files),manifest)
    finally: cleanup_pending(temp,output.parent)

def iter_iscx_observations(catalog,admitted_root):
    from .catalog import load_catalog
    loaded=load_catalog(admitted_root)
    if loaded!=catalog: raise DatasetError("iscx_catalog_identity_mismatch")
    revision=catalog.sources[0]["revision"]
    for member in catalog.manifest["members"]:
        if member["category"] not in ("benign","phishing"): continue
        for ordinal,url in _member_rows(safe_file(admitted_root,member["path"]),member["format"]):
            reference={"archive":catalog.sources[0]["original_archive"],"member":member["original_member"],"line":ordinal}
            identity={"source_id":"iscx-url2016","revision":revision,"reference":reference}
            yield Observation(manifest_hash(identity),"iscx-url2016",revision,member["category"],reference,url,member["category"],None,None)
