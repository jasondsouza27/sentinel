import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from paired_fixtures import complete_reviews, intake_case, write_intake
from sentinel.curation import init_workspace
from sentinel.paired.cli import run_evaluate, run_train
from sentinel.paired.contracts import StudyCriteria
from sentinel.paired.protocol import freeze_study
from sentinel.url_ml.urls import UrlParser


class WorkflowTests(unittest.TestCase):
    def test_team_handoff_documents_every_gate_and_stage(self):
        guide = Path(__file__).resolve().parents[1] / "docs" / "paired-study-workflow.md"
        text = guide.read_text(encoding="utf-8")
        for stage in ("prepare", "finalize", "audit", "freeze", "train", "evaluate", "predict"):
            self.assertIn(f"sentinel.paired.cli {stage}", text)
        for item in ("evidence_ledger.csv", "phishing_request", "verified_legitimate_request",
                     "source_label_confounded", "unavailable", "research_only"):
            self.assertIn(item, text)

    def test_synthetic_software_path_and_production_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            empty = Path(temporary) / "empty"
            init_workspace(empty)
            audit = subprocess.run([sys.executable, "-m", "sentinel.paired.cli", "audit",
                                    "--root", str(empty)], capture_output=True, text=True)
            self.assertEqual(audit.returncode, 0)
            self.assertEqual(json.loads(audit.stdout)["status"], "unavailable")

            root = Path(temporary) / "synthetic"
            root.mkdir()
            cases = [intake_case(i, source="shared-source") for i in range(40)]
            for i, case in enumerate(cases):
                case["message"] = f"Unique software-only synthetic wording {i} {case['url']}"
            write_intake(root, cases)
            complete_reviews(root, [i % 2 for i in range(40)])
            criteria = StudyCriteria(min_total=20, min_per_class=10, min_test_per_class=2, min_test_domains=3)
            parser = UrlParser(Path(__file__).resolve().parents[1] / "resources" / "url-v2-suffix.dat")
            lock = freeze_study(root, parser, criteria=criteria)
            self.assertEqual(len(lock["manifest_sha256"]), 64)
            trained = run_train(root, criteria=criteria)
            self.assertEqual(trained["status"], "trained_research_only")
            report = run_evaluate(root, criteria=criteria, replicates=40)
            self.assertEqual(report["release_status"], "research_only")
            self.assertEqual(report["bootstrap"]["replicates"], 40)
            self.assertTrue((root / "study-v1" / "final_access.json").exists())
            self.assertTrue((root / "study-v1" / "final-evaluation" / "private_error_cases.json").exists())
            aggregate = (root / "study-v1" / "final-evaluation" / "aggregate.json").read_text()
            for secret in ("Unique software-only", "https://", "case-0", "shared-source", "vault-0"):
                self.assertNotIn(secret, aggregate)
            with self.assertRaises(FileExistsError):
                run_evaluate(root, criteria=criteria, replicates=40)
            production = subprocess.run([sys.executable, "-m", "sentinel.paired.cli", "freeze",
                                         "--root", str(root)], capture_output=True, text=True)
            self.assertNotEqual(production.returncode, 0)
            self.assertIn("unavailable", production.stderr)


if __name__ == "__main__":
    unittest.main()
