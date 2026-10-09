import contextlib
import copy
import hashlib
import io
import json
import subprocess
import shutil
from dataclasses import replace
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sentinel.url_ml.contracts import DatasetError
from sentinel.url_v2.storage import read_json,write_json
from url_v3_fixtures import hashes,synthetic_v2_root,synthetic_study
from test_url_v3_transport import Response

class V3CliTests(unittest.TestCase):
    def run_cli(self,args,config=None):
        from sentinel.url_v3.cli import main
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            if config is None: status=main(args)
            else:
                # Reduced synthetic grids/pins are permitted only by this test patch.
                with patch("sentinel.url_v3.cli.load_config",return_value=config): status=main(args)
        return status,output.getvalue()
    def test_stdlib_help_runtime_and_stage_arguments(self):
        child=subprocess.run([sys.executable,"-S","-m","sentinel.url_v3.cli","--help"],capture_output=True,text=True,timeout=15)
        self.assertEqual(child.returncode,0,child.stderr)
        for name in ("bind-v2","acquire-mendeley","audit","freeze","pilot","train","evaluate","predict"): self.assertIn(name,child.stdout)
        from sentinel.url_v3.cli import main
        for args in (["freeze"],["bind-v2","--root","unused"],["audit","--root","unused","--v2-root","other"]):
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit): main(args)
        with tempfile.TemporaryDirectory(prefix="sentinel runtime ") as td:
            script="import sys; from sentinel.url_v3.cli import main; sys.version_info=(3,13,0); raise SystemExit(main(['freeze','--root',sys.argv[1]]))"
            child=subprocess.run([sys.executable,"-S","-c",script,td],capture_output=True,text=True,timeout=15)
            self.assertEqual(child.returncode,2); self.assertIn("url_v3_requires_python311",child.stdout)
            self.assertTrue(list((Path(td)/"failed-runs").glob("*.json")))
    def test_all_eight_real_stages_with_synthetic_bytes_and_spaces(self):
        with tempfile.TemporaryDirectory(prefix="sentinel v3 cli ") as td:
            home=Path(td); root=home/"private study"; (home/"old input").mkdir(); old,cfg,parser=synthetic_v2_root(home/"old input")
            original=hashes(old)
            for key in cfg["support"]: cfg["support"][key]=1
            cfg["training"]["char_tfidf"].update(max_features=200,C=[1],class_weight=[None])
            cfg["training"]["lexical_hgb"].update(max_depth=[3],learning_rate=[.1],max_iter=5)
            body=("url,status\n"+"\n".join(f"https://m{label}-{i}.example/article?q={i},{'phishing' if label else 'legitimate'}" for label in (0,1) for i in range(40))+"\n").encode()
            source=cfg["sources"]["mendeley"]; source.update(size=len(body),sha256=hashlib.sha256(body).hexdigest())
            entry={"id":source["file_id"],"filename":source["filename"],"size":len(body),"status":"COMPLETED",
                   "content_details":{"size":len(body),"sha256_hash":source["sha256"],"download_url":source["download_url"]}}
            page={"@type":"Dataset","name":"Web page phishing detection","version":"3","sameAs":source["landing_page"],
                  "url":"http://doi.org/"+source["doi"],"license":{"text":"CC BY 4.0","url":"http://creativecommons.org/licenses/by/4.0"},
                  "author":{"name":"Abdelhakim Hannousse"},"citation":{"text":"Hannousse, Abdelhakim; Yahiouche, Salima (2021)"}}
            html='<script type="application/ld+json">'+json.dumps(page)+'</script>'
            def run(name,*extra):
                status,output=self.run_cli([name,"--root",str(root),"--psl",str(parser.psl_path),*map(str,extra)],cfg)
                self.assertEqual(status,0,output); self.assertNotIn(str(home),output); self.assertNotIn("https://",output)
                return output
            run("bind-v2","--v2-root",old)
            with patch("sentinel.url_v3.transport.open_response",side_effect=[Response(json.dumps([entry]).encode()),Response(html.encode()),Response(body)]):
                run("acquire-mendeley")
            run("audit"); frozen=json.loads(run("freeze")); self.assertTrue(frozen["training_ready"])
            self.assertEqual(read_json(root/"config.json"),cfg); self.assertTrue((root/"sources/suffix.dat").is_file())
            run("pilot"); self.assertTrue((root/"runs/pilot.json").is_file())
            artifact=home/"local candidate"; run("train","--artifact",artifact,"--version","synthetic")
            public=home/"aggregate result"; run("evaluate","--artifact",artifact,"--output",public)
            self.assertTrue((public/"evaluation.json").is_file())
            completed=read_json(public/"research-status.json")
            self.assertIs(completed["models_fitted"],True); self.assertEqual(completed["status"],"complete")
            self.assertEqual(set(completed["metrics"]["tracks"]),{"primary","supplemental"})
            status,output=self.run_cli(["predict","--artifact",str(artifact),"--url","https://m0-0.example/article?q=0"])
            self.assertEqual(status,0,output); self.assertIn('"state": "complete"',output)
            status,output=self.run_cli(["predict","--artifact",str(home/"missing"),"--url","https://example.org/"])
            self.assertEqual(status,2); self.assertIn("artifact_unavailable",output)
            self.assertEqual(original,hashes(old)); self.assertFalse((root/"cases.db").exists())
    def test_failed_gates_publish_null_metrics_and_never_fit(self):
        from sentinel.url_v3.evaluation import publish_research_status
        with tempfile.TemporaryDirectory(prefix="sentinel gate ") as td:
            home=Path(td); original,cfg,parser=synthetic_study(home/"original",scenario="no_queries")
            study=home/"study"; shutil.copytree(original.study_root,study,ignore=shutil.ignore_patterns("v2"))
            splits=replace(original,root=study/"protocol",audit_root=study/"audited",study_root=study)
            shutil.copyfile(parser.psl_path,study/"sources/suffix.dat")
            self.assertFalse(splits.manifest["training_ready"])
            status=publish_research_status(splits,cfg,home/"freeze report",stage="freeze",status="unavailable",reason="v3_training_support_incomplete")
            self.assertIsNone(status["metrics"]); self.assertIs(status["models_fitted"],False)
            self.assertEqual(status["support"]["tracks"],splits.manifest["tracks"])
            with self.assertRaises(DatasetError):
                publish_research_status(splits,cfg,home/"freeze report",stage="freeze",status="unavailable")
            with patch("sentinel.url_ml.training.fit_candidate",side_effect=AssertionError("gate must precede fitting")):
                for name in ("pilot","train"):
                    args=[name,"--root",str(splits.study_root),"--output",str(home/(name+" status"))]
                    if name=="train": args+=["--artifact",str(home/"model"),"--version","synthetic"]
                    code,output=self.run_cli(args,cfg); self.assertEqual(code,2,output)
                    report=read_json(home/(name+" status")/"research-status.json")
                    self.assertIsNone(report["metrics"]); self.assertIs(report["models_fitted"],False)
                    self.assertEqual(report["reason"],"v3_training_support_incomplete")
                    self.assertNotIn(str(home),output); self.assertNotIn("case_ids",output)
            self.assertTrue(list((splits.study_root/"failed-runs").glob("*.json")))
            self.assertFalse((home/"model").exists())
    def test_foreign_config_and_stage_failure_are_preserved_and_sanitized(self):
        with tempfile.TemporaryDirectory(prefix="sentinel failure ") as td:
            home=Path(td); wrong=home/"foreign.json"; write_json(wrong,{"schema":"url-ml-config-v2"})
            code,output=self.run_cli(["acquire-mendeley","--root",str(home/"study"),"--config",str(wrong)])
            self.assertEqual(code,2); self.assertIn("v3_config",output)
            self.assertTrue(list((home/"study/failed-runs").glob("*.json")))
            from sentinel.url_v3.contracts import default_config
            with patch("sentinel.url_v3.cli._execute",side_effect=RuntimeError("https://secret.example/?token=SECRET C:\\Users\\private\\data")):
                code,output=self.run_cli(["audit","--root",str(home/"failure")],default_config())
            self.assertEqual(code,2); self.assertNotIn("SECRET",output); self.assertNotIn("C:\\",output)
            self.assertTrue(list((home/"failure/failed-runs").glob("*.json")))
    def test_readonly_input_overlap_is_refused_before_any_write(self):
        with tempfile.TemporaryDirectory(prefix="sentinel overlap ") as td:
            home=Path(td); old,cfg,parser=synthetic_v2_root(home); before=hashes(old)
            for root in (old,old/"new study"):
                code,output=self.run_cli(["bind-v2","--root",str(root),"--v2-root",str(old),"--psl",str(parser.psl_path)],cfg)
                self.assertEqual(code,2); self.assertIn("v2_input_read_only",output)
            self.assertEqual(before,hashes(old)); self.assertFalse((old/"new study").exists())
    def test_unavailable_status_rejects_invented_metrics_or_private_data(self):
        from sentinel.url_v3.evaluation import publish_research_status
        from sentinel.url_v3.contracts import default_config
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(DatasetError):
                publish_research_status(None,default_config(),Path(td)/"bad",stage="freeze",status="unavailable",metrics={"accuracy":.9})
            report=publish_research_status(None,default_config(),Path(td)/"clean",stage="audit",status="failed",reason="source_unavailable")
            self.assertIsNone(report["metrics"]); self.assertIs(report["models_fitted"],False)
            self.assertFalse((Path(td)/"clean/evaluation.json").exists())

if __name__=="__main__": unittest.main()
