import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v3.contracts import default_config

class Response(io.BytesIO):
    def __init__(self, body=b"abcdefgh", status=200, headers=None, fail_after=None):
        super().__init__(body); self.status=status
        self.headers=headers or {}; self.fail_after=fail_after; self.read_calls=0
    def geturl(self): return "https://data.mendeley.com/object?signature=SECRET"
    def read(self,n=-1):
        self.read_calls+=1
        if self.fail_after is not None and self.tell()>=self.fail_after: raise TimeoutError("SECRET")
        if self.fail_after is not None: n=min(n,self.fail_after-self.tell())
        return super().read(n)

class TransportTests(unittest.TestCase):
    def setUp(self):
        from sentinel.url_v3.transport import AcquisitionSession
        self.cls=AcquisitionSession; self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"session"; self.config=default_config()
        self.url=self.config["sources"]["mendeley"]["download_url"]
        source=self.config["sources"]["mendeley"]
        source["size"]=8; source["sha256"]=hashlib.sha256(b"abcdefgh").hexdigest()
        self.config["acquisition"]["max_csv_bytes"]=8
    def fetch(self,session):
        return session.fetch(self.url,self.root/"payload.csv",resource="csv",max_bytes=8)
    def test_verified_receipt_and_identity_request_are_reused(self):
        with self.cls(self.root,self.config) as session:
            with patch("sentinel.url_v3.transport.open_response",return_value=Response()) as request:
                receipt=self.fetch(session)
            self.assertEqual(receipt["sha256"],self.config["sources"]["mendeley"]["sha256"])
            req,hosts,timeout=request.call_args.args
            self.assertEqual(req.get_header("Accept-encoding"),"identity"); self.assertEqual(timeout,30)
            self.assertEqual(session.snapshot()["received_body_bytes"],8)
        with self.cls(self.root,self.config) as session:
            with patch("sentinel.url_v3.transport.open_response",side_effect=AssertionError("no network")):
                self.assertEqual(self.fetch(session),receipt)
            self.assertNotIn("SECRET",json.dumps(session.snapshot()))
        (self.root/"payload.csv").write_bytes(b"corrupt!")
        with self.cls(self.root,self.config) as session:
            with self.assertRaises(DatasetError): self.fetch(session)
    def test_errors_partial_retries_and_three_attempts_are_durable(self):
        error=urllib.error.HTTPError(self.url,503,"unavailable",{},Response(b"err",503))
        with self.cls(self.root,self.config) as session:
            with patch("sentinel.url_v3.transport.open_response",side_effect=[error,Response(fail_after=3),Response()]) as request:
                self.fetch(session)
            self.assertEqual(request.call_count,3); self.assertEqual(session.snapshot()["received_body_bytes"],14)
        root=self.root/"failed"
        with self.cls(root,self.config) as session:
            with patch("sentinel.url_v3.transport.open_response",side_effect=TimeoutError("SECRET")) as request:
                with self.assertRaises(DatasetError):
                    session.fetch(self.url,root/"payload.csv",resource="csv",max_bytes=8)
                self.assertEqual(request.call_count,3)
        with self.cls(root,self.config) as session:
            with patch("sentinel.url_v3.transport.open_response") as request:
                with self.assertRaises(DatasetError):
                    session.fetch(self.url,root/"payload.csv",resource="csv",max_bytes=8)
                request.assert_not_called()
    def test_chunked_oversize_rejected_bodies_and_global_budget(self):
        for index,response in enumerate([Response(b"x"*50),Response(b"err",400),
                                         Response(b"abc",headers={"Content-Encoding":"gzip"}),
                                         Response(b"wrong!!!")]):
            root=self.root/str(index)
            with self.cls(root,self.config) as session:
                with patch("sentinel.url_v3.transport.open_response",return_value=response):
                    with self.assertRaises(DatasetError):
                        session.fetch(self.url,root/"payload.csv",resource="csv",max_bytes=8)
                self.assertGreater(session.snapshot()["received_body_bytes"],0)
                self.assertFalse((root/"payload.csv").exists())
        self.config["acquisition"]["max_received_body_bytes"]=5
        with self.cls(self.root,self.config) as session:
            with patch("sentinel.url_v3.transport.open_response",return_value=Response()):
                with self.assertRaises(DatasetError): self.fetch(session)
            self.assertEqual(session.snapshot()["received_body_bytes"],5)
            self.assertFalse((self.root/"payload.csv").exists())
    def test_complete_unregistered_payload_is_not_a_cache_hit_and_lock_is_exclusive(self):
        self.root.mkdir(); (self.root/"payload.csv").write_bytes(b"abcdefgh")
        with self.cls(self.root,self.config) as session:
            with self.assertRaises(DatasetError):
                with self.cls(self.root,self.config): pass
            with patch("sentinel.url_v3.transport.open_response",return_value=Response()) as request:
                self.fetch(session)
            self.assertEqual(request.call_count,1)
            self.assertEqual(session.snapshot()["received_body_bytes"],8)
            self.assertFalse(list(self.root.glob(".pending-fetch-*")))
    def test_crash_reservation_remains_charged_and_orphans_are_removed(self):
        with self.cls(self.root,self.config) as session:
            session.state["inflight_bytes"]=3; session._save()
        (self.root/".pending-fetch-test").write_bytes(b"abc")
        with self.cls(self.root,self.config) as session:
            self.assertEqual(session.snapshot()["interrupted_body_bytes_upper_bound"],3)
            self.assertFalse((self.root/".pending-fetch-test").exists())
            with patch("sentinel.url_v3.transport.open_response",return_value=Response()): self.fetch(session)
            self.assertEqual(session.snapshot()["received_body_bytes"],8)
    def test_all_redirect_statuses_close_without_draining(self):
        from sentinel.url_v2.ranges import ApprovedRedirect
        for status in (301,302,303,307,308):
            with self.subTest(status=status):
                body=Response(b"x"*50000); handler=ApprovedRedirect(self.config["acquisition"]["allow_hosts"])
                handler.parent=SimpleNamespace(open=lambda request,timeout:Response())
                def redirect(request,hosts,timeout):
                    request.timeout=timeout
                    return getattr(handler,"http_error_"+str(status))(request,body,status,"",{"location":self.url})
                root=self.root/str(status)
                with self.cls(root,self.config) as session,patch("sentinel.url_v3.transport.open_response",side_effect=redirect):
                    session.fetch(self.url,root/"payload.csv",resource="csv",max_bytes=8)
                    self.assertEqual(session.snapshot()["received_body_bytes"],8)
                self.assertEqual(body.read_calls,0); self.assertTrue(body.closed)
    def test_unapproved_targets_fail_before_network(self):
        for url in ["http://data.mendeley.com/x","https://u@data.mendeley.com/x",
                    "https://data.mendeley.com:444/x","https://evil.example/x"]:
            with self.cls(self.root,self.config) as session,patch("sentinel.url_v3.transport.open_response") as request:
                with self.assertRaises(DatasetError):
                    session.fetch(url,self.root/"payload.csv",resource="csv",max_bytes=8)
                request.assert_not_called()

if __name__=="__main__": unittest.main()
