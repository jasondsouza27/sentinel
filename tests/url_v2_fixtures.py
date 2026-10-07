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
