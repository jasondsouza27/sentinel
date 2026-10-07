"""Disk-indexed canonical audit retaining every source observation and exclusion."""
import json
import hashlib
import re
import sqlite3
from collections import Counter
from dataclasses import asdict
from datetime import datetime,time,timedelta,timezone
from pathlib import Path
from urllib.parse import urlsplit
from sentinel.url_ml.contracts import DatasetError,UrlRow,UnsupportedUrl
from .contracts import AuditBundle,DATASET_SCHEMA,Observation,Record
from .storage import cleanup_pending,manifest_hash,new_directory,publish_jsonl_directory,read_json,sha256,verify_files

def format_flags(url):
    p=urlsplit(url); flags=[]
    if p.scheme=="https": flags.append("https")
    if (p.hostname or "").startswith("www."): flags.append("www_host")
    if p.path not in ("","/"): flags.append("non_root_path")
    if p.query: flags.append("query_present")
    return tuple(flags)

def date_interval(raw,semantics):
    if raw is None or raw=="": return None,"missing"
    if not isinstance(raw,str) or len(raw)>128: raise ValueError("malformed_source_date")
    is_day=bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}",raw))
    if not is_day and not re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T",raw): raise ValueError("malformed_source_date")
    value=datetime.fromisoformat(raw.replace("Z","+00:00"))
    if not semantics.get("authenticated"): return None,"semantics_unverified"
    if value.tzinfo is None:
        if semantics.get("timezone")!="UTC": return None,"timezone_unknown"
        value=value.replace(tzinfo=timezone.utc)
    value=value.astimezone(timezone.utc); end=value+timedelta(days=1)-timedelta(microseconds=1) if is_day else value
    return [value.isoformat(timespec="microseconds"),end.isoformat(timespec="microseconds")],"authenticated"

def _stage(catalog,observations,parser,path):
    db=sqlite3.connect(path); db.execute("PRAGMA temp_store=FILE")
    db.execute("CREATE TABLE observations (id TEXT PRIMARY KEY,case_id TEXT,label INTEGER,url TEXT,domain TEXT,reason TEXT,payload TEXT)")
    db.execute("CREATE INDEX canonical_idx ON observations(case_id,label)")
    sources={s["source_id"]:s for s in catalog.sources}
    try:
        for ordinal,obs in enumerate(observations,1):
            if not isinstance(obs,Observation) or not isinstance(obs.reference,dict) or not obs.reference: raise DatasetError("observation_schema_invalid")
            identity={"source_id":obs.source_id,"revision":obs.revision,"reference":obs.reference}
            source=sources.get(obs.source_id)
            if source is None or source["revision"]!=obs.revision or manifest_hash(identity)!=obs.observation_id: raise DatasetError("observation_identity_invalid")
            value=asdict(obs); reason=None; parsed=None; label=None; interval=None; status="unchecked"
            if obs.original_url is None or obs.original_url=="": reason="missing_source_url"
            elif not isinstance(obs.original_url,str): reason="invalid_source_url"
            elif len(obs.original_url)>2048: reason="oversized_source_url"
            elif obs.original_label is None or obs.original_label=="": reason="missing_source_label"
            elif not isinstance(obs.original_label,str) or obs.original_label not in source["label_map"]: reason="invalid_source_label"
            elif obs.opaque_id is not None and (not isinstance(obs.opaque_id,str) or len(obs.opaque_id)>4096): reason="invalid_or_oversized_opaque_id"
            else:
                label=source["label_map"][obs.original_label]
                try: parsed=parser.normalize(obs.original_url)
                except UnsupportedUrl as exc: reason=exc.reason
                if not reason:
                    try: interval,status=date_interval(obs.source_date,source["date_semantics"])
                    except (ValueError,OverflowError): reason="malformed_source_date"
            case_id=hashlib.sha256(parsed.model_url.encode("utf-8")).hexdigest() if parsed is not None and not reason else None
            value.update({"canonical_case_id":case_id,"reason":reason,"date_interval":interval,"date_status":status,
              "parser_flags":list(parsed.flags) if parsed is not None else []})
            try: db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?)",(obs.observation_id,case_id,label,parsed.model_url if parsed else None,parsed.domain_group if parsed else None,reason,json.dumps(value,sort_keys=True,allow_nan=False)))
            except sqlite3.IntegrityError: raise DatasetError("duplicate_observation_identity") from None
            if ordinal%4096==0: db.commit()
        conflicts=[x[0] for x in db.execute("SELECT case_id FROM observations WHERE reason IS NULL GROUP BY case_id HAVING MIN(label)<>MAX(label)")]
        for case_id in conflicts: db.execute("UPDATE observations SET reason='conflicting_label' WHERE case_id=?",(case_id,))
        db.commit(); return db
    except BaseException: db.close(); raise

def _provenance(db):
    for payload,reason in db.execute("SELECT payload,reason FROM observations ORDER BY id"):
        value=json.loads(payload); value["reason"]=reason
        if reason: value["canonical_case_id"]=None
        yield value

