import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from url_v2_fixtures import test_config
from test_url_v2_ranges import Response

class CatalogTests(unittest.TestCase):
    def inventory(self):
        from sentinel.url_v2.contracts import PHRESH_REVISION
        return {"sha":PHRESH_REVISION,"cardData":{"license":"cc-by-4.0"},"siblings":[
          {"rfilename":f"data/{part}-00000-of-00001.parquet","size":100,"blobId":"b"*40,"lfs":{"sha256":"a"*64,"size":100}}
          for part in ("train","test")]}
    def test_catalog_pinned_round_trip_byte_checks_and_exclusive_output(self):
        from sentinel.url_v2.catalog import fetch_phresh_catalog,load_catalog
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/"catalog"; raw=json.dumps(self.inventory()).encode(); card=b"license: cc-by-4.0"
            with patch("sentinel.url_v2.catalog.open_response",side_effect=[Response(raw,status=200,url="https://huggingface.co/api/x"),Response(card,status=200,url="https://huggingface.co/card")]) as request:
                result=fetch_phresh_catalog(output,test_config()); self.assertEqual(request.call_count,2)
            self.assertEqual(len(result.files),2); self.assertEqual(result.manifest["metadata_response_bytes"],len(raw)+len(card))
            self.assertEqual(load_catalog(output),result)
            self.assertEqual(result.files[0].expected_sha256,"a"*64)
            with self.assertRaises(DatasetError): fetch_phresh_catalog(output,test_config())
            (output/"inventory.json").write_bytes(b"changed")
            with self.assertRaises(DatasetError): load_catalog(output)
    def test_malformed_inventory_and_unbounded_body_rejected(self):
        from sentinel.url_v2.catalog import fetch_phresh_catalog
        variants=[]
        wrong=self.inventory(); wrong["sha"]="moving"; variants.append(wrong)
        wrong=self.inventory(); wrong["siblings"][0]["size"]=True; variants.append(wrong)
        wrong=self.inventory(); wrong["siblings"]=wrong["siblings"][:1]; variants.append(wrong)
        wrong=self.inventory(); wrong["siblings"].append({"rfilename":"data/extra.parquet","size":100}); variants.append(wrong)
        wrong=self.inventory(); wrong["cardData"]["license"]="unknown"; variants.append(wrong)
        for i,value in enumerate(variants):
            with self.subTest(i=i),tempfile.TemporaryDirectory() as td,patch("sentinel.url_v2.catalog.open_response",return_value=Response(json.dumps(value).encode(),status=200,url="https://huggingface.co/api/x")):
                output=Path(td)/"catalog"
                with self.assertRaises(DatasetError): fetch_phresh_catalog(output,test_config())
                self.assertFalse(output.exists())
        with tempfile.TemporaryDirectory() as td,patch("sentinel.url_v2.catalog.open_response",return_value=Response(b"x"*2097153,status=200,url="https://huggingface.co/api/x")):
            with self.assertRaises(DatasetError): fetch_phresh_catalog(Path(td)/"catalog",test_config())

if __name__=="__main__": unittest.main()
