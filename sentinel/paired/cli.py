"""Offline, guarded stages for the paired message-link study."""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from sentinel import curation

from .admission import finalize_study_reviews, prepare_study_reviews
from .artifacts import export_study_artifact, inspect_study_artifact, load_study_artifact
from .contracts import PRODUCTION_CRITERIA, StudyCriteria
from .readiness import readiness_report

_HEX = re.compile(r"[a-f0-9]{64}\Z")


def _parser():
    from sentinel.url_ml.urls import UrlParser
    return UrlParser(Path(__file__).resolve().parents[2] / "resources" / "url-v2-suffix.dat")


def _eligible(root, criteria):
    report = readiness_report(root, criteria)
    if report["status"] != "eligible_for_freeze":
        raise ValueError("paired study unavailable: " + ",".join(report["reasons"]))
    return report


def _protocol(root):
    from .protocol import _checked_manifest
    manifest, digest = _checked_manifest(Path(root), _parser())
    return {**manifest, "manifest_sha256": digest}


def run_train(root: Path, *, criteria: StudyCriteria = PRODUCTION_CRITERIA) -> dict:
    from .evaluation import fit_calibrators, select_candidates
    from .models import fit_branch_candidates
    from .protocol import load_development

    root = Path(root)
    _eligible(root, criteria)
    parser = _parser()
    protocol = _protocol(root)
    if protocol.get("criteria") != vars(criteria):
        raise ValueError("frozen study criteria differ from this training stage")
    development = load_development(root, parser)
    output = root / "study-v1" / "artifact"
    if output.exists():
        raise FileExistsError("paired training artifact already exists")
    candidates = fit_branch_candidates(development["train"], parser, {})
    selections = select_candidates(candidates, development["validation"])
    calibrators = fit_calibrators(selections, development["calibration"])
    metadata = export_study_artifact(selections, calibrators, protocol, output)
    return {"status": "trained_research_only", "artifact_manifest_sha256": curation._sha256(output / "manifest.json"),
            "protocol_sha256": protocol["manifest_sha256"], "branches": metadata["branches"]}


def reserve_final_access(root: Path, protocol_sha256: str, artifact_sha256: str,
                         *, output_name: str = "evaluation.json") -> dict:
    root = Path(root)
    if not _HEX.fullmatch(protocol_sha256) or not _HEX.fullmatch(artifact_sha256):
        raise ValueError("final access needs valid protocol and artifact SHA-256")
    if output_name not in {"evaluation.json", "final-evaluation"}:
        raise ValueError("unsupported final output identity")
    study = root / "study-v1"
    output = study / output_name
    if output.exists():
        raise FileExistsError("final evaluation already exists; sealed test is single use")
    receipt = study / "final_access.json"
    value = {"schema_version": 1, "state": "reserved", "protocol_sha256": protocol_sha256,
             "artifact_sha256": artifact_sha256, "output_name": output_name,
             "output_path_sha256": hashlib.sha256(str(output.resolve()).encode()).hexdigest()}
    if receipt.exists():
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        if saved != value:
            raise ValueError("final evaluation was reserved for a different protocol, artifact or output")
        return saved
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return value


def run_evaluate(root: Path, *, criteria: StudyCriteria = PRODUCTION_CRITERIA,
                 replicates: int = 1000) -> dict:
    from .evaluation import evaluate_branches
    from .protocol import connected_groups, load_development, load_final_test

    root = Path(root)
    _eligible(root, criteria)
    parser = _parser()
    protocol = _protocol(root)
    if protocol.get("criteria") != vars(criteria):
        raise ValueError("frozen study criteria differ from this evaluation stage")
    development = load_development(root, parser)
    artifact_path = root / "study-v1" / "artifact"
    metadata = inspect_study_artifact(artifact_path)
    if metadata["protocol_sha256"] != protocol["manifest_sha256"]:
        raise ValueError("artifact does not match frozen study")
    bundle = load_study_artifact(artifact_path)
    artifact_hash = curation._sha256(artifact_path / "manifest.json")
    receipt = reserve_final_access(root, protocol["manifest_sha256"], artifact_hash,
                                   output_name="final-evaluation")
    # The receipt is durable before this sealed loader may return row data.
    test = load_final_test(root, parser, receipt)
    groups = connected_groups(test, parser)
    train_domains = {parser.normalize(row["url"]).domain_group for row in development["train"]}
    study = root / "study-v1"
    with tempfile.TemporaryDirectory(dir=study, prefix="final-evaluation-stage-") as temporary:
        stage = Path(temporary)
        report = evaluate_branches(bundle.selections, test, bundle.calibrators, groups,
                                   replicates=replicates, train_domains=train_domains,
                                   baseline_train=development["train"],
                                   private_error_path=stage / "private_error_cases.json")
        report.update({"protocol_sha256": protocol["manifest_sha256"],
                       "artifact_sha256": artifact_hash, "release_status": "research_only"})
        (stage / "aggregate.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(stage, study / "final-evaluation")
    return report


def run_predict(root: Path, message: str, url: str) -> dict:
    artifact = Path(root) / "study-v1" / "artifact"
    metadata = inspect_study_artifact(artifact)
    if metadata["release_status"] != "approved":
        return {"state": "unavailable", "reason": "research_only_artifact"}
    from .service import PairedService
    return PairedService(artifact).assess(message, url)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline Sentinel paired-study stages")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "finalize", "audit", "freeze", "train", "evaluate", "predict"):
        sub = commands.add_parser(name)
        sub.add_argument("--root", type=Path, required=True)
        if name == "predict":
            sub.add_argument("--message", required=True)
            sub.add_argument("--url", required=True)
    args = parser.parse_args(argv)
    root = args.root
    try:
        if args.command == "prepare":
            result = prepare_study_reviews(root)
        elif args.command == "finalize":
            result = finalize_study_reviews(root)
        elif args.command == "audit":
            result = readiness_report(root)
        elif args.command == "freeze":
            from .protocol import freeze_study
            _eligible(root, PRODUCTION_CRITERIA)
            result = freeze_study(root, _parser())
        elif args.command == "train":
            result = run_train(root)
        elif args.command == "evaluate":
            result = run_evaluate(root)
        else:
            result = run_predict(root, args.message, args.url)
    except (ValueError, FileExistsError, FileNotFoundError, ImportError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
