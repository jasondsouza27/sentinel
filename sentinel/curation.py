"""Local, two-reviewer collection workflow for paired-message research."""

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from .datasets import domain_group, extract_urls
from .research import _campaigns, _domains, _normalized, evaluate_fixed_split, load_rows, split_rows


INTAKE_FIELDS = (
    "case_id", "message", "url", "source_name", "source_ref", "campaign_group", "channel", "collected_on",
    "collection_basis", "pair_evidence", "pair_note", "redaction_reviewed",
)
REVIEW_FIELDS = ("case_id", "message", "url", "reviewer_id", "review_label", "review_reason")
ADJUDICATION_FIELDS = ("case_id", "final_label", "reason")
FINAL_FIELDS = (
    "case_id", "message", "url", "label", "domain_group", "campaign_group", "source_name", "source_ref", "channel",
    "collected_on", "collection_basis", "pair_evidence", "pair_note",
    "reviewer_a_id", "reviewer_b_id", "reviewer_a_reason", "reviewer_b_reason",
    "resolution", "adjudication_reason",
)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not set(required).issubset(reader.fieldnames or []):
            raise ValueError(f"{Path(path).name} needs columns: {', '.join(required)}")
        return list(reader)


def _write_csv(path, fields, rows):
    with Path(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _check_new(paths):
    existing = [path.name for path in paths if path.exists()]
    if existing:
        raise FileExistsError("Refusing to overwrite " + ", ".join(existing))


def _same_link(left, right):
    a, b = urlsplit(left), urlsplit(right)
    return (
        a.hostname and a.hostname.lower() == (b.hostname or "").lower()
        and a.scheme.lower() == b.scheme.lower()
        and a.port == b.port
        and a.path == b.path
        and a.query == b.query and a.fragment == b.fragment
    )


def _intake(root):
    rows = _read_csv(root / "intake.csv", INTAKE_FIELDS)
    if not rows:
        raise ValueError("intake.csv is empty; add permissioned message-link cases first")
    seen_ids = set()
    seen_pairs = set()
    for row in rows:
        case_id = row["case_id"].strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", case_id):
            raise ValueError("Use an opaque case_id with letters, digits, dots, dashes, or underscores")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate case_id: {case_id}")
        seen_ids.add(case_id)
        message = row["message"].strip()
        url = row["url"].strip()
        if not message or len(message) > 8000:
            raise ValueError(f"{case_id}: message must contain 1–8000 characters")
        try:
            parts = urlsplit(url)
            _ = parts.port  # Reject malformed ports even for same_post pairs.
            valid_url = parts.scheme in ("http", "https") and parts.hostname and "." in parts.hostname
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError(f"{case_id}: provide a complete HTTP(S) URL")
        if not row["source_name"].strip() or not row["source_ref"].strip():
            raise ValueError(f"{case_id}: source_name and source_ref are required")
        campaign = row["campaign_group"].strip()
        if campaign and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", campaign):
            raise ValueError(f"{case_id}: campaign_group must be an opaque ID up to 80 characters")
        if row["channel"].strip() not in ("social_post", "social_dm", "sms", "email"):
            raise ValueError(f"{case_id}: channel must be social_post, social_dm, sms, or email")
        try:
            collected = date.fromisoformat(row["collected_on"].strip())
        except ValueError as error:
            raise ValueError(f"{case_id}: collected_on must be YYYY-MM-DD") from error
        if collected.isoformat() != row["collected_on"].strip():
            raise ValueError(f"{case_id}: collected_on must be YYYY-MM-DD")
        if row["collection_basis"].strip() not in ("licensed_public", "consented"):
            raise ValueError(f"{case_id}: collection_basis must be licensed_public or consented")
        evidence = row["pair_evidence"].strip()
        if evidence == "in_message":
            try:
                matched = any(_same_link(url, found) for found in extract_urls(message))
            except ValueError:
                matched = False
            if not matched:
                raise ValueError(f"{case_id}: URL is not present in the message")
        elif evidence == "same_post":
            if not row["pair_note"].strip():
                raise ValueError(f"{case_id}: same_post needs a pair_note explaining the link")
        else:
            raise ValueError(f"{case_id}: pair_evidence must be in_message or same_post")
        if row["redaction_reviewed"].strip().lower() != "yes":
            raise ValueError(f"{case_id}: review redaction, then set redaction_reviewed to yes")
        pair_key = (_normalized(message), url.lower())
        if pair_key in seen_pairs:
            raise ValueError(f"{case_id}: duplicate message–URL pair")
        seen_pairs.add(pair_key)
    return rows


def init_workspace(directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "intake.csv"
    _check_new([path])
    _write_csv(path, INTAKE_FIELDS, [])
    return {"intake": str(path), "cases": 0}


def prepare_reviews(directory):
    root = Path(directory)
    rows = _intake(root)
    files = [root / "reviewer_a.csv", root / "reviewer_b.csv", root / "adjudication.csv", root / "review_manifest.json"]
    _check_new(files)
    reviewer_rows = [
        {"case_id": row["case_id"], "message": row["message"], "url": row["url"],
         "reviewer_id": "", "review_label": "", "review_reason": ""}
        for row in rows
    ]
    _write_csv(files[0], REVIEW_FIELDS, reviewer_rows)
    _write_csv(files[1], REVIEW_FIELDS, reviewer_rows)
    _write_csv(files[2], ADJUDICATION_FIELDS, [])
    manifest = {"intake_sha256": _sha256(root / "intake.csv"), "cases": len(rows)}
    files[3].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _reviews(path, intake):
    rows = _read_csv(path, REVIEW_FIELDS)
    if len(rows) != len(intake) or len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError(f"{path.name}: cases do not match intake.csv")
    mapped = {row["case_id"]: row for row in rows}
    if set(mapped) != set(intake):
        raise ValueError(f"{path.name}: cases do not match intake.csv")
    reviewer_ids = set()
    for case_id, original in intake.items():
        row = mapped[case_id]
        if row["message"] != original["message"] or row["url"] != original["url"]:
            raise ValueError(f"{path.name}: {case_id} message or URL was changed")
        if row["review_label"].strip() not in ("0", "1", "?"):
            raise ValueError(f"{path.name}: {case_id} needs label 0, 1, or ?")
        if not row["review_reason"].strip() or not row["reviewer_id"].strip():
            raise ValueError(f"{path.name}: {case_id} needs reviewer_id and review_reason")
        reviewer_ids.add(row["reviewer_id"].strip())
    if len(reviewer_ids) != 1:
        raise ValueError(f"{path.name}: use one reviewer_id for the entire sheet")
    return mapped, reviewer_ids.pop()


def finalize_reviews(directory):
    root = Path(directory)
    output = root / "final_pairs.csv"
    audit_path = root / "final_audit.json"
    _check_new([output, audit_path])
    manifest = json.loads((root / "review_manifest.json").read_text(encoding="utf-8"))
    if manifest["intake_sha256"] != _sha256(root / "intake.csv"):
        raise ValueError("intake.csv changed after review sheets were prepared")
    rows = _intake(root)
    intake = {row["case_id"]: row for row in rows}
    a, reviewer_a = _reviews(root / "reviewer_a.csv", intake)
    b, reviewer_b = _reviews(root / "reviewer_b.csv", intake)
    if reviewer_a == reviewer_b:
        raise ValueError("Reviewer A and Reviewer B must be different people")
    adjudication_rows = _read_csv(root / "adjudication.csv", ADJUDICATION_FIELDS)
    if len({row["case_id"] for row in adjudication_rows}) != len(adjudication_rows):
        raise ValueError("adjudication.csv has duplicate case_id values")
    adjudications = {row["case_id"]: row for row in adjudication_rows}
    final = []
    agreement = adjudicated = excluded = 0
    unresolved = []
    for row in rows:
        case_id = row["case_id"]
        label_a = a[case_id]["review_label"].strip()
        label_b = b[case_id]["review_label"].strip()
        if label_a == label_b and label_a in ("0", "1"):
            if case_id in adjudications:
                raise ValueError(f"{case_id}: adjudication is only for disagreement or uncertainty")
            label, resolution, adjudication_reason = label_a, "agreement", ""
            agreement += 1
        else:
            decision = adjudications.get(case_id)
            if not decision or decision["final_label"].strip() not in ("0", "1", "exclude") or not decision["reason"].strip():
                unresolved.append(case_id)
                continue
            label, resolution, adjudication_reason = decision["final_label"].strip(), "adjudicated", decision["reason"].strip()
            adjudicated += 1
        if label == "exclude":
            excluded += 1
            continue
        final.append({
            "case_id": case_id, "message": row["message"], "url": row["url"],
            "label": label, "domain_group": domain_group(row["url"]),
            "campaign_group": row["campaign_group"].strip(),
            "source_name": row["source_name"], "source_ref": row["source_ref"],
            "channel": row["channel"],
            "collected_on": row["collected_on"], "collection_basis": row["collection_basis"],
            "pair_evidence": row["pair_evidence"], "pair_note": row["pair_note"],
            "reviewer_a_id": reviewer_a, "reviewer_b_id": reviewer_b,
            "reviewer_a_reason": a[case_id]["review_reason"],
            "reviewer_b_reason": b[case_id]["review_reason"],
            "resolution": resolution, "adjudication_reason": adjudication_reason,
        })
    unknown_adjudications = set(adjudications) - set(intake)
    if unknown_adjudications:
        raise ValueError("Unknown adjudication case_id: " + ", ".join(sorted(unknown_adjudications)))
    if unresolved:
        raise ValueError("Adjudication needed for: " + ", ".join(unresolved))
    _write_csv(output, FINAL_FIELDS, final)
    audit = {
        "intake_sha256": _sha256(root / "intake.csv"),
        "reviewer_a_sha256": _sha256(root / "reviewer_a.csv"),
        "reviewer_b_sha256": _sha256(root / "reviewer_b.csv"),
        "adjudication_sha256": _sha256(root / "adjudication.csv"),
        "final_pairs_sha256": _sha256(output),
        "reviewed_cases": len(rows), "agreement_cases": agreement,
        "adjudicated_cases": adjudicated, "excluded_cases": excluded,
        "final_cases": len(final),
        "class_counts": dict(Counter(item["label"] for item in final)),
        "channel_counts": dict(Counter(item["channel"] for item in final)),
        "distinct_sources": len({item["source_name"] for item in final}),
        "distinct_source_refs": len({item["source_ref"] for item in final}),
    }
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit


def _verify_finalized(root):
    audit = json.loads((root / "final_audit.json").read_text(encoding="utf-8"))
    for name in ("intake", "reviewer_a", "reviewer_b", "adjudication", "final_pairs"):
        path = root / f"{name}.csv"
        if audit.get(f"{name}_sha256") != _sha256(path):
            raise ValueError(f"{path.name} changed after finalization")
    return audit


def freeze_split(directory, seed=42):
    root = Path(directory)
    source = root / "final_pairs.csv"
    _verify_finalized(root)
    rows = load_rows(source)
    train, test = split_rows(rows, seed)
    locked = root / "locked"
    locked.mkdir(parents=True, exist_ok=True)
    train_path, test_path, manifest_path = (locked / "train.csv", locked / "test.csv", locked / "manifest.json")
    _check_new([train_path, test_path, manifest_path])
    fields = tuple(rows[0].keys())
    _write_csv(train_path, fields, train)
    _write_csv(test_path, fields, test)
    train_domains = set().union(*(_domains(row) for row in train))
    test_domains = set().union(*(_domains(row) for row in test))
    train_campaigns = set().union(*(_campaigns(row) for row in train))
    test_campaigns = set().union(*(_campaigns(row) for row in test))
    train_messages = {_normalized(row["message"]) for row in train}
    test_messages = {_normalized(row["message"]) for row in test}
    manifest = {
        "seed": seed,
        "final_audit_sha256": _sha256(root / "final_audit.json"),
        "source_sha256": _sha256(source),
        "train_sha256": _sha256(train_path),
        "test_sha256": _sha256(test_path),
        "train_cases": len(train), "test_cases": len(test),
        "class_balance": {
            "train": dict(Counter(row["label"] for row in train)),
            "test": dict(Counter(row["label"] for row in test)),
        },
        "overlap": {
            "domains": len(train_domains & test_domains),
            "duplicate_messages": len(train_messages & test_messages),
            "campaigns": len(train_campaigns & test_campaigns),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def evaluate_locked(directory):
    """Score a frozen split only if its files still match the lock manifest."""
    root = Path(directory)
    locked = root / "locked"
    output = locked / "evaluation.json"
    _check_new([output])
    manifest = json.loads((locked / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("final_audit_sha256") != _sha256(root / "final_audit.json"):
        raise ValueError("final_audit.json changed after the split was locked")
    _verify_finalized(root)
    train_path, test_path = locked / "train.csv", locked / "test.csv"
    checks = (
        (root / "final_pairs.csv", manifest["source_sha256"]),
        (train_path, manifest["train_sha256"]),
        (test_path, manifest["test_sha256"]),
    )
    for path, expected in checks:
        if _sha256(path) != expected:
            raise ValueError(f"{path.name} changed after the split was locked")
    report = {
        "dataset_sha256": manifest["source_sha256"],
        "train_sha256": manifest["train_sha256"],
        "test_sha256": manifest["test_sha256"],
        **evaluate_fixed_split(load_rows(train_path), load_rows(test_path)),
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Build a reviewed, locked Sentinel research dataset")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "prepare", "finalize", "freeze", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("directory", help="Local curation directory")
        if name == "freeze":
            command.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    action = {
        "init": init_workspace,
        "prepare": prepare_reviews,
        "finalize": finalize_reviews,
        "freeze": freeze_split,
        "evaluate": evaluate_locked,
    }[args.command]
    try:
        result = action(args.directory, seed=args.seed) if args.command == "freeze" else action(args.directory)
    except (ValueError, FileExistsError, FileNotFoundError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
