import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sentinel.paired.artifacts import export_study_artifact, inspect_study_artifact, load_study_artifact
from sentinel.paired.evaluation import Selection
from sentinel.paired.models import BranchCandidate
from sentinel.url_ml.contracts import Calibration


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "paired-artifact"
        self.selections = {name: Selection(BranchCandidate(name, name + "-v1", {"model": name},
                                                            {"peak_bytes": 123}), .5, {"fpr": 0.0})
                           for name in ("message", "url", "combined")}
        self.calibrators = {name: Calibration("unavailable", None, None, None, {"reason": "fixture"})
                            for name in self.selections}
        self.protocol = {"manifest_sha256": "a" * 64, "partitions": {"train": {"sha256": "b" * 64}}}

    def _export(self):
        return export_study_artifact(self.selections, self.calibrators, self.protocol, self.output)

    def test_research_only_artifact_round_trip_and_no_overwrite(self):
        report = self._export()
        self.assertEqual(report["release_status"], "research_only")
        self.assertEqual(inspect_study_artifact(self.output)["release_status"], "research_only")
        loaded = load_study_artifact(self.output)
        self.assertEqual(loaded.selections["message"].candidate.config_id, "message-v1")
        with self.assertRaises(FileExistsError):
            self._export()

    def test_missing_or_tampered_member_rejected_before_deserialization(self):
        self._export()
        model = self.output / "model.joblib"
        model.write_bytes(model.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "model.joblib"):
            load_study_artifact(self.output)
        model.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            load_study_artifact(self.output)

    def test_foreign_dependency_metadata_rejected(self):
        self._export()
        metadata_path = self.output / "metadata.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["environment"]["joblib"] = "foreign-version"
        metadata_path.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
        manifest_path = self.output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["members"]["metadata.json"] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        (self.output / "manifest.sha256").write_text(hashlib.sha256(manifest_path.read_bytes()).hexdigest(), encoding="ascii")
        with self.assertRaisesRegex(ValueError, "environment"):
            load_study_artifact(self.output)


if __name__ == "__main__":
    unittest.main()
