import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError,UrlRow
from sentinel.url_v3.contracts import default_config
from url_v3_fixtures import synthetic_study

class V3ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
    def test_ownership_priority_subset_and_component_isolation(self):
        from sentinel.url_v3.protocol import assert_training_ready
        from sentinel.url_v2.storage import read_json
        splits,cfg,parser=synthetic_study(self.root); assert_training_ready(splits)
        owners=[json.loads(x) for x in (splits.root/"owners.jsonl").read_text().splitlines()]
        old={json.loads(x)["case_id"]:json.loads(x)["owner_observation_ids"] for x in (self.root/"binding/primary-owners.jsonl").read_text().splitlines()}
        self.assertTrue({r.case_id for r in splits.tracks["primary"]}<=set(old))
        destinations={}
        for name,rows in {**splits.development.partitions,**splits.tracks}.items():
            for row in rows:
                comp=splits.component_by_case[row.case_id]
                self.assertEqual(destinations.setdefault(comp,name),name)
        for o in owners:
            if o["track"]=="primary":
                self.assertTrue(set(o["owner_observation_ids"])<=set(old[o["case_id"]]))
                self.assertEqual(o["source_ids"],["phreshphish"])
            if o["track"]=="supplemental": self.assertEqual(o["source_ids"],["mendeley-webpage-2020"])
        self.assertEqual(set(splits.tracks),{"primary","supplemental"})
        self.assertEqual(splits.manifest["temporal"]["status"],"unavailable")
        self.assertEqual(splits.manifest["protected_domain_groups"],3)
    def test_fixed_half_hash(self):
        from sentinel.url_v3.protocol import supplemental_reserved
        for comp in ("0"*64,"f"*64,hashlib.sha256(b"example").hexdigest()):
            expected=int.from_bytes(hashlib.sha256(b"url-v3-mendeley-final|42|"+comp.encode("ascii")).digest()[:8],"big")<2**63
            self.assertIs(supplemental_reserved(comp),expected)
    def test_conflict_never_releases_anchor_or_adds_new_primary_case(self):
        splits,cfg,parser=synthetic_study(self.root,scenario="primary_conflict")
        self.assertEqual(splits.manifest["protected_domain_groups"],3)
        self.assertEqual(len(splits.tracks["primary"]),1)
        self.assertEqual(splits.manifest["original_primary_removed"],1)
        self.assertFalse(any("final.example" in r.url for r in splits.development.partitions["train"]))
        self.assertFalse(any("final.example" in r.url for r in splits.tracks["supplemental"]))
        self.assertEqual(splits.manifest["exclusions"]["heldout_component_overlap"],3)
    def test_mandatory_cap_and_whole_nonmandatory_skip(self):
        from sentinel.url_v3.protocol import select_development
        with self.assertRaisesRegex(DatasetError,"mandatory_development_components_exceed_cap"):
            select_development({"mandatory":range(200001)},{"mandatory"},200000,42)
        chosen,skips=select_development({"must":range(2),"giant":range(200001),"tiny":range(1)},{"must"},5,42)
        self.assertEqual(set(chosen),{"must","tiny"}); self.assertEqual(skips,{"giant":"development_cap"})
        again=select_development(dict(reversed(list({"must":range(2),"giant":range(200001),"tiny":range(1)}.items()))),{"must"},5,42)
        self.assertEqual((chosen,skips),again)
    def test_production_rows_domains_and_train_or_final_query_gates(self):
        from sentinel.url_v3.protocol import track_support
        cfg=default_config()
        def rows(n,groups,queries):
            return tuple(UrlRow(str(label)+"-"+str(i),"https://x.example/","https://x.example/path"+("?q=1" if i<queries else ""),
                       label,"domain:"+str(label)+"-"+str(i%groups),"fixture") for label in (0,1) for i in range(n))
        for training,n,groups in ((True,1000,100),(False,100,30)):
            values=rows(n,groups,30); comps={r.case_id:r.domain_group for r in values}
            self.assertEqual(track_support(values,comps,cfg,training=training,formats=True)["status"],"available")
            for count,group_count,query_count in ((n-1,groups,30),(n,groups-1,30),(n,groups,29)):
                values=rows(count,group_count,query_count); comps={r.case_id:r.domain_group for r in values}
                self.assertEqual(track_support(values,comps,cfg,training=training,formats=True)["status"],"unavailable")
    def test_missing_format_and_source_support_block_before_training(self):
        from sentinel.url_v3.protocol import assert_training_ready
        splits,cfg,_=synthetic_study(self.root,scenario="no_queries")
        self.assertEqual(splits.manifest["development"]["benign_format_counts"]["query_present"],1)
        with self.assertRaises(DatasetError): assert_training_ready(splits)
        other,cfg,_=synthetic_study(self.root/"other")
        other.manifest["source_development"]["mendeley-webpage-2020"]["status"]="unavailable"
        with self.assertRaises(DatasetError): assert_training_ready(other)
    def test_rehashed_assignment_tamper_is_rejected(self):
        from sentinel.url_v3.protocol import load_protocol
        from sentinel.url_v3.binding import load_v2_binding
        from sentinel.url_v3.mendeley import load_mendeley
        from sentinel.url_v3.sources import joint_catalog
        from sentinel.url_v2.audit import load_audit
        from sentinel.url_v2.storage import read_json,write_json,sha256
        splits,cfg,parser=synthetic_study(self.root)
        binding=load_v2_binding(self.root/"binding",cfg,parser); cat=joint_catalog(binding,load_mendeley(self.root/"sources/mendeley",cfg))
        audit=load_audit(self.root/"audited",cat,parser)
        self.assertEqual(load_protocol(audit,cat,binding,splits.root,cfg,study_root=self.root).manifest,splits.manifest)
        path=splits.root/"assignments.json"; obj=json.loads(path.read_text()); obj["train"].append(obj["primary"][0])
        path.write_text(json.dumps(obj)+"\n",encoding="utf-8")
        manifest=read_json(splits.root/"manifest.json"); manifest["files"]["assignments.json"]=sha256(path); write_json(splits.root/"manifest.json",manifest)
        with self.assertRaises(DatasetError): load_protocol(audit,cat,binding,splits.root,cfg,study_root=self.root)


    def test_actual_missing_source_class_and_reversed_audit_order(self):
        from sentinel.url_v3.protocol import assert_training_ready,_assemble
        from sentinel.url_v3.binding import load_v2_binding
        from sentinel.url_v3.mendeley import load_mendeley
        from sentinel.url_v3.sources import joint_catalog
        from sentinel.url_v2.audit import load_audit,iter_records,iter_provenance
        from unittest.mock import patch
        broken,cfg,parser=synthetic_study(self.root/"missing",scenario="missing_source_class")
        self.assertEqual(broken.manifest["source_development"]["phreshphish"]["class_counts"]["1"],0)
        with self.assertRaises(DatasetError): assert_training_ready(broken)
        splits,cfg,parser=synthetic_study(self.root/"balanced")
        study=splits.study_root
        binding=load_v2_binding(study/"binding",cfg,parser)
        catalog=joint_catalog(binding,load_mendeley(study/"sources/mendeley",cfg))
        audit=load_audit(study/"audited",catalog,parser)
        expected=_assemble(audit,catalog,binding,cfg)
        rows=list(iter_records(audit)); provenance=list(iter_provenance(audit))
        with patch("sentinel.url_v3.protocol.iter_records",return_value=iter(reversed(rows))),patch(
                   "sentinel.url_v3.protocol.iter_provenance",return_value=iter(reversed(provenance))):
            actual=_assemble(audit,catalog,binding,cfg)
        self.assertEqual(actual,expected)

if __name__=="__main__": unittest.main()
