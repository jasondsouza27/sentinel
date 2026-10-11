"""Full physical and semantic admission before URL-v3 fitting or scoring."""
import copy
from pathlib import Path
from sentinel.url_ml import urls
from sentinel.url_ml.contracts import DatasetError,SplitBundle
from sentinel.url_ml.provenance import validate_provenance
from sentinel.url_v2.audit import load_audit
from sentinel.url_v2.storage import manifest_hash,read_json,safe_file,sha256
from .binding import load_v2_binding
from .contracts import V3Splits,DEVELOPMENT_NAMES,FINAL_NAMES
from .mendeley import load_mendeley
from .sources import joint_catalog
from .protocol import load_protocol,assert_training_ready

_VERIFIED={}

def _physical(splits,config,parser):
    if (not isinstance(splits,V3Splits) or splits.root is None or splits.audit_root is None or splits.study_root is None or
        set(splits.development.partitions)!=set(DEVELOPMENT_NAMES) or set(splits.tracks)!=set(FINAL_NAMES)):
        raise DatasetError("v3_frozen_roots_or_keys_invalid")
    study=Path(splits.study_root).resolve()
    if Path(splits.root).resolve()!=study/"protocol" or Path(splits.audit_root).resolve()!=study/"audited":
        raise DatasetError("v3_frozen_root_identity_invalid")
    if read_json(study/"config.json")!=config: raise DatasetError("v3_frozen_config_changed")
    if sha256(parser.psl_path)!=parser.psl_sha256 or parser.psl_sha256!=config["parser"]["psl_sha256"]:
        raise DatasetError("v3_frozen_psl_changed")
    fingerprints={str(study/"config.json"):sha256(study/"config.json"),str(parser.psl_path):sha256(parser.psl_path),
                  str(Path(urls.__file__).resolve()):sha256(Path(urls.__file__))}
    binding=read_json(study/"binding/manifest.json")
    try: v2=Path(binding["v2_root"]).resolve()
    except (KeyError,TypeError): raise DatasetError("v3_parent_root_invalid") from None
    directories=[study/"binding",study/"sources/mendeley",study/"audited",study/"protocol",
                 v2/"sources/phreshphish/catalog",v2/"sources/phreshphish/projection",v2/"audited",v2/"protocol"]
    for root in directories:
        manifest=read_json(root/"manifest.json"); files=manifest.get("files")
        if not isinstance(files,dict) or not files: raise DatasetError("v3_missing_physical_checksums")
        fingerprints[str(root/"manifest.json")]=sha256(root/"manifest.json")
        for name,expected in files.items():
            path=safe_file(root,name); digest=sha256(path)
            if digest!=expected: raise DatasetError("v3_physical_file_changed")
            fingerprints[str(path)]=digest
    return study,manifest_hash(fingerprints)

def verify_frozen_splits(splits,config,parser):
    try:
        study,signature=_physical(splits,config,parser)
        expected=_VERIFIED.get(signature)
        if expected is None:
            binding=load_v2_binding(study/"binding",config,parser)
            source=load_mendeley(study/"sources/mendeley",config)
            catalog=joint_catalog(binding,source)
            audit=load_audit(study/"audited",catalog,parser)
            expected=load_protocol(audit,catalog,binding,study/"protocol",config,study_root=study)
            if _physical(splits,config,parser)[1]!=signature: raise DatasetError("v3_files_changed_during_verification")
            # Cache only a privately owned snapshot that completed semantic replay.
            # Every reuse still reads and hashes every physical dependency.
            _VERIFIED.clear(); _VERIFIED[signature]=copy.deepcopy(expected)
        if (splits.manifest!=expected.manifest or splits.development!=expected.development or
            splits.tracks!=expected.tracks or splits.component_by_case!=expected.component_by_case or
            splits.sources_by_case!=expected.sources_by_case):
            raise DatasetError("v3_frozen_memory_or_rows_changed")
        if sha256(Path(urls.__file__))!=expected.manifest["parser_code_sha256"]:
            raise DatasetError("v3_parser_code_changed")
        return copy.deepcopy(expected.manifest)
    except DatasetError: raise
    except (OSError,KeyError,TypeError,ValueError,AttributeError):
        raise DatasetError("v3_frozen_input_invalid") from None

def development_bundle(splits,config,parser):
    verify_frozen_splits(splits,config,parser); assert_training_ready(splits)
    manifest=splits.development.manifest
    validate_provenance(manifest["provenance"],stage="development")
    return SplitBundle(dict(splits.development.partitions),copy.deepcopy(manifest))

def load_verified_study(root,config,parser):
    """Reconstruct the complete study once, then cache only its verified snapshot."""
    study=Path(root).resolve()
    probe=V3Splits(SplitBundle({name:() for name in DEVELOPMENT_NAMES},{}),
                   {name:() for name in FINAL_NAMES},{},{},{},
                   study/"protocol",study/"audited",study)
    try:
        _,before=_physical(probe,config,parser)
        binding=load_v2_binding(study/"binding",config,parser)
        source=load_mendeley(study/"sources/mendeley",config)
        catalog=joint_catalog(binding,source)
        audit=load_audit(study/"audited",catalog,parser)
        splits=load_protocol(audit,catalog,binding,study/"protocol",config,study_root=study)
        _,after=_physical(splits,config,parser)
        if before!=after: raise DatasetError("v3_files_changed_during_verification")
        _VERIFIED.clear(); _VERIFIED[after]=copy.deepcopy(splits)
        return splits
    except DatasetError: raise
    except (OSError,KeyError,TypeError,ValueError,AttributeError):
        raise DatasetError("v3_frozen_input_invalid") from None
