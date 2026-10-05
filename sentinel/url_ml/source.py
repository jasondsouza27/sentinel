"""Fixed-source acquisition and immutable URL-only conversion."""
import csv
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .contracts import DatasetBundle, DatasetError, UrlRow, UnsupportedUrl, DATASET_SCHEMA

UCI_URL = "https://archive.ics.uci.edu/static/public/967/phiusiil+phishing+url+dataset.zip"
PSL_URL = "https://publicsuffix.org/list/public_suffix_list.dat"
CSV_MEMBER = "PhiUSIIL_Phishing_URL_Dataset.csv"
MAX_DOWNLOAD_BYTES = 64 * 1024**2
MAX_MEMBER_BYTES = 128 * 1024**2
PARSER_VERSION = "url-parser-v1"

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024**2), b""): h.update(chunk)
    return h.hexdigest()

def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+"\n", encoding="utf-8")

def read_json(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError): raise DatasetError("invalid_json") from None

def safe_file(root, name):
    if not isinstance(name,str) or not name or "\\" in name:
        raise DatasetError("unsafe_file_path")
    rel=Path(name)
    target=(Path(root) / rel).resolve()
    if rel.is_absolute() or ".." in rel.parts or not target.is_relative_to(Path(root).resolve()):
        raise DatasetError("unsafe_file_path")
    return target

def verify_files(root, files):
    if not isinstance(files,dict) or not files: raise DatasetError("missing_checksums")
    for name,digest in files.items():
        p=safe_file(root,name)
        if not p.is_file() or sha256(p)!=digest: raise DatasetError("file_hash_mismatch")

def new_directory(output_dir):
    output_dir=Path(output_dir)
    if output_dir.exists(): raise DatasetError("output_exists")
    output_dir.parent.mkdir(parents=True,exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=".pending-", dir=output_dir.parent))

def publish_directory(temp, dest):
    if Path(dest).exists(): raise DatasetError("output_exists")
    os.rename(temp,dest)

def validate_source_url(url):
    p=urlsplit(url)
    if p.scheme!="https" or p.hostname not in {"archive.ics.uci.edu","publicsuffix.org"} or p.username or p.password or p.port not in (None,443):
        raise DatasetError("unapproved_source_url")

class SourceRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_source_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def _download(url,path):
    validate_source_url(url)
    opener=build_opener(SourceRedirect())
    req=Request(url,headers={"User-Agent":"Sentinel-Research/1.0"})
    with opener.open(req,timeout=60) as response, Path(path).open("xb") as f:
        validate_source_url(response.geturl())
        size=0
        for chunk in iter(lambda: response.read(1024**2),b""):
            size+=len(chunk)
            if size>MAX_DOWNLOAD_BYTES: raise DatasetError("download_too_large")
            f.write(chunk)

def read_member(archive, destination):
    try:
        with zipfile.ZipFile(archive) as z:
            matches=[i for i in z.infolist() if i.filename==CSV_MEMBER]
            if len(matches)!=1: raise DatasetError("required_member_missing_or_ambiguous")
            member=matches[0]
            if member.file_size>MAX_MEMBER_BYTES: raise DatasetError("member_too_large")
            with z.open(member) as src, Path(destination).open("xb") as dst:
                size=0
                for chunk in iter(lambda: src.read(1024**2),b""):
                    size+=len(chunk)
                    if size>MAX_MEMBER_BYTES: raise DatasetError("member_too_large")
                    dst.write(chunk)
    except FileExistsError: raise DatasetError("output_exists") from None
    except zipfile.BadZipFile: raise DatasetError("invalid_archive") from None

def fetch_sources(root: Path) -> dict:
    root=Path(root); dest=root / "raw"
    if dest.exists():
        manifest=read_json(dest / "acquisition.json")
        if manifest.get("schema")!="url-acquisition-v1": raise DatasetError("acquisition_schema")
        verify_files(dest,manifest.get("files"))
        return manifest
    temp=new_directory(dest)
    try:
        _download(UCI_URL,temp / "source.zip")
        _download(PSL_URL,temp / "suffix.dat")
        read_member(temp / "source.zip",temp / "source.csv")
        manifest={"schema":"url-acquisition-v1", "retrieved_at":datetime.now(timezone.utc).isoformat(),
          "sources":{"dataset":{"url":UCI_URL,"terms":"CC BY 4.0; UCI PhiUSIIL dataset 967", "member":CSV_MEMBER},
                     "suffix":{"url":PSL_URL,"terms":"Mozilla Public License 2.0"}},
          "files":{n:sha256(temp/n) for n in ("source.zip","source.csv","suffix.dat")}}
        write_json(temp / "acquisition.json",manifest)
        publish_directory(temp,dest)
        return manifest
    finally:
        if temp.exists(): shutil.rmtree(temp)

