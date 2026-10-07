"""Sequential Parquet metadata projection through an audited seekable view."""
import io
import json
from dataclasses import asdict
from datetime import date,datetime
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from .contracts import Observation,PROJECTION_SCHEMA
from .storage import manifest_hash,publish_jsonl_directory,read_json,verify_files

COLUMNS=["url","label","date","sha256"]

def validate_chunks(chunks,size,footer_start,config):
    spans=[]
    for chunk in chunks:
        start=chunk["start"]; length=chunk["length"]
        if chunk.get("file_path"): raise DatasetError("parquet_external_column_unsupported")
        if type(start) is not int or type(length) is not int or start<4 or length<=0 or start+length>footer_start or footer_start>size-8: raise DatasetError("parquet_column_bounds_invalid")
        if chunk["name"] in COLUMNS and length>config["projection"]["max_range_bytes"]: raise DatasetError("parquet_selected_column_too_large")
        spans.append((start,start+length,chunk["name"]))
    spans.sort()
    if any(a[1]>b[0] for a,b in zip(spans,spans[1:])): raise DatasetError("parquet_columns_overlap")
    return [(start,end) for start,end,name in spans if name in COLUMNS]

def _arrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        return pa,pq
    except ImportError: raise DatasetError("url_data_dependencies_unavailable") from None

def plan_projection(file,session,config):
    pa,pq=_arrow(); limits=config["projection"]
    head=session.read_range(file,0,4); tail=session.read_range(file,file.size-8,8)
    if head!=b"PAR1" or tail[-4:]!=b"PAR1": raise DatasetError("parquet_magic_or_encryption_unsupported")
    length=int.from_bytes(tail[:4],"little"); start=file.size-8-length
    if length<=0 or length>limits["max_footer_bytes"] or start<4: raise DatasetError("parquet_footer_bounds_invalid")
    footer=session.read_range(file,start,length)
    if len(footer)!=length: raise DatasetError("parquet_footer_truncated")
    try:
        parsed=pq.ParquetFile(io.BytesIO(b"PAR1"+footer+tail),pre_buffer=False,buffer_size=0,thrift_string_size_limit=limits["thrift_string_limit"],thrift_container_size_limit=limits["thrift_container_limit"],arrow_extensions_enabled=False)
        metadata=parsed.metadata; schema=metadata.schema.to_arrow_schema()
        for name in COLUMNS:
            if schema.names.count(name)!=1: raise DatasetError("parquet_projected_field_missing")
            field=schema.field(name)
            scalar=pa.types.is_string(field.type) or pa.types.is_large_string(field.type)
            if name=="date": scalar=scalar or pa.types.is_date(field.type) or pa.types.is_timestamp(field.type)
            if not scalar: raise DatasetError("parquet_projected_schema_unsupported")
        chunks=[]
        for i in range(metadata.num_row_groups):
            rg=metadata.row_group(i)
            for j in range(rg.num_columns):
                c=rg.column(j); offsets=[x for x in (c.dictionary_page_offset,c.data_page_offset) if x is not None and x>=0]
                if not offsets: raise DatasetError("parquet_column_offset_missing")
                chunks.append({"name":c.path_in_schema,"start":min(offsets),"length":c.total_compressed_size,"file_path":c.file_path,"row_group":i})
        selected=validate_chunks(chunks,file.size,start,config)
        return {"metadata":metadata,"allowed_spans":[(0,4),(start,file.size),*selected],"chunks":chunks,"rows":metadata.num_rows,"footer_bytes":length}
    except DatasetError: raise
    except Exception as exc: raise DatasetError("parquet_metadata_invalid",{"error_type":type(exc).__name__}) from None

class PermittedView(io.RawIOBase):
    def __init__(self,file,session,allowed_spans):
        super().__init__(); self.file=file; self.session=session; self.spans=tuple(allowed_spans); self.position=0; self.cached=None
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.position
    def seek(self,offset,whence=0):
        position=offset if whence==0 else self.position+offset if whence==1 else self.file.size+offset if whence==2 else -1
        if position<0 or position>self.file.size: raise DatasetError("parquet_seek_out_of_bounds")
        self.position=position; return position
    def read(self,size=-1):
        if size is None or size<0: size=self.file.size-self.position
        if size==0: return b""
        end=self.position+size
        span=next(((lo,hi) for lo,hi in self.spans if lo<=self.position and end<=hi),None)
        if span is None: raise DatasetError("parquet_unaudited_read_refused",{"start":self.position,"length":size})
        if self.cached is None or self.cached[0]!=span:
            lo,hi=span; payload=self.session.read_range(self.file,lo,hi-lo)
            if len(payload)!=hi-lo: raise DatasetError("parquet_selected_data_truncated")
            self.cached=(span,payload)
        result=self.cached[1][self.position-span[0]:end-span[0]]; self.position=end; return result
    def readinto(self,buffer):
        result=self.read(len(buffer)); buffer[:len(result)]=result; return len(result)

