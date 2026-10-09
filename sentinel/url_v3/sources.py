"""Explicit joint catalog and full original-observation audit for URL v3."""
from dataclasses import asdict
from itertools import chain
from sentinel.url_v2.audit import audit_sources
from sentinel.url_v2.contracts import SourceCatalog
from sentinel.url_v2.projection import iter_phresh_observations
from sentinel.url_v2.storage import manifest_hash
from .binding import load_v2_binding
from .mendeley import load_mendeley,iter_mendeley_observations

def joint_catalog(binding,mendeley):
    sources=tuple(sorted((*binding.catalog.sources,*mendeley.sources),key=lambda s:s["source_id"]))
    files=tuple(sorted((*binding.catalog.files,*mendeley.files),key=lambda f:(f.source_id,f.path)))
    manifest={"schema":"url-source-catalog-v2","sources":list(sources),"source_files":[asdict(f) for f in files],
              "child_catalog_sha256":[manifest_hash(binding.catalog.manifest),manifest_hash(mendeley.manifest)],
              "parent_v2_protocol_sha256":binding.manifest["parent_v2_protocol_sha256"],
              "protected_domains_sha256":binding.manifest["protected_domains_sha256"],
              "metadata_response_bytes":binding.catalog.manifest.get("metadata_response_bytes",0)+mendeley.manifest["metadata_response_bytes"]}
    return SourceCatalog(sources,files,manifest)

def audit_v3(binding,source_root,config,parser,output_dir):
    binding=load_v2_binding(binding.root,config,parser)
    source=load_mendeley(source_root,config); catalog=joint_catalog(binding,source)
    observations=chain(iter_phresh_observations(binding.v2_root/"sources/phreshphish/projection",binding.catalog),
                       iter_mendeley_observations(source_root,source))
    return audit_sources(catalog,observations,parser,output_dir)
