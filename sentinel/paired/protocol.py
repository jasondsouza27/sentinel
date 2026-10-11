"""One-seed, group-isolated four-way lock for paired research."""

import hashlib
import json
import math
import os
import random
import re
import tempfile
from collections import Counter
from pathlib import Path

from sentinel import curation, research
from sentinel.datasets import LINK

from .admission import verify_finalized_study
from .contracts import PRODUCTION_CRITERIA, StudyCriteria
from .readiness import readiness_report

SUFFIX_SHA256 = "e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66"
PARTITIONS = ("train", "validation", "calibration", "test")
FRACTIONS = {"train": .70, "validation": .10, "calibration": .10, "test": .10}


def _parser_checked(parser):
    if parser.psl_sha256 != SUFFIX_SHA256 or curation._sha256(parser.psl_path) != SUFFIX_SHA256:
        raise ValueError("offline suffix snapshot hash changed")


def _message_urls(message):
    for match in LINK.finditer(message):
        raw = match.group().rstrip(".,;:!?)]}'\"")
        yield "http://" + raw if raw.lower().startswith("www.") else raw


def connected_groups(rows: list[dict], parser) -> dict[str, str]:
    _parser_checked(parser)
    ids = [row["case_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case_id in paired rows")
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        parent[find(a)] = find(b)

    seen = {}
    for i, row in enumerate(rows):
        if not row.get("message", "").strip() or not row.get("url", "").strip():
            raise ValueError("missing paired modality")
        links = [row["url"], *_message_urls(row["message"])]
        domains = {parser.normalize(link).domain_group for link in links}
        wording = " ".join(re.findall(r"[a-z0-9]+", LINK.sub(" URL ", row["message"]).lower()))
        keys = {"domain:" + domain for domain in domains}
        keys.add("wording:" + wording)
        campaign = row.get("campaign_group", "").strip().lower()
        if campaign:
            keys.add("campaign:" + campaign)
        for key in keys:
            if key in seen:
                union(i, seen[key])
            else:
                seen[key] = i
    members = {}
    for i, case_id in enumerate(ids):
        members.setdefault(find(i), []).append(case_id)
    component_ids = {root: "g-" + hashlib.sha256("\0".join(sorted(group)).encode()).hexdigest()[:16]
                     for root, group in members.items()}
    return {case_id: component_ids[find(i)] for i, case_id in enumerate(ids)}


def _check_partition(partitions, parser, criteria):
    all_rows = [row for part in PARTITIONS for row in partitions[part]]
    groups = connected_groups(all_rows, parser)
    seen = set()
    for part in PARTITIONS:
        rows = partitions[part]
        if {row["label"] for row in rows} != {"0", "1"}:
            raise ValueError(f"{part} needs both classes")
        part_groups = {groups[row["case_id"]] for row in rows}
        if seen & part_groups:
            raise ValueError("connected component crossed partitions")
        seen |= part_groups
    test = partitions["test"]
    for label in ("0", "1"):
        if sum(row["label"] == label for row in test) < criteria.min_test_per_class:
            raise ValueError(f"test needs {criteria.min_test_per_class} cases of class {label}")
    domains = {parser.normalize(row["url"]).domain_group for row in test}
    if len(domains) < criteria.min_test_domains:
        raise ValueError("test has insufficient distinct domain groups")


def allocate_partitions(rows: list[dict], parser, *, seed: int = 42,
                        criteria: StudyCriteria = PRODUCTION_CRITERIA) -> dict[str, list[dict]]:
    _parser_checked(parser)
    if seed != 42:
        raise ValueError("primary protocol fixes seed 42")
    if len(rows) < criteria.min_total:
        raise ValueError("insufficient total reviewed pairs")
    labels = Counter(row.get("label") for row in rows)
    if set(labels) != {"0", "1"} or any(labels[label] < criteria.min_per_class for label in ("0", "1")):
        raise ValueError("insufficient reviewed cases per class")
    groups = connected_groups(rows, parser)
    components = {}
    for row in rows:
        components.setdefault(groups[row["case_id"]], []).append(row)
    if len(components) < 4 or max(map(len, components.values())) > math.ceil(.70 * len(rows)):
        raise ValueError("one giant component or too few independent components")
    rng = random.Random(seed)
    items = list(components.items())
    rng.shuffle(items)
    items.sort(key=lambda item: -len(item[1]))
    remaining = dict(items)
    assigned = {name: [] for name in PARTITIONS}

    def take(name, label, needed):
        while sum(row["label"] == label for row in assigned[name]) < needed:
            possible = [(key, group) for key, group in remaining.items()
                        if any(row["label"] == label for row in group)]
            if not possible:
                raise ValueError("cannot place both classes in all partitions without component leakage")
            # Stable order after the single seed shuffle; prefer compact groups.
            key, group = min(possible, key=lambda item: len(item[1]))
            assigned[name].extend(group)
            del remaining[key]

    for name in ("test", "validation", "calibration", "train"):
        for label in ("0", "1"):
            take(name, label, criteria.min_test_per_class if name == "test" else 1)
    for key, group in remaining.items():
        destination = min(PARTITIONS, key=lambda name: (
            len(assigned[name]) / max(1, FRACTIONS[name] * len(rows)), PARTITIONS.index(name)))
        assigned[destination].extend(group)
    for name in PARTITIONS:
        assigned[name].sort(key=lambda row: row["case_id"])
    _check_partition(assigned, parser, criteria)
    return assigned


def freeze_study(root: Path, parser, *, criteria: StudyCriteria = PRODUCTION_CRITERIA) -> dict:
    root = Path(root)
    target = root / "study-v1"
    if target.exists():
        raise FileExistsError("study-v1 already exists; refusing to replace the sealed lock")
    report = readiness_report(root, criteria)
    if report["status"] != "eligible_for_freeze":
        raise ValueError("paired study unavailable: " + ",".join(report["reasons"]))
    verify_finalized_study(root)
    rows = research.load_rows(root / "final_pairs.csv")
    assigned = allocate_partitions(rows, parser, criteria=criteria)
    manifest = {
        "schema_version": 1, "seed": 42, "fractions": FRACTIONS,
        "source_sha256": curation._sha256(root / "final_pairs.csv"),
        "study_final_manifest_sha256": curation._sha256(root / "study_final_manifest.json"),
        "suffix_sha256": SUFFIX_SHA256,
        "criteria": vars(criteria),
        "partitions": {},
    }
    with tempfile.TemporaryDirectory(dir=root, prefix="study-v1-stage-") as temporary:
        stage = Path(temporary)
        for name in PARTITIONS:
            path = stage / f"{name}.csv"
            curation._write_csv(path, curation.FINAL_FIELDS, assigned[name])
            manifest["partitions"][name] = {
                "sha256": curation._sha256(path),
                "cases": len(assigned[name]),
                "classes": dict(Counter(row["label"] for row in assigned[name])),
            }
        manifest_path = stage / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        digest = curation._sha256(manifest_path)
        (stage / "manifest.sha256").write_text(digest + "\n", encoding="ascii")
        os.replace(stage, target)
    return {**manifest, "manifest_sha256": digest}


def _checked_manifest(root, parser):
    _parser_checked(parser)
    verify_finalized_study(root)
    directory = root / "study-v1"
    digest = curation._sha256(directory / "manifest.json")
    if (directory / "manifest.sha256").read_text(encoding="ascii").strip() != digest:
        raise ValueError("study-v1 manifest.json changed")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("seed") != 42 or manifest.get("suffix_sha256") != SUFFIX_SHA256:
        raise ValueError("unsupported or changed study-v1 manifest")
    if manifest.get("source_sha256") != curation._sha256(root / "final_pairs.csv"):
        raise ValueError("final_pairs.csv changed after freeze")
    if manifest.get("study_final_manifest_sha256") != curation._sha256(root / "study_final_manifest.json"):
        raise ValueError("study_final_manifest.json changed after freeze")
    for name in PARTITIONS:
        if curation._sha256(directory / f"{name}.csv") != manifest["partitions"][name]["sha256"]:
            raise ValueError(f"{name}.csv changed after freeze")
    return manifest, digest


def load_development(root: Path, parser) -> dict[str, list[dict]]:
    root = Path(root)
    _checked_manifest(root, parser)
    return {name: research.load_rows(root / "study-v1" / f"{name}.csv")
            for name in PARTITIONS if name != "test"}


def load_final_test(root: Path, parser, receipt: dict) -> list[dict]:
    root = Path(root)
    _, digest = _checked_manifest(root, parser)
    if receipt.get("state") != "reserved" or receipt.get("protocol_sha256") != digest:
        raise ValueError("final-test access requires a matching reservation receipt")
    return research.load_rows(root / "study-v1" / "test.csv")
