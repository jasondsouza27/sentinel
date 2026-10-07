import json
import tempfile
import unittest
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_ml.urls import UrlParser
from url_v2_fixtures import synthetic_catalog,synthetic_observation

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        from url_ml_fixtures import fixture_psl
        self.parser=UrlParser(fixture_psl(self.root))
        self.catalog=synthetic_catalog(self.root)
    def observation(self,n,**kwargs): return synthetic_observation(reference={"shard":"fixture.parquet","row":n},**kwargs)
    def test_conflicts_all_excluded_and_cross_source_duplicates_retained(self):
        from sentinel.url_v2.audit import audit_sources,iter_records,iter_provenance,load_audit
        observations=[self.observation(1,original_url="https://Alpha.example:443/a?q=1"),self.observation(2,original_url="https://alpha.example/a?q=1",source_id="iscx-url2016"),
          self.observation(3,original_url="https://conflict.example/x",original_label="benign"),self.observation(4,original_url="https://conflict.example/x",original_label="phish")]
        audit=audit_sources(self.catalog,observations,self.parser,self.root/"audit"); records=list(iter_records(audit)); provenance=list(iter_provenance(audit))
        self.assertEqual(len(records),1); self.assertEqual(records[0].row.url,"https://alpha.example/a?q=1")
        self.assertEqual(set(records[0].observation_ids),{o.observation_id for o in observations[:2]})
        self.assertEqual({x["observation_id"] for x in provenance if x["reason"]=="conflicting_label"},{o.observation_id for o in observations[2:]})
        self.assertEqual(audit.manifest["included_observations"]+sum(audit.manifest["excluded"].values()),4)
        again=audit_sources(self.catalog,reversed(observations),self.parser,self.root/"again")
        for name in ("rows.jsonl","provenance.jsonl","exclusions.jsonl"): self.assertEqual((audit.root/name).read_bytes(),(again.root/name).read_bytes())
        self.assertEqual(load_audit(audit.root,self.catalog,self.parser),audit)
        from sentinel.url_ml.source import load_dataset
        with self.assertRaises(DatasetError): load_dataset(audit.root,self.parser)
        (audit.root/"provenance.jsonl").write_text("")
        with self.assertRaises(DatasetError): load_audit(audit.root,self.catalog,self.parser)
    def test_missing_invalid_oversized_dates_and_no_scheme_repair(self):
        from sentinel.url_v2.audit import audit_sources,iter_provenance
        variants=[{"original_url":None},{"original_label":None},{"original_label":"malware"},{"original_url":"https://alpha.example/"+"x"*2048},
          {"original_url":"alpha.example/path"},{"source_date":"2024-99-42"},{"source_date":"2024-01-01"},{"source_date":None}]
        audit=audit_sources(self.catalog,[self.observation(i+1,**v) for i,v in enumerate(variants)],self.parser,self.root/"audit")
        self.assertEqual(audit.manifest["excluded"],{"missing_source_url":1,"missing_source_label":1,"invalid_source_label":1,"oversized_source_url":1,"url_scheme":1,"malformed_source_date":1})
        dates={x["source_date"]:x["date_interval"] for x in iter_provenance(audit) if not x["reason"]}
        self.assertIsNone(dates["2024-01-01"]); self.assertIsNone(dates[None])
    def test_authenticated_date_only_uses_entire_day_and_tampered_ids_fail(self):
        from sentinel.url_v2.audit import audit_sources,iter_provenance
        self.catalog.sources[0]["date_semantics"]={"meaning":"collection date","evidence_ref":"Reviewed source documentation", "timezone":"UTC","authenticated":True}
        obs=self.observation(1,source_date="2024-01-01")
        audit=audit_sources(self.catalog,[obs],self.parser,self.root/"date")
        interval=next(iter_provenance(audit))["date_interval"]
        self.assertEqual(interval,["2024-01-01T00:00:00.000000+00:00","2024-01-01T23:59:59.999999+00:00"])
        from dataclasses import replace
        with self.assertRaises(DatasetError): audit_sources(self.catalog,[replace(obs,observation_id="0"*64)],self.parser,self.root/"bad")

if __name__=="__main__": unittest.main()
