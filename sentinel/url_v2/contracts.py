"""Versioned stdlib records and validated reproducible experiment settings."""
import copy
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from sentinel.url_ml.contracts import DatasetError,UrlRow,SplitBundle,RunBundle

PHRESH_REPOSITORY='phreshphish/phreshphish'
PHRESH_REVISION='eabec4b7a66324b79cc8a0ad856d1731dc26fe1a'
PSL_SHA256='e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66'
V2_CONFIG_SCHEMA='url-ml-config-v2'
CATALOG_SCHEMA='url-source-catalog-v2'
PROJECTION_SCHEMA='url-projection-v2'
DATASET_SCHEMA='url-dataset-v2'
PROTOCOL_SCHEMA='url-protocol-v2'
PROVENANCE_SCHEMA='url-provenance-v2'
ARTIFACT_SCHEMA='url-artifact-v2'
EVALUATION_SCHEMA='url-final-evaluation-v2'

@dataclass(frozen=True)
class SourceFile:
    source_id:str
    revision:str
    path:str
    original_partition:str
    size:int
    expected_sha256:str|None
    object_id:str|None

@dataclass(frozen=True)
class SourceCatalog:
    sources:tuple[dict,...]
    files:tuple[SourceFile,...]
    manifest:dict

@dataclass(frozen=True)
class Observation:
    observation_id:str
    source_id:str
    revision:str
    original_partition:str
    reference:dict
    original_url:str|None
    original_label:str|None
    source_date:str|None
    opaque_id:str|None

@dataclass(frozen=True)
class Record:
    row:UrlRow
    observation_ids:tuple[str,...]
    flags:tuple[str,...]

@dataclass(frozen=True)
class AuditBundle:
    root:Path
    manifest:dict

@dataclass(frozen=True)
class V2Splits:
    development:SplitBundle
    tracks:dict[str,tuple[UrlRow,...]]
    component_by_case:dict[str,str]
    sources_by_case:dict[str,tuple[str,...]]
    manifest:dict

@dataclass
class ResearchRun:
    run:RunBundle
    format_model:object
    format_report:dict
    protocol:dict

def default_config():
    training=json.loads((Path(__file__).resolve().parents[2]/'configs/url-ml-v1.json').read_text(encoding='utf-8'))
    training['sensitivity_budgets']=[.05,.01]
    unknown={'meaning':'unverified source date','evidence_ref':'source-date semantics require an acquisition audit',
             'timezone':None,'authenticated':False}
    return {'schema':V2_CONFIG_SCHEMA,
      'sources':{'phreshphish':{'source_id':'phreshphish','repository':PHRESH_REPOSITORY,'revision':PHRESH_REVISION,
                  'label_map':{'benign':0,'phish':1},'date_semantics':copy.deepcopy(unknown)},
                 'iscx':{'source_id':'iscx-url2016','revision':'local-official',
                  'source_url':'https://www.unb.ca/cic/datasets/url-2016.html','label_map':{'benign':0,'phishing':1},
                  'date_semantics':copy.deepcopy(unknown)}},
      'parser':{'max_url_chars':2048,'psl_sha256':PSL_SHA256},
      'projection':{'allow_hosts':['huggingface.co','us.aws.cdn.hf.co'],'timeout_seconds':30,'max_retries':3,
        'max_footer_bytes':2097152,'max_range_bytes':33554432,'max_response_bytes':2147483648,
        'batch_rows':4096,'max_inventory_bytes':2097152,'max_card_bytes':262144,
        'thrift_string_limit':2097152,'thrift_container_limit':100000},
      'split':{'seed':42,'fractions':{'train':.8,'validation':.1,'calibration':.1},'development_max_rows':200000},
      'support':{'train_min_rows_per_class':1000,'train_min_groups_per_class':100,
        'other_min_rows_per_class':100,'other_min_groups_per_class':30,
        'benign_min_non_root_path':100,'benign_min_non_www_host':100,'benign_min_query':30},
      'training':training}

def _shape(value,expected,path='config'):
    if isinstance(expected,dict):
        if not isinstance(value,dict) or set(value)!=set(expected): raise DatasetError('config_keys_invalid')
        for key,item in expected.items(): _shape(value[key],item,path+'.'+key)
    elif isinstance(expected,list):
        if not isinstance(value,list) or len(value)!=len(expected): raise DatasetError('config_sequence_invalid')
        for index,item in enumerate(expected): _shape(value[index],item,path+f'[{index}]')
    elif path.endswith('.date_semantics.timezone'):
        if value not in (None,'UTC'): raise DatasetError('config_timezone_unsupported')
    elif '.date_semantics.' in path:
        if type(value) is not type(expected): raise DatasetError('config_date_semantics_invalid')
        if isinstance(value,str) and (not value.strip() or len(value)>2048): raise DatasetError('config_date_semantics_invalid')
    elif isinstance(expected,(int,float)) and not isinstance(expected,bool):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value!=expected:
            raise DatasetError('config_numeric_value_invalid')
    elif type(value) is not type(expected) or value!=expected: raise DatasetError('config_value_invalid')

def load_config(path:Path)->dict:
    try: value=json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError): raise DatasetError('config_unreadable') from None
    _shape(value,default_config())
    for source in value['sources'].values():
        d=source['date_semantics']
        if d['authenticated'] and not d['evidence_ref'].strip(): raise DatasetError('date_semantics_evidence_missing')
    return value
