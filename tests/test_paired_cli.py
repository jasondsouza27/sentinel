import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paired_fixtures import complete_reviews, intake_case, write_intake
from sentinel.curation import init_workspace
from sentinel.paired.cli import reserve_final_access, run_train
from sentinel.paired.contracts import StudyCriteria
from sentinel.paired.protocol import freeze_study
from sentinel.url_ml.urls import UrlParser


class PairedCliTests(unittest.TestCase):
    def test_empty_audit_and_production_commands_remain_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_workspace(root)
            for command in ("audit", "freeze", "train", "evaluate"):
                result = subprocess.run([sys.executable, "-m", "sentinel.paired.cli", command,
                                         "--root", str(root)], capture_output=True, text=True)
                if command == "audit":
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(json.loads(result.stdout)["status"], "unavailable")
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((root / "study-v1").exists())

    def test_final_receipt_is_single_use_but_same_interrupted_attempt_resumes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "study-v1").mkdir()
            first = reserve_final_access(root, "a" * 64, "b" * 64, "c" * 64)
            self.assertEqual(first["state"], "reserved")
            self.assertEqual(first["evaluation_sha256"], "c" * 64)
            self.assertEqual(first, reserve_final_access(root, "a" * 64, "b" * 64, "c" * 64))
            with self.assertRaises(ValueError):
                reserve_final_access(root, "a" * 64, "d" * 64, "c" * 64)
            with self.assertRaisesRegex(ValueError, "different"):
                reserve_final_access(root, "a" * 64, "b" * 64, "d" * 64)
            (root / "study-v1" / "evaluation.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                reserve_final_access(root, "a" * 64, "b" * 64, "c" * 64)

    def test_training_rejects_changed_private_split_before_any_fit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cases = [intake_case(i, source="shared") for i in range(40)]
            for i, case in enumerate(cases):
                case["message"] = f"Unique synthetic wording {i} {case['url']}"
            write_intake(root, cases)
            complete_reviews(root, [i % 2 for i in range(40)])
            criteria = StudyCriteria(20, 10, 2, 3)
            parser = UrlParser(Path(__file__).resolve().parents[1] / "resources" / "url-v2-suffix.dat")
            freeze_study(root, parser, criteria=criteria)
            split = root / "study-v1" / "validation.csv"
            split.write_bytes(split.read_bytes() + b"changed")
            with patch("sentinel.paired.models.fit_branch_candidates") as fit:
                with self.assertRaises(ValueError):
                    run_train(root, criteria=criteria)
                fit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
