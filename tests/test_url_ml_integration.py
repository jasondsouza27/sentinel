import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request,urlopen
from sentinel.analysis import analyze
from sentinel.server import create_server
from url_ml_fixtures import HAS_ML,fixture_psl,small_run

class OptionalCompatibilityTests(unittest.TestCase):
    def test_dependency_free_subprocess_and_missing_configured_artifact(self):
        code = """
import json,tempfile,threading,sys
from pathlib import Path
from urllib.request import Request,urlopen
from sentinel.server import create_server
with tempfile.TemporaryDirectory() as folder:
    server=create_server(port=0,db_path=Path(folder)/'cases.db',url_model_path=Path(folder)/'missing')
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        with urlopen(base+'/api/health') as response: health=json.load(response)
        request=Request(base+'/api/analyze',data=json.dumps({'url':'https://example.org/'}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request) as response: result=json.load(response)
        assert health['url_model']['state']=='unavailable'
        assert result['url_assessment']['state']=='unavailable'
        assert 'numpy' not in sys.modules and 'sklearn' not in sys.modules
        print('dependency-free configured server verified')
    finally:
        server.shutdown(); server.server_close(); thread.join()
"""
        result=subprocess.run([sys.executable,"-S","-c",code],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_disabled_shape_and_no_silent_selection_from_message(self):
        from sentinel.url_ml.service import UrlModelService
        payload={"message":"Look at https://link.example/a"}
        baseline=analyze(payload)
        self.assertEqual(set(baseline),{"fraud","harmful_content","profile"})
        with tempfile.TemporaryDirectory() as folder:
            model=UrlModelService(Path(folder)/"missing")
            assessed=analyze(payload,url_model=model)
        self.assertEqual(assessed["fraud"],baseline["fraud"])
        self.assertEqual(assessed["url_assessment"]["state"],"not_assessed")
        self.assertTrue(any("explicit URL" in line for line in assessed["url_assessment"]["unavailable_checks"]))

@unittest.skipUnless(HAS_ML,"Optional URL ML environment is not installed")
class LearnedIntegrationTests(unittest.TestCase):
    def test_separate_unsaved_and_case_export_retains_model_version(self):
        from sentinel.url_ml.urls import UrlParser
        from sentinel.url_ml.artifacts import export_artifact
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); parser=UrlParser(fixture_psl(root)); artifact=root / "model"
            export_artifact(small_run(parser),parser,artifact,"fixture-v1")
            server=create_server(port=0,db_path=root / "cases.db",url_model_path=artifact)
            worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
            base=f"http://127.0.0.1:{server.server_port}"
            def request(path,payload=None,method=None):
                data=json.dumps(payload).encode() if payload is not None else None
                headers={"Content-Type":"application/json"} if data else {}
                with urlopen(Request(base+path,data=data,headers=headers,method=method),timeout=10) as response: return json.load(response)
            try:
                payload={"message":"You are an idiot", "url":"https://example.org/A?Token=X", "profile":{"followers_count":2}}
                baseline=analyze(payload); result=request("/api/analyze",payload)
                self.assertEqual(result["url_assessment"]["state"],"complete")
                for field in baseline: self.assertEqual(result[field],baseline[field])
                self.assertEqual(request("/api/cases"),[])
                self.assertEqual(request("/api/health")["url_model"]["model_version"],"fixture-v1")
                case=request("/api/cases",{"input":payload})
                exported=request(f"/api/cases/{case['id']}/report")
                self.assertEqual(exported["result"]["url_assessment"]["model_version"],"fixture-v1")
                request(f"/api/cases/{case['id']}",method="DELETE")
                self.assertEqual(request("/api/cases"),[])
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=3)

if __name__=="__main__": unittest.main()
