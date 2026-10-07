"""Synthetic software fixtures; never a source of published accuracy evidence."""
import hashlib
import json
from pathlib import Path

def test_config():
    return json.loads(Path('configs/url-ml-v2.json').read_text(encoding='utf-8'))

def synthetic_observation(**overrides):
    from sentinel.url_v2.contracts import Observation
    values={'source_id':'phreshphish','revision':'fixture-release','original_partition':'train',
            'reference':{'shard':'fixture.parquet','row':1},'original_url':'https://alpha.example/a?q=1',
            'original_label':'benign','source_date':None,'opaque_id':None}
    values.update(overrides)
    values.setdefault('observation_id',hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest())
    return Observation(**values)

def synthetic_catalog(root:Path):
    from sentinel.url_v2.contracts import SourceCatalog,CATALOG_SCHEMA
    sources=tuple(test_config()['sources'].values())
    manifest={'schema':CATALOG_SCHEMA,'sources':list(sources),'files':[],'synthetic':True,'metadata_response_bytes':0}
    return SourceCatalog(sources,(),manifest)

def write_parquet_fixture(path:Path,*,nested=False,missing=False):
    import pyarrow as pa
    import pyarrow.parquet as pq
    values={"url":["https://alpha.example/a?q=1","https://beta.example/login",None],
            "label":["benign","phish","benign"],"date":["2024-08-01",None,"2025-01-01"],
            "sha256":["opaque-a","opaque-b",None],"html":["<html>secret</html>"*100]*3,"langs":["en"]*3}
    if nested: values["url"]=[{"value":"nested"}]*3
    if missing: values.pop("label")
    table=pa.table(values); pq.write_table(table,path,row_group_size=2,compression="snappy")
    return values

class LocalRangeSession:
    def __init__(self,paths): self.paths=paths; self.requests=[]; self.received=0
    def read_range(self,file,start,length):
        self.requests.append((file.path,start,length))
        with self.paths[file.path].open("rb") as f: f.seek(start); body=f.read(length)
        self.received+=len(body)
        return body
    def snapshot(self): return {"response_bytes":self.received,"requests":self.requests}