def _scalar(value):
    if value is None or isinstance(value,str): return value
    if isinstance(value,(date,datetime)): return value.isoformat()
    raise DatasetError("parquet_scalar_unsupported")

def project_phresh(catalog,session,output_dir,config,*,pilot=False):
    pa,pq=_arrow(); limits=config["projection"]; purpose="pilot" if pilot else "full"
    if hasattr(session,"binding") and session.binding.get("purpose")!=purpose: raise DatasetError("projection_run_purpose_mismatch")
    all_files=sorted(catalog.files,key=lambda f:(f.original_partition!="train",f.path))
    if pilot: all_files=[next(f for f in all_files if f.original_partition==part) for part in ("train","test")]
    report={"schema":PROJECTION_SCHEMA,"status":"transport-schema-pilot" if pilot else "complete","purpose":purpose,
      "source_catalog_sha256":manifest_hash(catalog.manifest),"config_sha256":manifest_hash(config),"projected_columns":COLUMNS,
      "full_file_checksum_verified":False,"shards":[],"batch_lengths":[]}
    def observations():
        for file in all_files:
            plan=plan_projection(file,session,config); ordinal=0; view=PermittedView(file,session,plan["allowed_spans"])
            try:
                reader=pq.ParquetFile(view,metadata=plan["metadata"],pre_buffer=False,buffer_size=0,
                  thrift_string_size_limit=limits["thrift_string_limit"],thrift_container_size_limit=limits["thrift_container_limit"],arrow_extensions_enabled=False)
                for batch in reader.iter_batches(batch_size=limits["batch_rows"],columns=COLUMNS,use_threads=False,use_pandas_metadata=False):
                    report["batch_lengths"].append(batch.num_rows)
                    for row in batch.to_pylist():
                        ordinal+=1; reference={"shard":file.path,"row":ordinal}
                        identity={"source_id":file.source_id,"revision":file.revision,"reference":reference}
                        obs=Observation(manifest_hash(identity),file.source_id,file.revision,file.original_partition,reference,
                          _scalar(row["url"]),_scalar(row["label"]),_scalar(row["date"]),_scalar(row["sha256"]))
                        yield asdict(obs)
                if ordinal!=plan["rows"]: raise DatasetError("parquet_row_count_mismatch")
                report["shards"].append({"path":file.path,"rows":ordinal,"footer_bytes":plan["footer_bytes"],"selected_spans":plan["allowed_spans"][2:],"expected_full_sha256":file.expected_sha256,"full_file_checksum_verified":False})
            except DatasetError: raise
            except Exception as exc: raise DatasetError("parquet_projection_failed",{"path":file.path,"error_type":type(exc).__name__}) from None
            finally: view.close()
        report["transport"]=session.snapshot()
    try: return publish_jsonl_directory(Path(output_dir),{"observations.jsonl":observations()},report)
    except DatasetError as exc:
        raise DatasetError(exc.reason,{"cause":exc.diagnostics,"transport":session.snapshot(),"completed_shards":report["shards"],"purpose":purpose}) from None

def iter_phresh_observations(projection_root,catalog):
    root=Path(projection_root); manifest=read_json(root/"manifest.json")
    if manifest.get("schema")!=PROJECTION_SCHEMA or manifest.get("status")!="complete" or manifest.get("source_catalog_sha256")!=manifest_hash(catalog.manifest): raise DatasetError("projection_identity_invalid")
    if {s["path"] for s in manifest["shards"]}!={f.path for f in catalog.files}: raise DatasetError("projection_inventory_incomplete")
    verify_files(root,manifest["files"])
    with (root/"observations.jsonl").open(encoding="utf-8") as f:
        for line in f:
            try: yield Observation(**json.loads(line))
            except (ValueError,TypeError): raise DatasetError("projection_observation_invalid") from None
