import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from url_ml_fixtures import HAS_ML,fixture_psl,sample_dataset

@unittest.skipUnless(HAS_ML,"Optional URL ML environment is not installed")
class FailureReportTests(unittest.TestCase):
    def setUp(self):
        from sentinel.url_ml import training,cli
        from sentinel.url_ml.contracts import DatasetError
        from sentinel.url_ml.urls import UrlParser
        from sentinel.url_ml.splits import freeze_splits
        self.training,self.cli,self.Error=training,cli,DatasetError
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.parser=UrlParser(fixture_psl(self.root))
        self.dataset=sample_dataset(groups=80,parser=self.parser)
        self.splits=freeze_splits(self.dataset,self.root / "split")
        self.config=json.loads(Path("configs/url-ml-v1.json").read_text())

    def failing_fit(self,rows,branch,params,parser,*args,**kwargs):
        return None,{"status":"fit_failed","error":"fixture_resource_failure",
                     "error_type":"MemoryError","error_message":"fixture allocation failed",
                     "branch":branch,"params":params,"peak_bytes":12345,"fit_seconds":.25}

    def test_all_failed_candidates_keep_every_attempt_in_exception(self):
        with patch.object(self.training,"fit_candidate",side_effect=self.failing_fit),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(self.Error) as raised:
                self.training.select_model(self.splits,self.config,self.parser)
        self.assertEqual(raised.exception.reason,"all_candidates_failed")
        report=raised.exception.diagnostics
        self.assertEqual(report["status"],"failed")
        self.assertEqual(len(report["configurations"]),10)
        self.assertEqual(report["training_config"],self.config)
        for record,(branch,params) in zip(report["configurations"],self.training.candidate_grid(self.config)):
            self.assertEqual((record["branch"],record["params"]),(branch,params))
            self.assertEqual(record["error_message"],"fixture allocation failed")
            self.assertEqual(record["peak_bytes"],12345)
            self.assertEqual(record["native_threads"],4)

    def test_first_and_second_pilot_failures_are_saved_without_overwrite(self):
        for failed_branch,count in (("char_tfidf",1),("lexical_hgb",2)):
            with self.subTest(branch=failed_branch):
                def attempt(rows,branch,params,parser,*args):
                    if branch==failed_branch: return self.failing_fit(rows,branch,params,parser)
                    return object(),{"status":"ok","branch":branch,"params":params,"peak_bytes":999,"fit_seconds":.1}
                for repeat in range(2):
                    stdout=io.StringIO()
                    with patch.object(self.training,"fit_candidate",side_effect=attempt),patch.object(self.cli,"_load_root",return_value=(self.parser,self.dataset,self.splits)),contextlib.redirect_stdout(stdout):
                        code=self.cli.main(["pilot","--root",str(self.root)])
                    self.assertEqual(code,2)
                    last=json.loads(stdout.getvalue().splitlines()[-1])
                    report_path=Path(last["diagnostic_path"])
                    report=json.loads(report_path.read_text(encoding="utf-8"))
                    self.assertEqual(len(report["measurements"]),count)
                    self.assertEqual(report["status"],"failed")
                    self.assertEqual(report["measurements"][-1]["error"],"fixture_resource_failure")
                    self.assertEqual(report["measurements"][-1]["params"],next(p for b,p in self.training.candidate_grid(self.config) if b==failed_branch))
                    self.assertIn("ids_sha256",report)
                    self.assertEqual(report["split_provenance"],self.splits.manifest["provenance"])
                    if repeat:
                        self.assertNotEqual(report_path,previous_path)
                        self.assertEqual(previous_path.read_bytes(),previous_bytes)
                    previous_path,previous_bytes=report_path,report_path.read_bytes()
        self.assertFalse((self.root / "pilot.json").exists())
        self.assertEqual(len(list((self.root / "failed-runs").glob("*.json"))),4)

    def test_train_cli_persists_failed_selection_outside_artifact(self):
        artifact=self.root / "immutable-artifact"
        stdout=io.StringIO()
        with patch.object(self.training,"fit_candidate",side_effect=self.failing_fit),patch.object(self.cli,"_load_root",return_value=(self.parser,self.dataset,self.splits)),contextlib.redirect_stdout(stdout):
            code=self.cli.main(["train","--root",str(self.root),"--artifact",str(artifact),"--version","failure-fixture"])
        self.assertEqual(code,2)
        last=json.loads(stdout.getvalue().splitlines()[-1])
        self.assertEqual(last["error"],"all_candidates_failed")
        report=json.loads(Path(last["diagnostic_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(report["configurations"]),10)
        self.assertEqual(report["split_provenance"],self.splits.manifest["provenance"])
        self.assertFalse(artifact.exists())
        progress=json.loads(stdout.getvalue().splitlines()[0])["training_progress"]
        self.assertEqual(progress["params"],self.training.candidate_grid(self.config)[0][1])
        self.assertEqual(progress["error"],"fixture_resource_failure")

    def test_isolated_fit_failure_retains_exception_and_resource_context(self):
        model,record=self.training.fit_candidate(self.dataset.rows,"char_tfidf",{"max_features":0},self.parser)
        self.assertIsNone(model)
        self.assertEqual(record["status"],"fit_failed")
        self.assertIn("max_features",record["error_message"])
        self.assertIn("error_type",record)
        self.assertEqual(record["train_rows"],len(self.dataset.rows))
        self.assertEqual(record["native_threads"],4)
        self.assertGreater(record["peak_bytes"],0)
        self.assertGreater(record["observed_rss_peak_bytes"],0)

if __name__=="__main__": unittest.main()
