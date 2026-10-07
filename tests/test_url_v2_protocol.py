import json
import tempfile
import unittest
from pathlib import Path
from sentinel.url_ml.contracts import DatasetError
from url_v2_fixtures import synthetic_audit,synthetic_observation,small_protocol_config

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
    def test_isolated_partitions_gates_and_owner_based_chronology(self):
        from sentinel.url_v2.protocol import freeze_protocol,load_protocol,assert_training_ready
        audit,catalog,parser=synthetic_audit(self.root,authenticated=True); config=small_protocol_config(parser)
        splits=freeze_protocol(audit,catalog,config,self.root/"protocol"); assert_training_ready(splits)
        self.assertEqual(set(splits.development.partitions),{"train","validation","calibration"})
        parts={**splits.development.partitions,**splits.tracks}; owners={}
        for name,rows in parts.items():
            for row in rows:
                component=splits.component_by_case[row.case_id]; self.assertIn(owners.setdefault(component,name),(name,))
        self.assertEqual(splits.manifest["temporal"]["status"],"available")
        self.assertEqual(load_protocol(audit,catalog,self.root/"protocol",config).manifest,splits.manifest)
        with self.assertRaises(DatasetError): freeze_protocol(audit,catalog,config,self.root/"protocol")
        path=self.root/"protocol"/"assignments.json"; values=json.loads(path.read_text()); values["train"].append(values["primary"][0]); path.write_text(json.dumps(values))
        with self.assertRaises(DatasetError): load_protocol(audit,catalog,self.root/"protocol",config)
    def test_reserved_test_wins_domain_and_source_scoped_opaque_connections(self):
        from sentinel.url_v2.protocol import freeze_protocol
        observations=[]
        def add(url,part,source="phreshphish",opaque=None):
            observations.append(synthetic_observation(reference={"shard":"fixture","row":len(observations)+1},original_url=url,original_partition=part,source_id=source,opaque_id=opaque))
        add("https://a.example/article?q=1","train",opaque="same")
        add("https://b.example/article?q=1","test",opaque="same")
        add("https://a.example/external?q=1","benign","iscx-url2016")
        add("https://independent.example/article?q=1","benign","iscx-url2016",opaque="same")
        audit,catalog,parser=synthetic_audit(self.root,observations); splits=freeze_protocol(audit,catalog,small_protocol_config(parser),self.root/"protocol")
        self.assertEqual([r.url for r in splits.tracks["primary"]],["https://b.example/article?q=1"])
        self.assertEqual([r.url for r in splits.tracks["external"]],["https://independent.example/article?q=1"])
        self.assertEqual(sum(len(r) for r in splits.development.partitions.values()),0)
        self.assertEqual(splits.manifest["tracks"]["external"]["status"],"unavailable")
        self.assertIn("missing_class_or_support",splits.manifest["tracks"]["external"]["reasons"])
        self.assertEqual(splits.manifest["temporal"]["status"],"unavailable")
    def test_cap_never_cuts_giant_components(self):
        from sentinel.url_v2.protocol import choose_components
        selected,skips=choose_components({"giant":range(200001),"small":range(2)},200000,42)
        self.assertEqual(selected,["small"]); self.assertEqual(skips,{"giant":"development_cap"})
    def test_equal_interleaved_missing_dates_and_semantic_assignment_tamper(self):
        from sentinel.url_v2.protocol import freeze_protocol,load_protocol
        from sentinel.url_v2.storage import sha256,write_json,read_json
        for name,development_date,test_date in (("equal","2024-01-01","2024-01-01"),("interleaved","2025-01-01","2024-01-01"),("missing",None,"2025-01-01")):
            root=self.root/name; root.mkdir(); observations=[]
            for part,date in (("train",development_date),("test",test_date)):
                for label in (0,1):
                    observations.append(synthetic_observation(reference={"shard":"fixture","row":len(observations)+1},original_partition=part,
                      original_url=f"https://{part}-{label}.example/page?q=1",original_label="phish" if label else "benign",source_date=date))
            audit,catalog,parser=synthetic_audit(root,observations,authenticated=True); config=small_protocol_config(parser)
            splits=freeze_protocol(audit,catalog,config,root/"protocol")
            self.assertEqual(splits.manifest["temporal"]["status"],"unavailable")
        path=root/"protocol"/"assignments.json"; assignments=read_json(path); assignments["train"].append(assignments["primary"][0]); write_json(path,assignments)
        manifest=read_json(root/"protocol"/"manifest.json"); manifest["files"]["assignments.json"]=sha256(path); write_json(root/"protocol"/"manifest.json",manifest)
        with self.assertRaises(DatasetError): load_protocol(audit,catalog,root/"protocol",config)

    def test_input_reordering_deterministic_and_missing_formats_block_training(self):
        from sentinel.url_v2.protocol import freeze_protocol,assert_training_ready
        audit,catalog,parser=synthetic_audit(self.root); config=small_protocol_config(parser)
        first=freeze_protocol(audit,catalog,config,self.root/"one"); second=freeze_protocol(audit,catalog,config,self.root/"two")
        self.assertEqual((self.root/"one"/"assignments.json").read_bytes(),(self.root/"two"/"assignments.json").read_bytes())
        self.assertEqual(first.manifest["temporal"]["status"],"unavailable")
        config["support"]["benign_min_query"]=100000
        failed=freeze_protocol(audit,catalog,config,self.root/"failed")
        with self.assertRaises(DatasetError): assert_training_ready(failed)
        self.assertEqual(failed.manifest["tracks"]["primary"]["status"],"unavailable")

if __name__=="__main__": unittest.main()
