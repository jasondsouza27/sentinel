"""Explicit stdlib-only contracts for the frozen URL-v3 study."""
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError, UrlRow, SplitBundle
from sentinel.url_v2.contracts import SourceCatalog, PHRESH_REVISION, PSL_SHA256

CONFIG_SCHEMA="url-ml-config-v3"
PROTOCOL_SCHEMA="url-protocol-v3"
DEVELOPMENT_SCHEMA="url-development-envelope-v3"
PROVENANCE_SCHEMA="url-provenance-v3"
ARTIFACT_SCHEMA="url-artifact-v3"
DIAGNOSTIC_SCHEMA="url-format-diagnostic-v3"
EVALUATION_SCHEMA="url-final-evaluation-v3"
STATUS_SCHEMA="url-research-status-v3"
MENDELEY_ID="mendeley-webpage-2020"
MENDELEY_REVISION="c2gw7fy2j4.3"
MENDELEY_FILE_ID="575316f4-ee1d-453e-a04f-7b950915b61b"
MENDELEY_SHA256="21093e2902e5441c86a6daf95e86e7c332046e477fdf109a579d7bd81e586d6c"
DEVELOPMENT_NAMES=("train","validation","calibration")
FINAL_NAMES=("primary","supplemental")

@dataclass(frozen=True)
class V2Binding:
    root: Path
    v2_root: Path
    catalog: SourceCatalog
    anchor_domains: tuple[str,...]
    primary_owners: dict[str,tuple[str,...]]
    manifest: dict

@dataclass(frozen=True)
class V3Splits:
    development: SplitBundle
    tracks: dict[str,tuple[UrlRow,...]]
    component_by_case: dict[str,str]
    sources_by_case: dict[str,tuple[str,...]]
    manifest: dict
    root: Path|None=None
    audit_root: Path|None=None
    study_root: Path|None=None

def default_config() -> dict:
    from sentinel.url_v2.contracts import default_config as v2_config
    old=v2_config()
    mendeley={"source_id":MENDELEY_ID,"revision":MENDELEY_REVISION,
      "label_map":{"legitimate":0,"phishing":1},
      "date_semantics":{"meaning":"missing row collection date","evidence_ref":"collection month is documentary only","timezone":None,"authenticated":False},
      "filename":"dataset_B_05_2020.csv","file_id":MENDELEY_FILE_ID,
      "size":3661166,"sha256":MENDELEY_SHA256,
      "landing_page":"https://data.mendeley.com/datasets/c2gw7fy2j4/3",
      "inventory_url":"https://data.mendeley.com/public-api/datasets/c2gw7fy2j4/files?folder_id=root&version=3",
      "download_url":f"https://data.mendeley.com/public-files/datasets/c2gw7fy2j4/files/{MENDELEY_FILE_ID}/file_downloaded",
      "doi":"10.17632/c2gw7fy2j4.3","license":"CC BY 4.0",
      "attribution":"Abdelhakim Hannousse and Salima Yahiouche","collection_month":"2020-05"}
    return {"schema":CONFIG_SCHEMA,
      "sources":{"phreshphish":copy.deepcopy(old["sources"]["phreshphish"]),"mendeley":mendeley},
      "parser":copy.deepcopy(old["parser"]),
      "acquisition":{"allow_hosts":["data.mendeley.com","prod-dcd-datasets-public-files-eu-west-1.s3.eu-west-1.amazonaws.com"],
        "timeout_seconds":30,"max_attempts":3,"max_metadata_bytes":2097152,
        "max_csv_bytes":4194304,"max_received_body_bytes":16777216},
      "csv":{"max_field_bytes":16384,"max_records":20000},
      "split":copy.deepcopy(old["split"]),
      "support":{**old["support"],"source_min_rows_per_class":100,"source_min_groups_per_class":30},
      "training":copy.deepcopy(old["training"])}

def _exact(value, expected):
    if type(value) is not type(expected): raise DatasetError("v3_config_type_invalid")
    if isinstance(expected,dict):
        if set(value)!=set(expected): raise DatasetError("v3_config_keys_invalid")
        for key,item in expected.items(): _exact(value[key],item)
    elif isinstance(expected,list):
        if len(value)!=len(expected): raise DatasetError("v3_config_sequence_invalid")
        for actual,item in zip(value,expected): _exact(actual,item)
    elif value!=expected: raise DatasetError("v3_config_value_invalid")

def load_config(path: Path) -> dict:
    try: value=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError): raise DatasetError("v3_config_unreadable") from None
    _exact(value,default_config())
    return value
