"""Pinned-source HTTP ranges with durable byte accounting and verified caches."""
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from sentinel.url_ml.contracts import DatasetError
from .contracts import PHRESH_REPOSITORY,PHRESH_REVISION
from .storage import manifest_hash,read_json,safe_file,sanitized,sha256

MEMBER=re.compile(r"data/(train|test)-[0-9]+(?:-of-[0-9]+)?\.parquet\Z")

def approved_url(url,hosts):
    try:
        parsed=urllib.parse.urlsplit(url)
        valid=parsed.scheme=="https" and parsed.hostname in hosts and not parsed.username and not parsed.password and parsed.port in (None,443) and not parsed.fragment
    except ValueError: valid=False
    if not valid: raise DatasetError("unapproved_source_endpoint")
    return parsed.hostname

class ApprovedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,hosts): self.hosts=tuple(hosts)
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        approved_url(newurl,self.hosts)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def open_response(request,hosts,timeout):
    approved_url(request.full_url,hosts)
    return urllib.request.build_opener(ApprovedRedirect(hosts)).open(request,timeout=timeout)

@contextmanager
def cache_lock(root):
    root.mkdir(parents=True,exist_ok=True)
    with (root/"session.lock").open("a+b") as f:
        f.seek(0); f.write(b"0"); f.flush(); f.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError: raise DatasetError("projection_session_busy") from None
        try: yield
        finally:
            if os.name=="nt": f.seek(0); msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(f,fcntl.LOCK_UN)

