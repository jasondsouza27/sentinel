import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from url_v2_fixtures import test_config

class Response(io.BytesIO):
    def __init__(self, body=b"abcdefgh", status=206, headers=None, url="https://us.aws.cdn.hf.co/object?signature=SECRET", fail_after=None):
        super().__init__(body); self.status=status; self.headers={"Content-Range":"bytes 0-7/100", "Content-Length":str(len(body)),"ETag":'"stable"',**(headers or {})}; self.url=url; self.fail_after=fail_after
    def geturl(self): return self.url
    def read(self,n=-1):
        if self.fail_after is not None and self.tell()>=self.fail_after: raise TimeoutError("https://us.aws.cdn.hf.co/object?signature=SECRET")
        if self.fail_after is not None: n=min(n,self.fail_after-self.tell())
        return super().read(n)

class RangeTests(unittest.TestCase):
    def setUp(self):
        from sentinel.url_v2.ranges import RangeSession
        from sentinel.url_v2.contracts import SourceFile,SourceCatalog,PHRESH_REVISION
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.config=test_config()
        self.file=SourceFile("phreshphish",PHRESH_REVISION,"data/train-00000-of-00001.parquet","train",100,"a"*64,"b"*40)
        self.catalog=SourceCatalog((),(self.file,),{"source_files":[self.file.__dict__],"metadata_response_bytes":0})
        self.session=RangeSession(self.catalog,self.root,self.config)
    def invoke(self,responses,start=0,length=8):
        with patch("sentinel.url_v2.ranges.open_response",side_effect=responses) as request:
            result=self.session.read_range(self.file,start,length)
            return result,request.call_count
    def test_verified_cache_resume_and_budget(self):
        from sentinel.url_v2.ranges import RangeSession
        body,calls=self.invoke([Response()]); self.assertEqual(body,b"abcdefgh"); self.assertEqual(calls,1)
        self.assertEqual(self.session.snapshot()["response_bytes"],8)
        resumed=RangeSession(self.catalog,self.root,self.config)
        with patch("sentinel.url_v2.ranges.open_response",side_effect=AssertionError("cache missed")):
            self.assertEqual(resumed.read_range(self.file,0,8),b"abcdefgh")
        self.assertEqual(resumed.snapshot()["response_bytes"],8)
        self.assertNotIn("signature=SECRET",json.dumps(resumed.snapshot()))
        self.assertFalse((self.root/"manifest.json").exists())
        self.config["projection"]["max_response_bytes"]=8
        limited=RangeSession(self.catalog,self.root/"limited",self.config)
        with patch("sentinel.url_v2.ranges.open_response",return_value=Response()): limited.read_range(self.file,0,8)
        with patch("sentinel.url_v2.ranges.open_response") as request:
            with self.assertRaises(DatasetError): limited.read_range(self.file,8,1)
            request.assert_not_called()
    def test_protocol_rejections_are_terminal(self):
        changes=[{"status":200},{"headers":{"Content-Encoding":"gzip"}},{"headers":{"Content-Range":"bytes 1-8/100"}},
                 {"headers":{"Content-Range":"bytes 0-7/101"}},{"headers":{"ETag":'W/"weak"'}},
                 {"headers":{"ETag":""}},{"url":"http://huggingface.co/x"},{"url":"https://evil.example/x"},
                 {"url":"https://u@huggingface.co/x"},{"url":"https://huggingface.co:444/x"},
                 {"body":b"abc","headers":{"Content-Length":"8"}}]
        for change in changes:
            with self.subTest(change=change),patch("sentinel.url_v2.ranges.open_response",return_value=Response(**change)) as request:
                with self.assertRaises(DatasetError): self.session.read_range(self.file,0,8)
                self.assertEqual(request.call_count,1)
    def test_changed_object_cache_corruption_and_invalid_ranges(self):
        self.invoke([Response()])
        with patch("sentinel.url_v2.ranges.open_response",return_value=Response(headers={"Content-Range":"bytes 8-15/100","ETag":'"changed"'})):
            with self.assertRaises(DatasetError): self.session.read_range(self.file,8,8)
        payload=next((self.root/"ranges").glob("*.bin")); payload.write_bytes(b"corrupt!")
        with self.assertRaises(DatasetError): self.session.read_range(self.file,0,8)
        for start,length in [(-1,1),(99,2),(0,0),(False,8),(0,33554433)]:
            with self.subTest(start=start,length=length),patch("sentinel.url_v2.ranges.open_response") as request:
                with self.assertRaises(DatasetError): self.session.read_range(self.file,start,length)
                request.assert_not_called()
        from dataclasses import replace
        with self.assertRaises(DatasetError): self.session.read_range(replace(self.file,path="../private"),0,8)
    def test_partial_attempts_charged_and_retry_limit(self):
        result,calls=self.invoke([Response(fail_after=3),Response()]); self.assertEqual(result,b"abcdefgh"); self.assertEqual(calls,2)
        self.assertEqual(self.session.snapshot()["response_bytes"],11)
        self.assertNotIn("signature=SECRET",json.dumps(self.session.snapshot()))
        self.session=type(self.session)(self.catalog,self.root/"failed",self.config)
        with patch("sentinel.url_v2.ranges.open_response",side_effect=[TimeoutError("expired")]*4) as request:
            with self.assertRaises(DatasetError): self.session.read_range(self.file,0,8)
            self.assertEqual(request.call_count,4)
        self.assertEqual(self.session.snapshot()["attempts"][-1]["error_message"],"expired")
    def test_incomplete_read_and_expired_cdn_location(self):
        import http.client
        import urllib.error
        partial=http.client.IncompleteRead(b"abc",5)
        with patch("sentinel.url_v2.ranges.open_response",side_effect=[partial,Response()]) as request:
            self.assertEqual(self.session.read_range(self.file,0,8),b"abcdefgh")
            self.assertEqual(request.call_count,2)
        self.assertEqual(self.session.snapshot()["response_bytes"],11)
        self.session=type(self.session)(self.catalog,self.root/"expired",self.config)
        expired=urllib.error.HTTPError("https://us.aws.cdn.hf.co/object?signature=SECRET",403,"expired",{},None)
        result,calls=self.invoke([expired,Response()]); self.assertEqual(result,b"abcdefgh"); self.assertEqual(calls,2)
        self.assertNotIn("signature=SECRET",json.dumps(self.session.snapshot()))

    def test_accepted_redirect_bodies_never_bypass_the_range_budget(self):
        from types import SimpleNamespace
        from sentinel.url_v2.ranges import ApprovedRedirect,RangeSession
        class RedirectBody(io.BytesIO):
            def __init__(self, interrupted):
                super().__init__(b'x'*10000); self.received=0; self.interrupted=interrupted
            def read(self,n=-1):
                body=super().read(n); self.received+=len(body)
                if self.interrupted: raise TimeoutError('redirect body interrupted')
                return body
        for status in (301,302,303,307,308):
            for interrupted in (False,True):
                with self.subTest(status=status,interrupted=interrupted):
                    config=json.loads(json.dumps(self.config)); config['projection']['max_response_bytes']=8
                    session=RangeSession(self.catalog,self.root/f'redirect-{status}-{interrupted}',config)
                    body=RedirectBody(interrupted); handler=ApprovedRedirect(config['projection']['allow_hosts'])
                    handler.parent=SimpleNamespace(open=lambda request,timeout:Response())
                    def open_redirect(request,hosts,timeout):
                        request.timeout=timeout
                        return getattr(handler,f'http_error_{status}')(request,body,status,'redirect',{'location':'https://us.aws.cdn.hf.co/object?signature=SECRET'})
                    with patch('sentinel.url_v2.ranges.open_response',side_effect=open_redirect):
                        result=session.read_range(self.file,0,8)
                    self.assertEqual(result,b'abcdefgh')
                    self.assertEqual(body.received,0,'Redirect payload must be closed, never drained outside the byte ledger')
                    self.assertTrue(body.closed)
                    self.assertEqual(session.snapshot()['response_bytes'],8)
                    self.assertNotIn('signature=SECRET',json.dumps(session.snapshot()))

    def test_unapproved_redirect_not_contacted(self):
        from sentinel.url_v2.ranges import ApprovedRedirect
        import urllib.request
        handler=ApprovedRedirect(self.config["projection"]["allow_hosts"])
        for target in ["http://huggingface.co/x","https://evil.example/x","https://x@huggingface.co/x"]:
            with self.assertRaises(DatasetError): handler.redirect_request(urllib.request.Request("https://huggingface.co/x"),None,302,"",{},target)

if __name__=="__main__": unittest.main()
