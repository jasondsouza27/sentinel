"""Study-wide stage exclusion and durable final-access receipts."""
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2.ranges import cache_lock
from sentinel.url_v2.storage import manifest_hash,read_json
from .contracts import PROTOCOL_SCHEMA

_HELD={}

def _study(splits):
    if splits.study_root is None or splits.root is None: raise DatasetError("v3_access_roots_required")
    root=Path(splits.study_root).resolve()
    if Path(splits.root).resolve()!=root/"protocol" or splits.manifest.get("schema")!=PROTOCOL_SCHEMA:
        raise DatasetError("v3_access_root_invalid")
    if read_json(splits.root/"manifest.json")!=splits.manifest:
        raise DatasetError("v3_access_protocol_changed")
    return root

@contextmanager
def study_guard(splits,*,stage):
    if stage not in ("pilot","train","evaluate"): raise DatasetError("v3_study_stage_invalid")
    root=_study(splits); key=str(root)
    if key in _HELD: raise DatasetError("v3_study_busy")
    with cache_lock(root/"stage-lock"):
        _HELD[key]=stage
        try: yield
        finally: _HELD.pop(key,None)

def _receipt(splits):
    root=_study(splits); protocol=manifest_hash(splits.manifest)
    return root/"final-access"/(protocol+".json"),protocol

def _owned(splits):
    if _HELD.get(str(_study(splits)))!="evaluate": raise DatasetError("v3_evaluation_guard_required")

def _save(path,value,*,initial=False):
    path.parent.mkdir(parents=True,exist_ok=True); pending=path.parent/(".receipt-"+uuid4().hex)
    try:
        with pending.open("x",encoding="utf-8",newline="\n") as f:
            json.dump(value,f,sort_keys=True,allow_nan=False); f.flush(); os.fsync(f.fileno())
        if initial: os.link(pending,path)
        else: os.replace(pending,path)
    finally:
        if pending.exists(): pending.unlink()

def assert_unscored(splits):
    path,_=_receipt(splits)
    if path.exists(): raise DatasetError("final_protocol_already_accessed")

def begin_final_access(splits,artifact_sha256,settings_sha256):
    _owned(splits); path,protocol=_receipt(splits)
    if any(not isinstance(x,str) or not re.fullmatch("[0-9a-f]{64}",x) for x in (artifact_sha256,settings_sha256)):
        raise DatasetError("v3_final_identity_invalid")
    identity={"schema":"url-final-access-v3","protocol_sha256":protocol,
              "artifact_sha256":artifact_sha256,"settings_sha256":settings_sha256}
    if path.exists():
        receipt=read_json(path)
        if any(receipt.get(k)!=v for k,v in identity.items()): raise DatasetError("v3_final_resume_identity_mismatch")
        if receipt.get("status") not in ("started","failed"): raise DatasetError("v3_final_evaluation_already_complete")
        receipt.update(status="started",resume_count=receipt["resume_count"]+1); _save(path,receipt)
        return receipt
    receipt={**identity,"status":"started","first_access_utc":datetime.now(timezone.utc).isoformat(),
             "resume_count":0,"report_sha256":None}
    _save(path,receipt,initial=True); return receipt

def finish_final_access(splits,*,status,report_sha256=None):
    _owned(splits); path,protocol=_receipt(splits)
    if status not in ("failed","complete"): raise DatasetError("v3_final_status_invalid")
    if status=="complete" and (not isinstance(report_sha256,str) or not re.fullmatch("[0-9a-f]{64}",report_sha256)):
        raise DatasetError("v3_final_report_digest_required")
    receipt=read_json(path)
    if receipt.get("protocol_sha256")!=protocol or receipt.get("status")!="started":
        raise DatasetError("v3_final_receipt_state_invalid")
    receipt.update(status=status,report_sha256=report_sha256); _save(path,receipt)

def assert_fitting_guard(splits):
    if _HELD.get(str(_study(splits))) not in ("pilot","train"):
        raise DatasetError("v3_fitting_guard_required")