class RangeSession:
    def __init__(self,catalog,cache_dir,config,*,purpose="full"):
        if purpose not in ("full","pilot"): raise DatasetError("range_purpose_invalid")
        self.catalog=catalog; self.root=Path(cache_dir); self.config=config; self.limits=config["projection"]
        self.binding={"catalog_sha256":manifest_hash(catalog.manifest),"config_sha256":manifest_hash(config),"revision":PHRESH_REVISION,"purpose":purpose}
        self.journal=self.root/"journal.json"
        with cache_lock(self.root):
            if self.journal.exists(): self._load()
            else:
                initial=catalog.manifest.get("metadata_response_bytes",0)
                if type(initial) is not int or not 0<=initial<=self.limits["max_response_bytes"]: raise DatasetError("metadata_budget_invalid")
                self.state={**self.binding,"response_bytes":initial,"metadata_receipt_charged":True,"objects":{},"ranges":{},"attempts":[]}
                self._save()
    def _load(self):
        self.state=read_json(self.journal)
        if any(self.state.get(k)!=v for k,v in self.binding.items()): raise DatasetError("range_journal_identity_mismatch")
        received=self.state.get("response_bytes")
        if type(received) is not int or not 0<=received<=self.limits["max_response_bytes"]: raise DatasetError("range_journal_budget_invalid")
    def _save(self):
        tmp=self.root/(".journal-"+uuid4().hex)
        try:
            with tmp.open("x",encoding="utf-8",newline="\n") as f:
                json.dump(self.state,f,sort_keys=True,allow_nan=False); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.journal)
        finally:
            if tmp.exists(): tmp.unlink()
    def snapshot(self): return json.loads(json.dumps(self.state))
    def _fail(self,reason):
        self._save(); raise DatasetError(reason,sanitized(self.snapshot()))
    def read_range(self,file,start,length):
        if file not in self.catalog.files or file.source_id!="phreshphish" or file.revision!=PHRESH_REVISION or not MEMBER.fullmatch(file.path):
            raise DatasetError("range_source_not_in_pinned_catalog")
        if type(start) is not int or type(length) is not int or start<0 or length<=0 or length>self.limits["max_range_bytes"] or start+length>file.size:
            raise DatasetError("range_bounds_invalid")
        key=manifest_hash({"file":file.__dict__,"start":start,"length":length,**self.binding})
        with cache_lock(self.root):
            self._load()
            if key in self.state["ranges"]:
                record=self.state["ranges"][key]; payload=safe_file(self.root,record["path"])
                if not payload.is_file() or payload.stat().st_size!=length or sha256(payload)!=record["sha256"]: self._fail("range_cache_corrupt")
                if record["etag"]!=self.state["objects"].get(file.path): self._fail("range_cache_object_mismatch")
                return payload.read_bytes()
            url=f"https://huggingface.co/datasets/{PHRESH_REPOSITORY}/resolve/{file.revision}/{file.path}"
            for index in range(self.limits["max_retries"]+1):
                if self.state["response_bytes"]+length>self.limits["max_response_bytes"]: self._fail("projection_response_budget_exceeded")
                attempt={"path":file.path,"start":start,"length":length,"attempt":index+1,"received_bytes":0}; self.state["attempts"].append(attempt); self._save()
                response=None
                try:
                    request=urllib.request.Request(url,headers={"Range":f"bytes={start}-{start+length-1}","Accept-Encoding":"identity","User-Agent":"Sentinel-Research/2"})
                    response=open_response(request,self.limits["allow_hosts"],self.limits["timeout_seconds"])
                    attempt["host"]=approved_url(response.geturl(),self.limits["allow_hosts"])
                    attempt["status"]=response.status
                    if 500<=response.status<=599: raise urllib.error.URLError("source_server_error")
                    if response.status!=206: self._fail("range_status_not_206")
                    headers=response.headers
                    if headers.get("Content-Encoding","identity").lower()!="identity": self._fail("range_encoded_response")
                    expected=f"bytes {start}-{start+length-1}/{file.size}"
                    if headers.get("Content-Range")!=expected: self._fail("range_content_range_invalid")
                    if headers.get("Content-Length")!=str(length): self._fail("range_content_length_invalid")
                    etag=headers.get("ETag","")
                    if not re.fullmatch(r'"[^"\r\n]+"',etag): self._fail("range_strong_identity_missing")
                    old=self.state["objects"].get(file.path)
                    if old is not None and old!=etag: self._fail("range_object_changed")
                    self.state["objects"][file.path]=etag; self._save()
                    chunks=[]; received=0
                    while received<length:
                        chunk=response.read(min(65536,length-received))
                        if not chunk: self._fail("range_body_truncated")
                        received+=len(chunk); attempt["received_bytes"]+=len(chunk); self.state["response_bytes"]+=len(chunk); self._save(); chunks.append(chunk)
                    extra=response.read(1) if self.state["response_bytes"]<self.limits["max_response_bytes"] else b""
                    if extra:
                        attempt["received_bytes"]+=len(extra); self.state["response_bytes"]+=len(extra); self._fail("range_body_oversized")
                    body=b"".join(chunks); directory=self.root/"ranges"; directory.mkdir(exist_ok=True); target=directory/(key+".bin")
                    with target.open("xb") as f: f.write(body); f.flush(); os.fsync(f.fileno())
                    self.state["ranges"][key]={"path":"ranges/"+target.name,"sha256":hashlib.sha256(body).hexdigest(),"etag":etag}
                    attempt["status"]="verified"; self._save(); return body
                except DatasetError: raise
                except (TimeoutError,OSError,urllib.error.URLError,http.client.IncompleteRead) as exc:
                    if isinstance(exc,http.client.IncompleteRead):
                        spent=len(exc.partial); attempt["received_bytes"]+=spent; self.state["response_bytes"]+=spent
                        if self.state["response_bytes"]>self.limits["max_response_bytes"]: self._fail("projection_response_budget_exceeded")
                    transient=not isinstance(exc,urllib.error.HTTPError) or exc.code in (408,429) or 500<=exc.code<=599
                    if isinstance(exc,urllib.error.HTTPError) and exc.code==403:
                        transient=approved_url(exc.geturl(),self.limits["allow_hosts"])=="us.aws.cdn.hf.co"
                    if isinstance(exc,urllib.error.HTTPError): exc.close()
                    attempt["error"]=type(exc).__name__; attempt["error_message"]=sanitized(str(exc));
                    if isinstance(exc,urllib.error.HTTPError): attempt["http_status"]=exc.code
                    self._save()
                    if not transient or index>=self.limits["max_retries"]: self._fail("range_transport_failed")
                    time.sleep(min(.1*2**index,.4))
                finally:
                    if response is not None: response.close()
