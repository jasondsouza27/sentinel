import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v3.contracts import default_config
from sentinel.url_v2.storage import manifest_hash
from url_v3_fixtures import synthetic_v2_root, mendeley_fixture

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
    def test_only_url_label_pins_and_logical_records_are_projected(self):
        from sentinel.url_v3.mendeley import load_mendeley,iter_mendeley_observations
        body=b'\xef\xbb\xbfurl,ignored,status\r\nhttps://one.example/path,"quoted\nline",legitimate\r\nhttps://two.example/,0,phishing\r\n'
        catalog,cfg,calls=mendeley_fixture(self.root/"source",default_config(),body)
        self.assertEqual(len(calls),3)
        rows=list(iter_mendeley_observations(self.root/"source",load_mendeley(self.root/"source",cfg)))
        self.assertEqual([r.reference["record"] for r in rows],[1,2])
        for row in rows:
            self.assertEqual(set(row.reference),{"file_id","file_sha256","record"})
            self.assertEqual(row.reference["file_sha256"],cfg["sources"]["mendeley"]["sha256"])
            self.assertIsNone(row.source_date); self.assertIsNone(row.opaque_id)
            self.assertEqual(row.original_partition,"source")
            self.assertEqual(row.observation_id,manifest_hash({"source_id":row.source_id,"revision":row.revision,"reference":row.reference}))
        self.assertFalse(any("ignored" in vars(r) for r in rows))
    def test_invalid_official_identity_license_and_whole_file_fail_before_publication(self):
        from sentinel.url_v3.mendeley import load_mendeley
        changes=[lambda e,p:e.update(id="different"),lambda e,p:e.update(filename="wrong.csv"),
                 lambda e,p:e["content_details"].update(sha256_hash="0"*64),
                 lambda e,p:p.update(version="2"),lambda e,p:p["license"].update(text="unknown")]
        for i,change in enumerate(changes):
            target=self.root/str(i)/"source"
            with self.subTest(change=i),self.assertRaises(DatasetError):
                mendeley_fixture(target,default_config(),b"url,status\nhttps://x.example/,legitimate\n",metadata_change=change)
            self.assertFalse(target.exists())
        target=self.root/"valid"; _,cfg,_=mendeley_fixture(target,default_config(),b"url,status\nhttps://x.example/,legitimate\n")
        (target/cfg["sources"]["mendeley"]["filename"]).write_bytes(b"corrupt")
        with self.assertRaises(DatasetError): load_mendeley(target,cfg)
    def test_strict_utf8_headers_width_byte_fields_and_record_cap(self):
        invalid=[b"url,status\n\xff,legitimate\n",b"url,url,status\nx,x,legitimate\n",
                 b"url,,status\nx,0,legitimate\n",b"url,label\nx,legitimate\n",
                 b"url,status\nx,legitimate,extra\n",b"url,status\nx\n",
                 ("url,status,unused\nhttps://x.example/,legitimate,"+"\u00e9"*8193+"\n").encode(),
                 b"url,status\n"+b"https://x.example/,legitimate\n"*20001]
        for i,body in enumerate(invalid):
            target=self.root/str(i)/"source"
            with self.subTest(case=i),self.assertRaises(DatasetError): mendeley_fixture(target,default_config(),body)
            self.assertFalse(target.exists())
    def test_empty_cells_and_unknown_labels_remain_auditable_exclusions(self):
        from sentinel.url_v3.mendeley import iter_mendeley_observations
        from sentinel.url_v2.audit import audit_sources,iter_provenance
        from sentinel.url_ml.urls import UrlParser
        from url_ml_fixtures import fixture_psl
        body=b"url,status\n,legitimate\nhttps://x.example/,\nhttps://y.example/,BENIGN\n"
        cat,cfg,_=mendeley_fixture(self.root/"source",default_config(),body)
        obs=list(iter_mendeley_observations(self.root/"source",cat))
        audit=audit_sources(cat,obs,UrlParser(fixture_psl(self.root)),self.root/"audit")
        self.assertEqual(sorted(p["reason"] for p in iter_provenance(audit)),
                         ["invalid_source_label","missing_source_label","missing_source_url"])
        self.assertEqual(obs[0].original_url,""); self.assertEqual(obs[1].original_label,"")
    def test_joint_catalog_preserves_conflicts_from_invalid_ancillary_observations(self):
        from sentinel.url_v3.binding import bind_v2
        from sentinel.url_v3.sources import joint_catalog,audit_v3
        from sentinel.url_v3.mendeley import iter_mendeley_observations
        from sentinel.url_v2.audit import audit_sources,iter_provenance
        from sentinel.url_v2.projection import iter_phresh_observations
        v2,cfg,parser=synthetic_v2_root(self.root)
        binding=bind_v2(v2,self.root/"binding",cfg,parser)
        cat,cfg,_=mendeley_fixture(self.root/"source",cfg,b"url,status\nhttps://dev.example/article?x=1,phishing\n")
        joint=joint_catalog(binding,cat); self.assertNotIn("external_status",joint.manifest)
        self.assertEqual(len(joint.sources),2)
        # Shared auditor must retain a malformed date's contradiction.
        old=list(iter_phresh_observations(v2/"sources/phreshphish/projection",binding.catalog))
        old[0]=replace(old[0],source_date="bad-date")
        audit=audit_sources(joint,old+list(iter_mendeley_observations(self.root/"source",cat)),parser,self.root/"ancillary")
        conflict=[p for p in iter_provenance(audit) if p["reason"]=="conflicting_label"]
        self.assertEqual(len(conflict),2)
        self.assertIn("malformed_source_date",[p.get("original_exclusion_reason") for p in conflict])
        result=audit_v3(binding,self.root/"source",cfg,parser,self.root/"joint")
        self.assertEqual(result.manifest["excluded"]["conflicting_label"],2)
    def test_rehashed_projection_cannot_substitute_csv_observations(self):
        from sentinel.url_v3.mendeley import load_mendeley
        from sentinel.url_v2.storage import sha256,write_json
        target=self.root/"source"; _,cfg,_=mendeley_fixture(target,default_config(),b"url,status\nhttps://x.example/,legitimate\n")
        path=target/"observations.jsonl"; row=json.loads(path.read_text()); row["original_label"]="phishing"
        path.write_text(json.dumps(row)+"\n",encoding="utf-8")
        manifest=json.loads((target/"manifest.json").read_text()); manifest["files"]["observations.jsonl"]=sha256(path)
        write_json(target/"manifest.json",manifest)
        with self.assertRaises(DatasetError): load_mendeley(target,cfg)

if __name__=="__main__": unittest.main()
