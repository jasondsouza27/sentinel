import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError

class IscxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        self.mapping={"schema":"iscx-local-mapping-v1","official_url":"https://www.unb.ca/cic/datasets/url-2016.html",
          "acquisition_basis":"Official distribution, reviewed by researcher", "acquired_at":"2026-10-07",
          "original_archive":"ISCX-URL-2016.zip","members":[]}
        for category in ("benign","phishing","spam"):
            path=self.root/(category+".txt"); path.write_text("https://"+category+".example/path?q=1\n",encoding="utf-8")
            self.mapping["members"].append({"local_path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
              "original_member":category+"/original.txt","category":category,"evidence_ref":"Official member category reviewed by researcher",
              "format":{"kind":"lines","encoding":"utf-8"}})
    def write(self,value=None):
        p=self.root/"mapping.json"; p.write_text(json.dumps(value or self.mapping)); return p
    def test_explicit_admission_no_network_dates_and_excluded_categories(self):
        from sentinel.url_v2.iscx import admit_iscx,iter_iscx_observations
        from sentinel.url_v2.catalog import load_catalog,merge_catalogs
        from url_v2_fixtures import synthetic_catalog
        with patch("urllib.request.urlopen",side_effect=AssertionError("network used")) as network:
            catalog=admit_iscx(self.write(),self.root/"admitted"); rows=list(iter_iscx_observations(catalog,self.root/"admitted")); network.assert_not_called()
        self.assertEqual([r.original_label for r in rows],["benign","phishing"])
        self.assertEqual(catalog.sources[0]["label_map"],{"benign":0,"phishing":1})
        self.assertTrue(all(r.source_date is None for r in rows)); self.assertEqual(rows[0].reference["member"],"benign/original.txt")
        self.assertEqual(catalog.manifest["excluded_categories"],{"spam":1}); self.assertEqual(load_catalog(self.root/"admitted"),catalog)
        primary=synthetic_catalog(self.root)
        primary=type(primary)(primary.sources[:1],primary.files,primary.manifest)
        merged=merge_catalogs(primary,catalog); self.assertEqual(len(merged.sources),2)
        self.assertIn("child_catalog_sha256",merged.manifest)
    def test_bad_mapping_hash_evidence_member_and_csv_header_rejected(self):
        from sentinel.url_v2.iscx import admit_iscx
        changes=[("official_url","https://mirror.example/x"),("acquisition_basis",""),("original_archive","")]
        variants=[]
        for key,value in changes: bad=copy.deepcopy(self.mapping); bad[key]=value; variants.append(bad)
        for key,value in [("sha256","0"*64),("original_member","../escape"),("original_member",""),("category","unknown"),("evidence_ref","")]:
            bad=copy.deepcopy(self.mapping); bad["members"][0][key]=value; variants.append(bad)
        bad=copy.deepcopy(self.mapping); bad["members"][0]["format"]={"kind":"csv","encoding":"utf-8","header":True,"url_column":"not-present"}; variants.append(bad)
        for i,bad in enumerate(variants):
            with self.subTest(i=i):
                output=self.root/f"bad-{i}"
                with self.assertRaises(DatasetError): admit_iscx(self.write(bad),output)
                self.assertFalse(output.exists())
    def test_positive_only_csv_and_verified_bytes(self):
        from sentinel.url_v2.iscx import admit_iscx,iter_iscx_observations
        bad=copy.deepcopy(self.mapping); bad["members"]=bad["members"][1:2]; member=bad["members"][0]
        local=Path(member["local_path"]); local.write_text('URL,other\nhttps://phishing.example/login,ignored\n')
        member["sha256"]=hashlib.sha256(local.read_bytes()).hexdigest(); member["format"]={"kind":"csv","encoding":"utf-8","header":True,"url_column":"URL"}
        catalog=admit_iscx(self.write(bad),self.root/"positive"); rows=list(iter_iscx_observations(catalog,self.root/"positive"))
        self.assertEqual(len(rows),1); self.assertEqual(rows[0].original_label,"phishing")
        payload=next((self.root/"positive"/"members").iterdir()); payload.write_bytes(b"changed")
        with self.assertRaises(DatasetError): list(iter_iscx_observations(catalog,self.root/"positive"))

if __name__=="__main__": unittest.main()
