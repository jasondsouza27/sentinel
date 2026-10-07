import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from url_ml_fixtures import HAS_ML
from url_v2_fixtures import small_v2_research,synthetic_observation,synthetic_catalog,test_config

class DefaultV2Compatibility(unittest.TestCase):
    def test_stdlib_server_keeps_original_keys_and_no_saved_cases(self):
        code="""
import json,sys,tempfile,threading
from pathlib import Path
from urllib.request import Request,urlopen
from sentinel.server import create_server
import sentinel.url_v2.cli
with tempfile.TemporaryDirectory() as td:
    server=create_server(port=0,db_path=Path(td)/'cases.db'); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        request=Request(base+'/api/analyze',data=b'{"url":"https://example.org/"}',headers={'Content-Type':'application/json'})
        with urlopen(request) as response: result=json.load(response)
        with urlopen(base+'/api/cases') as response: cases=json.load(response)
        assert set(result)=={'fraud','harmful_content','profile'} and cases==[]
        assert not any(name in sys.modules for name in ('pyarrow','sklearn','numpy'))
        print('stdlib and case ownership verified')
    finally: server.shutdown(); server.server_close(); thread.join()
"""
        child=subprocess.run([sys.executable,"-S","-c",code],capture_output=True,text=True,timeout=20)
        self.assertEqual(child.returncode,0,child.stderr)

@unittest.skipUnless(HAS_ML,"requires ML runtime")
class ConfiguredV2Compatibility(unittest.TestCase):
    def test_explicit_v2_artifact_unsaved_prediction(self):
        from sentinel.url_v2.artifacts import export_v2_artifact
        from sentinel.url_v2.cli import main
        from sentinel.server import create_server
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); research,splits,config,parser=small_v2_research(root); artifact=root/"artifact with spaces"
            export_v2_artifact(research,parser,artifact,"fixture-v2"); output=io.StringIO()
            with contextlib.redirect_stdout(output): status=main(["predict","--artifact",str(artifact),"--url","https://alpha.example/article?q=1"])
            self.assertEqual(status,0); self.assertEqual(json.loads(output.getvalue())["model_version"],"fixture-v2")
            server=create_server(port=0,db_path=root/"cases.db",url_model_path=artifact); worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
            base=f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(Request(base+"/api/analyze",data=b'{"url":"https://alpha.example/article?q=1"}',headers={"Content-Type":"application/json"})) as response: result=json.load(response)
                self.assertEqual(result["url_assessment"]["model_version"],"fixture-v2")
                with urlopen(base+"/api/cases") as response: self.assertEqual(json.load(response),[])
            finally: server.shutdown(); server.server_close(); worker.join()
    def test_all_failed_fits_keep_private_context_and_no_artifact(self):
        from sentinel.url_v2.cli import main
        from sentinel.url_v2.audit import audit_sources
        from sentinel.url_v2.catalog import load_catalog,merge_catalogs
        from sentinel.url_v2.protocol import freeze_protocol
        from sentinel.url_v2.storage import write_json,sha256
        from sentinel.url_v2.contracts import SourceCatalog,CATALOG_SCHEMA,PHRESH_REVISION
        from sentinel.url_ml.urls import UrlParser
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); catalog_root=root/"sources"/"phreshphish"/"catalog"; catalog_root.mkdir(parents=True)
            source=test_config()["sources"]["phreshphish"]; write_json(catalog_root/"inventory.json",{})
            manifest={"schema":CATALOG_SCHEMA,"sources":[source],"source_files":[],"metadata_response_bytes":0,"files":{"inventory.json":sha256(catalog_root/"inventory.json")}}
            write_json(catalog_root/"manifest.json",manifest); primary=load_catalog(catalog_root); catalog=merge_catalogs(primary,None)
            import shutil
            shutil.copyfile("resources/url-v2-suffix.dat",root/"sources"/"suffix.dat"); parser=UrlParser(root/"sources"/"suffix.dat")
            observations=[]; ordinal=0
            for part,groups,per_group in (("train",500,6),("test",150,2)):
                for group in range(groups):
                    for n in range(per_group):
                        ordinal+=1; observations.append(synthetic_observation(reference={"shard":"fixture","row":ordinal},original_partition=part,
                          original_url=f"https://{part}{group}.example/article-{n}?q=1",original_label="phish" if n%2 else "benign"))
            audit=audit_sources(catalog,observations,parser,root/"audited"); freeze_protocol(audit,catalog,test_config(),root/"protocol")
            output=io.StringIO(); artifact=root/"never-created"
            with patch("sentinel.url_ml.training.fit_candidate",return_value=(None,{"status":"fit_failed","error_type":"ValueError","error_message":"https://example.org/?token=SECRET","peak_bytes":123})),contextlib.redirect_stdout(output):
                status=main(["train","--root",str(root),"--artifact",str(artifact),"--version","failed"])
            self.assertEqual(status,2); self.assertFalse(artifact.exists()); self.assertNotIn("token=SECRET",output.getvalue())
            diagnostic=json.loads(next((root/"failed-runs").glob("*.json")).read_text())
            self.assertEqual(len(diagnostic["diagnostics"]["configurations"]),10)
            self.assertEqual(diagnostic["diagnostics"]["training_config"]["max_peak_bytes"],8589934592)
            self.assertNotIn("token=SECRET",json.dumps(diagnostic))

if __name__=="__main__": unittest.main()
