"""Template-grouped, label-stratified train / calibration / test splits.

Every row of one template group lands in the same split, so a resent spam
template cannot appear in both training and test. Groups are assigned per label
(a group's label is its majority label) in a seeded order to keep class shares
close to the target fractions.
"""

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

FRACTIONS = {"train": 0.70, "calibration": 0.15, "test": 0.15}


def make_splits(records, seed=20261105):
    groups = defaultdict(list)
    for record in records:
        groups[record["group"]].append(record)
    by_label = defaultdict(list)
    for key, rows in groups.items():
        label = Counter(r["label"] for r in rows).most_common(1)[0][0]
        by_label[label].append(key)
    rng = random.Random(seed)
    assignment = {}
    for label in sorted(by_label):
        keys = sorted(by_label[label])
        rng.shuffle(keys)
        total = sum(len(groups[k]) for k in keys)
        filled = Counter()
        for key in keys:
            # Put each group where the split is furthest below its target row count.
            name = min(FRACTIONS, key=lambda n: filled[n] / (FRACTIONS[n] * total))
            assignment[key] = name
            filled[name] += len(groups[key])
    splits = {name: [] for name in FRACTIONS}
    for record in records:
        splits[assignment[record["group"]]].append(record["id"])
    for ids in splits.values():
        ids.sort()
    return splits


def describe(records, splits):
    label_of = {r["id"]: r["label"] for r in records}
    group_of = {r["id"]: r["group"] for r in records}
    seen = {}
    for name, ids in splits.items():
        for i in ids:
            if seen.setdefault(group_of[i], name) != name:
                raise AssertionError("A template group appears in two splits")
    return {name: {"rows": len(ids), "labels": dict(Counter(label_of[i] for i in ids))}
            for name, ids in splits.items()}


def write(records, out_path, seed=20261105):
    splits = make_splits(records, seed)
    body = {"seed": seed, "fractions": FRACTIONS, "summary": describe(records, splits), "ids": splits}
    text = json.dumps(body, indent=1, sort_keys=True)
    Path(out_path).write_text(text + "\n", encoding="utf-8")
    body["sha256"] = hashlib.sha256((text + "\n").encode()).hexdigest()
    return body


def write_v2(records, v1_splits_path, out_path, seed=20261106):
    """Keep every v1 row in its v1 split (same test set for comparison); split the
    new rows by template group. A new template group that also occurs in v1 joins
    that group's v1 split so no template crosses splits."""
    v1_ids = json.loads(Path(v1_splits_path).read_text())["ids"]
    where = {i: name for name, ids in v1_ids.items() for i in ids}
    group_split = {r["group"]: where[r["id"]] for r in records if r["id"] in where}
    new = [r for r in records if r["id"] not in where and r["group"] not in group_split]
    assigned = make_splits(new, seed) if new else {name: [] for name in FRACTIONS}
    splits = {name: list(v1_ids[name]) + assigned[name] for name in FRACTIONS}
    for r in records:
        if r["id"] not in where and r["group"] in group_split:
            splits[group_split[r["group"]]].append(r["id"])
    for ids in splits.values():
        ids.sort()
    body = {"seed": seed, "fractions": FRACTIONS, "summary": describe(records, splits), "ids": splits,
            "note": "v1 rows keep their v1 splits; new rows split by template group."}
    text = json.dumps(body, indent=1, sort_keys=True)
    Path(out_path).write_text(text + "\n", encoding="utf-8")
    body["sha256"] = hashlib.sha256((text + "\n").encode()).hexdigest()
    return body
