"""Official-source acquisition with durable budgets and verified receipts."""
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2.ranges import approved_url, cache_lock, open_response
from sentinel.url_v2.storage import manifest_hash, read_json, safe_file, sha256

class AcquisitionSession:
    def __init__(self,root,config):
        self.root=Path(root).resolve(); self.config=config; self.limits=config["acquisition"]
        self.journal=self.root/"journal.json"; self.active=False
    def __enter__(self):
        self.lock=cache_lock(self.root)
        try: self.lock.__enter__()
        except DatasetError: raise DatasetError("acquisition_session_busy") from None
        self.active=True
        try:
            if self.journal.exists():
                self.state=read_json(self.journal); self._validate()
            else:
                self.state={"schema":"url-acquisition-v3","config_sha256":manifest_hash(self.config),
                            "received_body_bytes":0,"interrupted_body_bytes_upper_bound":0,
                            "inflight_bytes":0,"attempts":[],"receipts":{}}
                self._save()
            # A process crash may occur between a read and recording its result.
            # The durable reservation remains charged without inventing measured bytes.
            if self.state["inflight_bytes"]:
                self.state["interrupted_body_bytes_upper_bound"]+=self.state["inflight_bytes"]
                self.state["inflight_bytes"]=0; self._save()
            for pending in self.root.glob(".pending-fetch-*"):
                if pending.is_file() and pending.parent==self.root: pending.unlink()
            return self
        except BaseException:
            self.__exit__(None,None,None); raise
    def __exit__(self,*args):
        if self.active: self.active=False; self.lock.__exit__(*args)
    def _validate(self):
        state=self.state
        if state.get("schema")!="url-acquisition-v3" or state.get("config_sha256")!=manifest_hash(self.config):
            raise DatasetError("acquisition_identity_mismatch")
        counters=("received_body_bytes","interrupted_body_bytes_upper_bound","inflight_bytes")
        if any(type(state.get(k)) is not int or state[k]<0 for k in counters):
            raise DatasetError("acquisition_budget_invalid")
        if sum(state[k] for k in counters)>self.limits["max_received_body_bytes"]:
            raise DatasetError("acquisition_budget_invalid")
        if not isinstance(state.get("attempts"),list) or not isinstance(state.get("receipts"),dict):
            raise DatasetError("acquisition_journal_invalid")
    def _save(self):
        pending=self.root/(".journal-"+uuid4().hex)
        try:
            with pending.open("x",encoding="utf-8",newline="\n") as f:
                json.dump(self.state,f,sort_keys=True,allow_nan=False); f.flush(); os.fsync(f.fileno())
            os.replace(pending,self.journal)
        finally:
            if pending.exists(): pending.unlink()
    def snapshot(self): return json.loads(json.dumps(self.state))
    def _remaining(self):
        return self.limits["max_received_body_bytes"]-sum(self.state[k] for k in
                 ("received_body_bytes","interrupted_body_bytes_upper_bound","inflight_bytes"))
    def _read(self,response,n,attempt):
        self.state["inflight_bytes"]=n; self._save()
        try: chunk=response.read(n)
        except http.client.IncompleteRead as exc:
            self._credit(exc.partial,n,attempt); raise
        except BaseException:
            # A buffered read may consume body bytes before failing without
            # exposing a partial buffer. Keep the full reservation charged.
            self.state["interrupted_body_bytes_upper_bound"]+=self.state["inflight_bytes"]
            self.state["inflight_bytes"]=0; self._save(); raise
        self._credit(chunk,n,attempt); return chunk
    def _credit(self,chunk,n,attempt):
        if not isinstance(chunk,bytes) or len(chunk)>n:
            raise DatasetError("source_read_contract_invalid")
        self.state["inflight_bytes"]=0
        self.state["received_body_bytes"]+=len(chunk); attempt["received_bytes"]+=len(chunk); self._save()
    def _body(self,response,pending,max_bytes,attempt):
        digest=hashlib.sha256(); size=0
        with pending.open("xb") as f:
            while True:
                remaining=self._remaining()
                if not remaining: raise DatasetError("source_cumulative_body_budget_exceeded")
                chunk=self._read(response,min(65536,max_bytes-size+1,remaining),attempt)
                if not chunk: break
                size+=len(chunk)
                if size>max_bytes: raise DatasetError("source_resource_body_oversized")
                f.write(chunk); digest.update(chunk)
                if size==max_bytes and self._remaining()==0:
                    # Require a matching length when no budget remains for an EOF probe.
                    if response.headers.get("Content-Length")!=str(size):
                        raise DatasetError("source_cumulative_body_budget_exceeded")
                    break
            f.flush(); os.fsync(f.fileno())
        return size,digest.hexdigest()
    def fetch(self,url,target,*,resource,max_bytes):
        if not self.active: raise DatasetError("acquisition_session_not_owned")
        approved_url(url,self.limits["allow_hosts"])
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}",resource): raise DatasetError("source_resource_invalid")
        ceiling=self.limits["max_csv_bytes"] if resource=="csv" else self.limits["max_metadata_bytes"]
        if type(max_bytes) is not int or not 0<max_bytes<=ceiling: raise DatasetError("source_resource_limit_invalid")
        source=self.config["sources"]["mendeley"]
        if resource=="csv" and url!=source["download_url"]: raise DatasetError("source_download_endpoint_mismatch")
        target=Path(target).resolve()
        try: relative=target.relative_to(self.root).as_posix()
        except ValueError: raise DatasetError("source_target_outside_session") from None
        safe_file(self.root,relative)
        identity={"url_sha256":hashlib.sha256(url.encode("utf-8")).hexdigest(),
                  "path":relative,"max_bytes":max_bytes}
        old=self.state["receipts"].get(resource)
        if old is not None:
            if any(old.get(k)!=v for k,v in identity.items()): raise DatasetError("source_receipt_identity_mismatch")
            if not target.is_file() or target.stat().st_size!=old["size"] or sha256(target)!=old["sha256"]:
                raise DatasetError("source_verified_cache_corrupt")
            if resource=="csv" and (old["size"]!=source["size"] or old["sha256"]!=source["sha256"]):
                raise DatasetError("source_verified_cache_pin_mismatch")
            return old
        attempts=[x for x in self.state["attempts"] if x["resource"]==resource]
        if any(x["identity"]!=identity for x in attempts): raise DatasetError("source_attempt_identity_mismatch")
        if target.exists():
            # An unregistered file is an orphan, even if its bytes happen to match.
            if not target.is_file(): raise DatasetError("source_target_invalid")
            target.rename(self.root/(".orphan-"+uuid4().hex))
        target.parent.mkdir(parents=True,exist_ok=True)
        for number in range(len(attempts)+1,self.limits["max_attempts"]+1):
            if self._remaining()<=0: raise DatasetError("source_cumulative_body_budget_exceeded")
            attempt={"resource":resource,"identity":identity,"attempt":number,"received_bytes":0,"status":"started"}
            self.state["attempts"].append(attempt); self._save()
            response=None; pending=self.root/(".pending-fetch-"+uuid4().hex)
            try:
                request=urllib.request.Request(url,headers={"Accept-Encoding":"identity","User-Agent":"Sentinel-Research/3"})
                try: response=open_response(request,self.limits["allow_hosts"],self.limits["timeout_seconds"])
                except urllib.error.HTTPError as exc: response=exc
                approved_url(response.geturl(),self.limits["allow_hosts"])
                status=response.status; attempt["http_status"]=status; self._save()
                size,digest=self._body(response,pending,max_bytes,attempt)
                if status in (408,429) or 500<=status<=599: raise TimeoutError("source_transient_http_status")
                if status!=200: raise DatasetError("source_status_not_200")
                if response.headers.get("Content-Encoding","identity").lower()!="identity":
                    raise DatasetError("source_encoded_response")
                length=response.headers.get("Content-Length")
                if length is not None and length!=str(size): raise DatasetError("source_content_length_mismatch")
                if resource=="csv" and (size!=source["size"] or digest!=source["sha256"]):
                    raise DatasetError("source_csv_pin_mismatch")
                receipt={**identity,"resource":resource,"size":size,"sha256":digest,
                         "received_body_bytes":self.state["received_body_bytes"],"complete":True}
                # Link publication is exclusive; another writer's target is never overwritten.
                os.link(pending,target)
                self.state["receipts"][resource]=receipt; attempt["status"]="verified"; self._save()
                return receipt
            except DatasetError as exc:
                attempt["status"]="rejected"; attempt["error"]=exc.reason; self._save(); raise
            except (OSError,urllib.error.URLError,http.client.IncompleteRead) as exc:
                attempt["status"]="interrupted"; attempt["error"]=type(exc).__name__; self._save()
                if number>=self.limits["max_attempts"]: raise DatasetError("source_transport_failed") from None
            finally:
                if response is not None: response.close()
                if pending.exists(): pending.unlink()
        raise DatasetError("source_attempt_limit_exhausted")