def _records(db):
    for case_id in (r[0] for r in db.execute("SELECT DISTINCT case_id FROM observations WHERE reason IS NULL ORDER BY case_id")):
        first=db.execute("SELECT id,label,url,domain,payload FROM observations WHERE case_id=? AND reason IS NULL ORDER BY id LIMIT 1",(case_id,)).fetchone(); value=json.loads(first[4]); flags=sorted(set(value["parser_flags"])|set(format_flags(first[2])))
        row=UrlRow(case_id,value["original_url"],first[2],first[1],first[3],"url-v2:case:"+case_id,value["source_date"])
        yield Record(row,tuple(r[0] for r in db.execute("SELECT id FROM observations WHERE case_id=? AND reason IS NULL ORDER BY id",(case_id,))),tuple(flags))

def _stats(db,catalog,parser):
    excluded=Counter(); sources=Counter(); dates=Counter(); formats=Counter(); classes=Counter(); groups=set(); count=0
    for p in _provenance(db):
        count+=1; sources[p["source_id"]]+=1; dates[p["date_status"]]+=1
        if p["reason"]: excluded[p["reason"]]+=1
    rows=0; included=0
    for record in _records(db):
        rows+=1; included+=len(record.observation_ids); classes[str(record.row.label)]+=1; groups.add(record.row.domain_group); formats.update(record.flags)
    exact=sum(n-1 for n, in db.execute("SELECT COUNT(*) FROM observations WHERE reason IS NULL GROUP BY url,json_extract(payload,'$.original_url') HAVING COUNT(*)>1"))
    from sentinel.url_ml import urls
    return {"schema":DATASET_SCHEMA,"source_catalog_sha256":manifest_hash(catalog.manifest),"parser_code_sha256":sha256(Path(urls.__file__)),
      "psl_sha256":parser.psl_sha256,"input_observations":count,"included_observations":included,"included_rows":rows,
      "duplicate_observations":included-rows,"exact_duplicate_observations":exact,"excluded":dict(sorted(excluded.items())),
      "source_observation_counts":dict(sorted(sources.items())),"date_status_counts":dict(sorted(dates.items())),"class_counts":dict(sorted(classes.items())),
      "format_counts":dict(sorted(formats.items())),"unique_domain_groups":len(groups),
      "limitations":["Source labels are historical annotations.","Unknown suffixes use full-host groups.","Date parsing does not authenticate collection semantics."]}

def audit_sources(catalog,observations,parser,output_dir):
    output=Path(output_dir); stage=new_directory(output); db=None
    try:
        db=_stage(catalog,observations,parser,stage/"staging.sqlite")
        manifest=_stats(db,catalog,parser)
        files={"rows.jsonl":(asdict(record) for record in _records(db)),"provenance.jsonl":_provenance(db),
          "exclusions.jsonl":({"observation_id":p["observation_id"],"reason":p["reason"]} for p in _provenance(db) if p["reason"])}
        result=publish_jsonl_directory(output,files,manifest); return AuditBundle(output,result)
    finally:
        if db is not None: db.close()
        cleanup_pending(stage,output.parent)

def _jsonl(path):
    try:
        with Path(path).open(encoding="utf-8") as f:
            for line in f: yield json.loads(line)
    except (OSError,ValueError): raise DatasetError("audit_jsonl_invalid") from None

def iter_records(audit):
    for value in _jsonl(audit.root/"rows.jsonl"):
        try: yield Record(UrlRow(**value["row"]),tuple(value["observation_ids"]),tuple(value["flags"]))
        except (KeyError,TypeError): raise DatasetError("audit_record_invalid") from None

def iter_provenance(audit): return _jsonl(audit.root/"provenance.jsonl")

def load_audit(root,catalog,parser):
    root=Path(root); manifest=read_json(root/"manifest.json")
    if manifest.get("schema")!=DATASET_SCHEMA or manifest.get("source_catalog_sha256")!=manifest_hash(catalog.manifest) or manifest.get("psl_sha256")!=parser.psl_sha256: raise DatasetError("audit_identity_mismatch")
    verify_files(root,manifest.get("files")); stage=new_directory(root.parent/("audit-validation-"+manifest_hash(manifest))); db=None
    try:
        fields=Observation.__dataclass_fields__
        obs=(Observation(**{key:value[key] for key in fields}) for value in _jsonl(root/"provenance.jsonl"))
        db=_stage(catalog,obs,parser,stage/"staging.sqlite"); stats=_stats(db,catalog,parser)
        if any(manifest.get(key)!=value for key,value in stats.items()): raise DatasetError("audit_counts_or_parser_mismatch")
        expected={"rows.jsonl":(asdict(r) for r in _records(db)),"provenance.jsonl":_provenance(db),
          "exclusions.jsonl":({"observation_id":p["observation_id"],"reason":p["reason"]} for p in _provenance(db) if p["reason"])}
        import hashlib
        for name,values in expected.items():
            digest=hashlib.sha256()
            for value in values: digest.update((json.dumps(value,sort_keys=True,ensure_ascii=True,allow_nan=False)+"\n").encode())
            if digest.hexdigest()!=manifest["files"][name]: raise DatasetError("audit_semantic_integrity_failed")
        return AuditBundle(root,manifest)
    except (KeyError,TypeError,ValueError): raise DatasetError("audit_provenance_invalid") from None
    finally:
        if db is not None: db.close()
        cleanup_pending(stage,root.parent)
