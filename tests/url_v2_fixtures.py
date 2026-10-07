"""Synthetic software fixtures; never a source of published accuracy evidence."""
import hashlib
import json
from pathlib import Path

def test_config():
    return json.loads(Path('configs/url-ml-v2.json').read_text(encoding='utf-8'))

def synthetic_observation(**overrides):
    from sentinel.url_v2.contracts import Observation
    values={'source_id':'phreshphish','revision':test_config()['sources']['phreshphish']['revision'],'original_partition':'train',
            'reference':{'shard':'fixture.parquet','row':1},'original_url':'https://alpha.example/a?q=1',
            'original_label':'benign','source_date':None,'opaque_id':None}
    values.update(overrides)
    if 'revision' not in overrides:
        values['revision']=next(s['revision'] for s in test_config()['sources'].values() if s['source_id']==values['source_id'])
    identity={key:values[key] for key in ('source_id','revision','reference')}
    values.setdefault('observation_id',hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest())
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

def synthetic_audit(root:Path,observations=None,*,authenticated=False):
    from sentinel.url_ml.urls import UrlParser
    from sentinel.url_v2.audit import audit_sources
    from url_ml_fixtures import fixture_psl
    parser=UrlParser(fixture_psl(root)); catalog=synthetic_catalog(root)
    if authenticated:
        for source in catalog.sources:
            source["date_semantics"]={"meaning":"synthetic collection date","evidence_ref":"software fixture","timezone":"UTC","authenticated":True}
    if observations is None:
        observations=[]; ordinal=0
        for part,groups,source in (("train",30,"phreshphish"),("test",10,"phreshphish"),("external",10,"iscx-url2016")):
            for group in range(groups):
                for label in (0,1):
                    ordinal+=1
                    observations.append(synthetic_observation(source_id=source,original_partition=part if source=="phreshphish" else ("benign" if label==0 else "phishing"),
                      reference={"shard":"fixture.parquet","row":ordinal},original_url=f"https://{part}{group}.example/article-{label}?q=1",
                      original_label=("benign" if label==0 else "phish" if source=="phreshphish" else "phishing"),
                      source_date="2024-01-01" if part=="train" else "2025-01-01"))
    return audit_sources(catalog,observations,parser,root/"audited"),catalog,parser

def small_protocol_config(parser):
    config=test_config(); config["parser"]["psl_sha256"]=parser.psl_sha256
    for key in config["support"]: config["support"][key]=1
    return config
