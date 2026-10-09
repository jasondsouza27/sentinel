import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_ml import training as legacy
from url_v3_fixtures import synthetic_study,descendant_factory,toy_fit

class V3TrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.splits,self.cfg,self.parser=synthetic_study(self.root)
    def test_descendant_rss_is_counted_and_descendants_are_stopped(self):
        import psutil
        marker=self.root/"child.pid"
        try:
            model,record=legacy.fit_candidate(self.splits.development.partitions["train"],"test",{"marker":str(marker)},
                  self.parser,max_peak_bytes=190*1024**2,pipeline_factory=descendant_factory)
            self.assertEqual(record["status"],"memory_budget_exceeded"); self.assertIsNone(model)
            self.assertGreater(record["observed_tree_rss_peak_bytes"],190*1024**2)
            self.assertTrue(marker.exists(),"worker must reach descendant allocation")
            self.assertFalse(psutil.pid_exists(int(marker.read_text())))
        finally:
            if marker.exists():
                try: psutil.Process(int(marker.read_text())).kill()
                except psutil.NoSuchProcess: pass
    def test_grid_whole_pilot_and_no_final_fitting_with_non_deployable_diagnostic(self):
        from sentinel.url_v3.training import component_pilot_rows,pilot_v3,train_v3
        rows=component_pilot_rows(self.splits,maximum=2000)
        ids={r.case_id for r in rows}; comps={self.splits.component_by_case[r.case_id] for r in rows}
        self.assertLessEqual(len(rows),2000)
        self.assertEqual(ids,{r.case_id for r in self.splits.development.partitions["train"] if self.splits.component_by_case[r.case_id] in comps})
        with patch("sentinel.url_ml.training.fit_candidate",side_effect=toy_fit) as fits,contextlib.redirect_stdout(io.StringIO()):
            pilot=pilot_v3(self.splits,self.cfg,self.parser); self.assertEqual(fits.call_count,2)
            fits.reset_mock(); research=train_v3(self.splits,self.cfg,self.parser)
        self.assertEqual(fits.call_count,11)
        records=research.run.selection.report["configurations"]
        self.assertEqual(sum(r["branch"]=="char_tfidf" for r in records),6)
        self.assertEqual(sum(r["branch"]=="lexical_hgb" for r in records),4)
        train_ids={r.case_id for r in self.splits.development.partitions["train"]}
        for call in fits.call_args_list:
            self.assertTrue({r.case_id for r in call.args[0]}<=train_ids)
            self.assertEqual(call.args[4],4); self.assertEqual(call.args[5],8589934592)
        self.assertFalse(research.format_report["eligible_for_deployment"])
        self.assertIn(research.run.selection.branch,{"char_tfidf","lexical_hgb"})
        self.assertEqual(research.run.calibration.status,"unavailable")
    def test_changed_sidecar_between_fits_aborts_with_only_one_fit(self):
        from sentinel.url_v3.training import train_v3
        def changed(*args,**kwargs):
            with (self.root/"protocol/owners.jsonl").open("a") as f: f.write("corrupt")
            return toy_fit(*args,**kwargs)
        with patch("sentinel.url_ml.training.fit_candidate",side_effect=changed) as fits,contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(DatasetError): train_v3(self.splits,self.cfg,self.parser)
        self.assertEqual(fits.call_count,1)
    def test_failed_mutated_or_scored_study_never_fits(self):
        from sentinel.url_v3.training import train_v3,pilot_v3,fit_checked
        from sentinel.url_v3.access import study_guard,begin_final_access,finish_final_access
        with patch("sentinel.url_ml.training.fit_candidate") as fits:
            with self.assertRaises(DatasetError):
                fit_checked(self.splits,self.cfg,self.parser,self.splits.tracks["primary"],"char_tfidf",legacy.candidate_grid(self.cfg["training"])[0][1])
            with study_guard(self.splits,stage="evaluate"):
                begin_final_access(self.splits,"a"*64,"b"*64); finish_final_access(self.splits,status="failed")
            for function in (train_v3,pilot_v3):
                with self.assertRaisesRegex(DatasetError,"final_protocol_already_accessed"): function(self.splits,self.cfg,self.parser)
            fits.assert_not_called()
        broken,cfg,parser=synthetic_study(self.root/"broken",scenario="missing_source_class")
        with patch("sentinel.url_ml.training.fit_candidate") as fits:
            with self.assertRaises(DatasetError): train_v3(broken,cfg,parser)
            fits.assert_not_called()
    def test_worker_error_never_leaks_url_signature_or_private_path_in_stdout(self):
        from sentinel.url_v3.training import train_v3
        def failure(*args,**kwargs):
            raise RuntimeError("https://data.mendeley.com/file?signature=SECRET C:\\Users\\Jason Dsouza\\private key token=SECRET")
        output=io.StringIO()
        with patch("sentinel.url_ml.training.fit_candidate",side_effect=failure),contextlib.redirect_stdout(output):
            with self.assertRaises(DatasetError) as error: train_v3(self.splits,self.cfg,self.parser)
        for value in (output.getvalue(),json.dumps(error.exception.diagnostics)):
            self.assertNotIn("SECRET",value); self.assertNotIn("https://",value); self.assertNotIn("Jason Dsouza",value)
    def test_tied_and_negative_slope_calibration_are_unavailable(self):
        import numpy as np
        from sentinel.url_ml.calibration import fit_calibration
        labels=np.asarray([0,1]*60)
        self.assertEqual(fit_calibration(labels,np.full(120,.5),.5).report["reason"],"insufficient_score_variation")
        scores=np.where(labels==0,.9,.1)
        self.assertEqual(fit_calibration(labels,scores,.5).report["reason"],"nonpositive_or_invalid_slope")


    def test_fit_checked_requires_study_guard(self):
        from sentinel.url_v3.training import fit_checked
        from sentinel.url_v3.access import study_guard
        params=legacy.candidate_grid(self.cfg["training"])[0][1]
        with patch("sentinel.url_ml.training.fit_candidate",side_effect=toy_fit) as fits:
            with self.assertRaises(DatasetError):
                fit_checked(self.splits,self.cfg,self.parser,self.splits.development.partitions["train"],"char_tfidf",params)
            fits.assert_not_called()
            with study_guard(self.splits,stage="train"):
                fit_checked(self.splits,self.cfg,self.parser,self.splits.development.partitions["train"],"char_tfidf",params)
            self.assertEqual(fits.call_count,1)

if __name__=="__main__": unittest.main()
