"""Hash-checked, local-only paired-study model bundles."""

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
_HEX = re.compile(r"[a-f0-9]{64}\Z")


@dataclass
class StudyArtifact:
    metadata: dict
    selections: dict
    calibrators: dict
    protocol: dict


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _environment():
    import joblib
    import numpy
    import sklearn
    return {"python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "numpy": numpy.__version__, "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__}


def export_study_artifact(selections: dict, calibrators: dict, protocol: dict, output: Path) -> dict:
    import joblib

    output = Path(output)
    if output.exists():
        raise FileExistsError("paired artifact already exists")
    if set(selections) != {"message", "url", "combined"} or set(calibrators) != set(selections):
        raise ValueError("artifact needs the three paired branches and calibrators")
    protocol_hash = protocol.get("manifest_sha256", "")
    if not _HEX.fullmatch(protocol_hash):
        raise ValueError("protocol manifest SHA-256 is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="paired-artifact-stage-", dir=output.parent))
    try:
        metadata = {
            "schema_version": SCHEMA_VERSION, "release_status": "research_only",
            "protocol_sha256": protocol_hash, "environment": _environment(),
            "branches": {name: {"config_id": selection.candidate.config_id,
                                "raw_threshold": selection.raw_threshold,
                                "calibration_status": calibrators[name].status,
                                "peak_memory_bytes": selection.candidate.fit_record.get("peak_bytes")}
                         for name, selection in sorted(selections.items())},
        }
        _json(stage / "metadata.json", metadata)
        joblib.dump({"selections": selections, "calibrators": calibrators, "protocol": protocol},
                    stage / "model.joblib", compress=3)
        (stage / "model_card.md").write_text(
            "# Sentinel paired-study model card\n\n"
            "Research-only artifact. No learned phishing warning may be served until an independent "
            "release review creates a separately approved artifact.\n\n"
            f"Protocol manifest SHA-256: `{protocol_hash}`.\n\n"
            "The paired cohort, source balance, held-out errors, calibration and false positives "
            "must be reviewed before deployment. An unavailable real-data gate is not a model result.\n",
            encoding="utf-8",
        )
        names = ("metadata.json", "model.joblib", "model_card.md")
        manifest = {"schema_version": SCHEMA_VERSION,
                    "members": {name: _sha(stage / name) for name in names}}
        _json(stage / "manifest.json", manifest)
        (stage / "manifest.sha256").write_text(_sha(stage / "manifest.json") + "\n", encoding="ascii")
        os.replace(stage, output)
    finally:
        if stage.exists():
            if stage.resolve().parent != output.parent.resolve():
                raise ValueError("artifact stage escaped its parent directory")
            shutil.rmtree(stage)
    return metadata


def inspect_study_artifact(path: Path) -> dict:
    """Validate every byte and version before a caller may deserialize joblib."""
    path = Path(path)
    manifest_path = path / "manifest.json"
    if _sha(manifest_path) != (path / "manifest.sha256").read_text(encoding="ascii").strip():
        raise ValueError("manifest.json hash changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION or set(manifest.get("members", {})) != {
            "metadata.json", "model.joblib", "model_card.md"}:
        raise ValueError("unsupported or incomplete paired artifact manifest")
    for name, expected in manifest["members"].items():
        if not _HEX.fullmatch(expected) or _sha(path / name) != expected:
            raise ValueError(f"{name} hash changed")
    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported paired artifact metadata")
    if metadata.get("environment") != _environment():
        raise ValueError("artifact environment is unsupported or foreign")
    if metadata.get("release_status") != "research_only":
        raise ValueError("approved release format is not available in artifact schema 1")
    if not _HEX.fullmatch(metadata.get("protocol_sha256", "")):
        raise ValueError("artifact protocol hash missing")
    return metadata


def load_study_artifact(path: Path) -> StudyArtifact:
    import joblib

    metadata = inspect_study_artifact(path)
    # joblib is not a safe format for untrusted files; callers only provide a
    # locally trusted path, and byte/version checks precede this operation.
    bundle = joblib.load(Path(path) / "model.joblib")
    if not isinstance(bundle, dict) or set(bundle) != {"selections", "calibrators", "protocol"}:
        raise ValueError("unsupported paired artifact payload")
    if bundle["protocol"].get("manifest_sha256") != metadata["protocol_sha256"]:
        raise ValueError("artifact protocol binding changed")
    if set(bundle["selections"]) != {"message", "url", "combined"}:
        raise ValueError("artifact branch set changed")
    return StudyArtifact(metadata, bundle["selections"], bundle["calibrators"], bundle["protocol"])
