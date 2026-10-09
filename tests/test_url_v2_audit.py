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
        import hashlib
        self.assertEqual(records[0].row.case_id,hashlib.sha256(b"https://alpha.example/a?q=1").hexdigest())
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
    def test_ancillary_failures_cannot_hide_cross_source_label_conflicts(self):
        from sentinel.url_v2.audit import audit_sources,iter_records,iter_provenance,load_audit
        cases=[({'source_date':'2024-99-99'},'malformed_source_date'),
               ({'opaque_id':'x'*4097},'invalid_or_oversized_opaque_id')]
        for i,(ancillary,reason) in enumerate(cases):
            with self.subTest(reason=reason):
                benign=self.observation(100+i*2,original_url='https://conflict.example/a',original_label='benign')
                phish=self.observation(101+i*2,source_id='iscx-url2016',original_url='https://CONFLICT.example:443/a',original_label='phishing',**ancillary)
                audit=audit_sources(self.catalog,[benign,phish],self.parser,self.root/f'ancillary-{i}')
                self.assertEqual(list(iter_records(audit)),[],'A known contradictory label must exclude the complete canonical URL')
                self.assertEqual(audit.manifest['excluded'],{'conflicting_label':2})
                observations={o['observation_id']:o for o in iter_provenance(audit)}
                self.assertEqual(observations[phish.observation_id]['original_exclusion_reason'],reason)
                self.assertEqual(observations[phish.observation_id]['source_date'],phish.source_date)
                self.assertEqual(load_audit(audit.root,self.catalog,self.parser),audit)

    def test_record_scan_keeps_exact_representatives_without_per_row_queries(self):
        from sentinel.url_v2.audit import _stage,_records
        observations=[self.observation(i+1,original_url=f"https://site{i}.example/article?q=1",original_label="benign" if i%2 else "phish") for i in range(60)]
        duplicate=self.observation(100,original_url="https://SITE0.example:443/article?q=1",original_label="phish",source_date="2025-01-02")
        observations.extend([duplicate,self.observation(101,original_url="https://conflict.example/",original_label="benign"),
          self.observation(102,original_url="https://conflict.example/",original_label="phish"),self.observation(103,original_url=None)])
        db=_stage(self.catalog,observations,self.parser,self.root/"scan.sqlite"); self.addCleanup(db.close)
        statements=[]; db.set_trace_callback(statements.append); records=list(_records(db)); db.set_trace_callback(None)
        self.assertEqual(len(records),60)
        self.assertEqual([r.row.case_id for r in records],sorted(r.row.case_id for r in records))
        self.assertEqual({r.row.url for r in records},{f"https://site{i}.example/article?q=1" for i in range(60)})
        record=next(r for r in records if r.row.url=="https://site0.example/article?q=1")
        pair=[observations[0],duplicate]; first=min(pair,key=lambda o:o.observation_id)
        self.assertEqual(record.observation_ids,tuple(sorted(o.observation_id for o in pair)))
        self.assertEqual(record.row.original_url,first.original_url); self.assertEqual(record.row.source_date,first.source_date)
        self.assertLessEqual(sum(q.lstrip().upper().startswith("SELECT") for q in statements),3,
          "Canonical record iteration must use a bounded scan rather than two extra queries per URL")

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
