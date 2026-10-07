"""Exclusive byte-checked publication and private sanitized diagnostics."""
import hashlib
import json
import re
import shutil
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_ml.source import safe_file,new_directory,publish_directory,write_json,read_json,sha256,verify_files
from sentinel.url_ml.splits import manifest_hash

def cleanup_pending(temp:Path,parent:Path)->None:
    actual=Path(temp).resolve(); expected=Path(parent).resolve()
    if actual.parent!=expected or not actual.name.startswith('.pending-'): raise DatasetError('unsafe_pending_cleanup')
    if actual.exists(): shutil.rmtree(actual)

def publish_jsonl_directory(output_dir:Path,files:dict,manifest:dict)->dict:
    output=Path(output_dir)
    temp=new_directory(output)
    try:
        hashes={}
        for name,records in files.items():
            if name=='manifest.json': raise DatasetError('reserved_manifest_filename')
            target=safe_file(temp,name); target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('x',encoding='utf-8',newline='\n') as f:
                for record in records: f.write(json.dumps(record,sort_keys=True,ensure_ascii=True,allow_nan=False)+'\n')
            hashes[name]=sha256(target)
        result={**manifest,'files':dict(sorted(hashes.items()))}
        write_json(temp/'manifest.json',result); publish_directory(temp,output)
        return result
    finally:
        cleanup_pending(temp,output.parent)

def sanitized(value):
    if isinstance(value,dict): return {str(k):sanitized(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [sanitized(x) for x in value]
    if isinstance(value,str):
        return re.sub(r'https?://[^\s\"\'<>]+','<redacted-url>',value)[:4096]
    if value is None or isinstance(value,(bool,int,float)): return value
    return sanitized(str(value))

def save_failure(root:Path,stage:str,diagnostics:dict)->Path:
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',stage): raise DatasetError('invalid_failure_stage')
    directory=Path(root)/'failed-runs'; directory.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=directory/f'{stage}-{stamp}-{uuid4().hex}.json'
    with target.open('x',encoding='utf-8',newline='\n') as f:
        f.write(json.dumps(sanitized(diagnostics),sort_keys=True,indent=2,allow_nan=False)+'\n')
    return target.resolve()