def import_phiusiil(csv_path: Path, parser, output_dir: Path) -> DatasetBundle:
    csv_path=Path(csv_path); output_dir=Path(output_dir)
    if output_dir.exists(): raise DatasetError("output_exists")
    source_hash=sha256(csv_path)
    buckets=defaultdict(list); excluded=[]; counts=Counter(); original_counts=Counter(); total=0
    csv.field_size_limit(MAX_MEMBER_BYTES)
    with csv_path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not {"URL","label"}.issubset(reader.fieldnames or []): raise DatasetError("required_columns_missing")
        for ordinal,item in enumerate(reader,1):
            total+=1
            case_id=hashlib.sha256((source_hash+":"+str(ordinal)).encode()).hexdigest()
            original=item.get("URL")
            reason=None
            if item.get("label") not in ("0","1"): reason="invalid_label"
            else:
                original_counts[item["label"]]+=1
                try: parsed=parser.normalize(original)
                except UnsupportedUrl as error: reason=error.reason
            if reason:
                counts[reason]+=1; excluded.append({"case_id":case_id,"record":ordinal,"original_url":original,"reason":reason}); continue
            row=UrlRow(case_id,original,parsed.model_url,1-int(item["label"]),parsed.domain_group,
                       "sha256:"+source_hash+":record:"+str(ordinal))
            buckets[parsed.model_url].append(row)
    rows=[]
    for equivalents in buckets.values():
        if len({r.label for r in equivalents})>1:
            for r in equivalents:
                counts["conflicting_label"]+=1; excluded.append({"case_id":r.case_id,"original_url":r.original_url,"reason":"conflicting_label"})
        else:
            rows.append(equivalents[0])
            for r in equivalents[1:]:
                counts["duplicate"]+=1; excluded.append({"case_id":r.case_id,"original_url":r.original_url,"reason":"duplicate"})
    if not rows: raise DatasetError("no_supported_rows")
    temp=new_directory(output_dir)
    try:
        for name,records in (("rows.jsonl",[asdict(r) for r in rows]),("exclusions.jsonl",excluded)):
            with (temp/name).open("w",encoding="utf-8") as f:
                for record in records: f.write(json.dumps(record,ensure_ascii=True,allow_nan=False)+"\n")
        manifest={"schema":DATASET_SCHEMA,"parser_version":PARSER_VERSION,"psl_sha256":parser.psl_sha256,
                  "source_sha256":source_hash,"source_member":CSV_MEMBER,"input_rows":total,"included_rows":len(rows),
                  "excluded":dict(sorted(counts.items())),"original_labels":{"0":"phishing","1":"legitimate"},
                  "canonical_labels":{"1":"phishing","0":"legitimate"},"original_label_counts":dict(original_counts),
                  "class_counts":dict(Counter(str(r.label) for r in rows)),"unique_groups":len({r.domain_group for r in rows}),
                  "files":{n:sha256(temp/n) for n in ("rows.jsonl","exclusions.jsonl")}}
        write_json(temp / "manifest.json",manifest); publish_directory(temp,output_dir)
        return DatasetBundle(tuple(rows),manifest)
    finally:
        if temp.exists(): shutil.rmtree(temp)

def load_dataset(output_dir: Path, parser) -> DatasetBundle:
    root=Path(output_dir); m=read_json(root / "manifest.json")
    if m.get("schema")!=DATASET_SCHEMA or m.get("parser_version")!=PARSER_VERSION or m.get("psl_sha256")!=parser.psl_sha256:
        raise DatasetError("dataset_parser_or_schema_mismatch")
    verify_files(root,m.get("files"))
    try:
        with (root / "rows.jsonl").open(encoding="utf-8") as f: rows=tuple(UrlRow(**json.loads(line)) for line in f)
        if len(rows)!=m["included_rows"] or len({r.case_id for r in rows})!=len(rows) or len({r.url for r in rows})!=len(rows):
            raise DatasetError("dataset_row_integrity")
        for r in rows:
            parsed=parser.normalize(r.original_url)
            if r.label not in (0,1) or parsed.model_url!=r.url or parsed.domain_group!=r.domain_group:
                raise DatasetError("dataset_row_integrity")
        if dict(Counter(str(r.label) for r in rows))!=m["class_counts"]: raise DatasetError("dataset_class_counts")
    except (TypeError,ValueError,KeyError): raise DatasetError("dataset_row_integrity") from None
    return DatasetBundle(rows,m)
