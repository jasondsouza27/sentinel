import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from url_v2_fixtures import test_config,write_parquet_fixture
from test_url_v2_ranges import Response

class CliTests(unittest.TestCase):
    def test_stdlib_help_and_wrong_runtime_are_explicit(self):
        child=subprocess.run([sys.executable,"-S","-m","sentinel.url_v2.cli","--help"],capture_output=True,text=True,timeout=15)
        self.assertEqual(child.returncode,0,child.stderr); self.assertIn("project-pilot",child.stdout)
        with tempfile.TemporaryDirectory(prefix="sentinel cli ") as td:
            code="import sys; from sentinel.url_v2.cli import main; sys.version_info=(3,13,0); raise SystemExit(main(['freeze','--root',sys.argv[1]]))"
            child=subprocess.run([sys.executable,"-S","-c",code,td],capture_output=True,text=True,timeout=15)
            self.assertEqual(child.returncode,2); self.assertIn("url_v2_requires_python311",child.stdout)
    @unittest.skipUnless(importlib.util.find_spec("pyarrow"),"requires URL data runtime")
    def test_catalog_projection_audit_freeze_with_spaces_and_private_failures(self):
        from sentinel.url_v2.cli import main
        from sentinel.url_v2.contracts import PHRESH_REVISION
        with tempfile.TemporaryDirectory(prefix="sentinel cli ") as td:
            root=Path(td); files={}; inventory={"sha":PHRESH_REVISION,"cardData":{"license":"cc-by-4.0"},"siblings":[]}
            for part in ("train","test"):
                path=root/(part+".parquet"); write_parquet_fixture(path); name=f"data/{part}-00000-of-00001.parquet"; files[name]=path.read_bytes()
                inventory["siblings"].append({"rfilename":name,"size":len(files[name]),"blobId":"b"*40})
            def transport(request,hosts,timeout):
                url=request.full_url
                if "/api/" in url: return Response(json.dumps(inventory).encode(),status=200,url="https://huggingface.co/api/catalog")
                if url.endswith("README.md"): return Response(b"license: cc-by-4.0",status=200,url="https://huggingface.co/card")
                name="data/"+url.rsplit("/",1)[-1]; start,end=map(int,request.get_header("Range").split("=")[1].split("-")); body=files[name][start:end+1]
                return Response(body,headers={"Content-Range":f"bytes {start}-{end}/{len(files[name])}"})
            dataset=root/"private data"
            def run(args):
                output=io.StringIO()
                with contextlib.redirect_stdout(output): status=main([*args,"--root",str(dataset)])
                self.assertNotIn("secret",output.getvalue()); return status,output.getvalue()
            with patch("sentinel.url_v2.catalog.open_response",side_effect=transport),patch("sentinel.url_v2.ranges.open_response",side_effect=transport):
                for command in ("catalog","project-pilot","project"): self.assertEqual(run([command])[0],0)
            self.assertEqual(run(["audit","--psl","resources/url-v2-suffix.dat"])[0],0)
            status,output=run(["freeze"]); self.assertEqual(status,0); self.assertIn('"training_ready": false',output)
            self.assertEqual(run(["project"])[0],2)
            self.assertTrue(any((dataset/"failed-runs").glob("*.json")))
            child=subprocess.run([sys.executable,"-S","-m","sentinel.url_v2.cli","audit","--root",str(dataset),"--psl","resources/url-v2-suffix.dat"],capture_output=True,text=True,timeout=15)
            self.assertEqual(child.returncode,2)
            self.assertFalse((dataset/"cases.db").exists())

if __name__=="__main__": unittest.main()
