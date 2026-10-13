import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from url_v3_fixtures import small_v3_research

class V3CompatibilityTests(unittest.TestCase):
    def test_explicit_v3_inference_does_not_import_arrow_or_load_diagnostic(self):
        from sentinel.url_v3.artifacts import export_v3_artifact
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); research,splits,cfg,parser=small_v3_research(root)
            artifact=root/"artifact with spaces"; export_v3_artifact(research,parser,artifact,"synthetic-v3")
            code="""
import importlib.abc,sys
class BlockArrow(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='pyarrow' or fullname.startswith('pyarrow.'): raise ImportError('Arrow blocked')
sys.meta_path.insert(0,BlockArrow())
import joblib
from unittest.mock import patch
from sentinel.url_ml.service import UrlModelService
with patch('joblib.load',wraps=joblib.load) as load:
    service=UrlModelService(sys.argv[1])
    result=service.assess('https://m0-1.example/article?q=1')
    assert result.state=='complete' and result.model_version=='synthetic-v3'
    assert result.probability is None
    assert load.call_count==1 and load.call_args.args[0].name=='pipeline.joblib'
assert not any(n=='pyarrow' or n.startswith('pyarrow.') for n in sys.modules)
print('v3 inference verified without Arrow or diagnostic deserialization')
"""
            child=subprocess.run([sys.executable,"-c",code,str(artifact)],capture_output=True,text=True,timeout=30)
            self.assertEqual(child.returncode,0,child.stderr)
    def test_default_stdlib_server_contract_and_empty_cases(self):
        code="""
import json,sys,tempfile,threading
from pathlib import Path
from urllib.request import Request,urlopen
from sentinel.server import create_server
import sentinel.url_v3.artifacts
with tempfile.TemporaryDirectory() as td:
    server=create_server(port=0,db_path=Path(td)/'cases.db')
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        request=Request(base+'/api/analyze',data=b'{"url":"https://example.org/"}',headers={'Content-Type':'application/json'})
        with urlopen(request) as response: result=json.load(response)
        with urlopen(base+'/api/cases') as response: cases=json.load(response)
        assert {'fraud','harmful_content','profile'} <= set(result) and cases==[]
        assert result['harm_assessment']['state']=='not_assessed'
        assert isinstance(result['assessment_receipt'],str)
        assert not any(n in sys.modules for n in ('numpy','sklearn','pyarrow'))
        print('stdlib and empty cases verified')
    finally: server.shutdown(); server.server_close(); thread.join()
"""
        child=subprocess.run([sys.executable,"-S","-c",code],capture_output=True,text=True,timeout=20)
        self.assertEqual(child.returncode,0,child.stderr)

if __name__=="__main__": unittest.main()
