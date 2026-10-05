"""Reproducible paired message/URL baseline experiment (standard library only)."""

import argparse
import csv
import json
import math
import random
import re
import statistics
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from .datasets import LINK, domain_group, extract_urls


REQUIRED = {"case_id", "message", "url", "label", "domain_group"}


def load_rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError(f"CSV requires columns: {', '.join(sorted(REQUIRED))}")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV is empty")
    if len({row["case_id"] for row in rows}) != len(rows):
        raise ValueError("case_id values must be unique")
    for row in rows:
        if row["label"] not in ("0", "1"):
            raise ValueError("label must be 0 or 1")
        if not row["message"].strip() or not row["url"].strip():
            raise ValueError("Each research case needs a paired message and URL")
        if not row["domain_group"].strip():
            raise ValueError("Each case needs a domain_group")
    return rows


def features(message, url, mode):
    output = []
    if mode in ("message", "combined"):
        message_without_links = LINK.sub(" URL ", message)
        output.extend("m:" + token for token in re.findall(r"[a-z0-9]{2,}", message_without_links.lower()))
    if mode in ("url", "combined"):
        parts = urlsplit(url)
        host = parts.hostname or ""
        output.extend("u:" + token for token in re.findall(r"[a-z0-9]{2,}", host + " " + parts.path.lower()))
        if "@" in parts.netloc:
            output.append("u:at_sign")
        if host.startswith("xn--") or ".xn--" in host:
            output.append("u:punycode")
        output.append("u:length_" + ("long" if len(url) >= 100 else "ordinary"))
    return output


def _train(rows, mode):
    counts = {"0": Counter(), "1": Counter()}
    documents = Counter()
    for row in rows:
        label = row["label"]
        documents[label] += 1
        counts[label].update(features(row["message"], row["url"], mode))
    if not all(documents[label] for label in ("0", "1")):
        raise ValueError("Training data needs both label 0 and label 1")
    vocabulary = set(counts["0"]) | set(counts["1"])
    size = max(len(vocabulary), 1)
    model = {"mode": mode, "prior": {}, "weights": {}}
    for label in ("0", "1"):
        denominator = sum(counts[label].values()) + size
        model["prior"][label] = math.log(documents[label] / len(rows))
        model["weights"][label] = {
            token: math.log((counts[label][token] + 1) / denominator) for token in vocabulary
        }
    return model


def train_models(rows):
    return {mode: _train(rows, mode) for mode in ("message", "url", "combined")}


def predict(model, message, url, mode=None):
    mode = mode or model["mode"]
    tokens = Counter(features(message, url, mode))
    scores = {}
    for label in ("0", "1"):
        scores[label] = model["prior"][label] + sum(
            count * model["weights"][label][token]
            for token, count in tokens.items() if token in model["weights"][label]
        )
    return 1 if scores["1"] >= scores["0"] else 0


def _normalized(message):
    # Group by the wording visible to the message-only baseline, not by URL tokens.
    without_links = LINK.sub(" URL ", message)
    return " ".join(re.findall(r"[a-z0-9]+", without_links.lower()))


def _domains(row):
    domains = {row["domain_group"].strip().lower()}
    domains.update(domain_group(url) for url in extract_urls(row["message"]))
    return domains


def _campaigns(row):
    group = (row.get("campaign_group") or "").strip().lower()
    return {group} if group else set()


def split_rows(rows, seed=42, test_fraction=0.2):
    """Connect rows sharing a domain, campaign, or normalized wording."""
    parent = list(range(len(rows)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        parent[find(left)] = find(right)

    seen_domains = {}
    seen_campaigns = {}
    seen_messages = {}
    for index, row in enumerate(rows):
        normalized = _normalized(row["message"])
        for domain in sorted(_domains(row)):
            if domain in seen_domains:
                union(index, seen_domains[domain])
            seen_domains[domain] = index
        for campaign in _campaigns(row):
            if campaign in seen_campaigns:
                union(index, seen_campaigns[campaign])
            seen_campaigns[campaign] = index
        if normalized in seen_messages:
            union(index, seen_messages[normalized])
        seen_messages[normalized] = index
    groups = {}
    for index in range(len(rows)):
        groups.setdefault(find(index), []).append(index)
    if len(groups) < 5:
        raise ValueError("At least five independent domain/message groups are needed for evaluation")
    keys = list(groups)
    rng = random.Random(seed)
    target = max(2, round(len(rows) * test_fraction))
    prevalence = sum(row["label"] == "1" for row in rows) / len(rows)
    best = None
    for _ in range(256):
        rng.shuffle(keys)
        chosen = []
        selected = set()
        for key in keys:
            chosen.append(key)
            selected.update(groups[key])
            selected_labels = {rows[index]["label"] for index in selected}
            if len(selected) < target or selected_labels != {"0", "1"}:
                continue
            remaining_labels = {rows[index]["label"] for index in range(len(rows)) if index not in selected}
            if remaining_labels == {"0", "1"}:
                positive_count = sum(rows[index]["label"] == "1" for index in selected)
                candidate = (
                    abs(len(selected) - target),
                    abs(positive_count - round(len(selected) * prevalence)),
                    len(selected), selected.copy(),
                )
                if best is None or candidate[:3] < best[:3]:
                    best = candidate
            break
        if best and best[0] == 0 and best[1] == 0:
            break
    if best is None:
        raise ValueError("Cannot form train and test sets containing both labels without group leakage")
    test_indexes = best[3]
    train = [row for index, row in enumerate(rows) if index not in test_indexes]
    test = [row for index, row in enumerate(rows) if index in test_indexes]
    if not train or not test:
        raise ValueError("Could not form non-empty train and test sets")
    return train, test


def _metrics(actual, predicted, elapsed_ms):
    tp = sum(a == "1" and p == 1 for a, p in zip(actual, predicted))
    tn = sum(a == "0" and p == 0 for a, p in zip(actual, predicted))
    fp = sum(a == "0" and p == 1 for a, p in zip(actual, predicted))
    fn = sum(a == "1" and p == 0 for a, p in zip(actual, predicted))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    negative_precision = tn / (tn + fn) if tn + fn else 0.0
    negative_recall = tn / (tn + fp) if tn + fp else 0.0
    negative_f1 = (
        2 * negative_precision * negative_recall / (negative_precision + negative_recall)
        if negative_precision + negative_recall else 0.0
    )
    positive_f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision, "recall": recall,
        "f1": positive_f1,
        "macro_f1": (positive_f1 + negative_f1) / 2,
        "accuracy": (tp + tn) / len(actual),
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "latency_ms_per_case": elapsed_ms / len(actual),
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
    }


def _evaluate_split(train, test):
    if not train or not test:
        raise ValueError("Train and test sets must both contain cases")
    if {row["label"] for row in train} != {"0", "1"} or {row["label"] for row in test} != {"0", "1"}:
        raise ValueError("Train and test sets must both contain labels 0 and 1")
    if {row["case_id"] for row in train} & {row["case_id"] for row in test}:
        raise ValueError("Train and test sets share case_id values")
    models = train_models(train)
    report = {"train_cases": len(train), "test_cases": len(test), "metrics": {}}
    report["class_balance"] = {
        "train": dict(Counter(row["label"] for row in train)),
        "test": dict(Counter(row["label"] for row in test)),
    }
    train_domains = set().union(*(_domains(row) for row in train))
    test_domains = set().union(*(_domains(row) for row in test))
    train_campaigns = set().union(*(_campaigns(row) for row in train))
    test_campaigns = set().union(*(_campaigns(row) for row in test))
    train_messages = {_normalized(row["message"]) for row in train}
    test_messages = {_normalized(row["message"]) for row in test}
    report["split_overlap"] = {
        "domains": len(train_domains & test_domains),
        "duplicate_messages": len(train_messages & test_messages),
        "campaigns": len(train_campaigns & test_campaigns),
    }
    if any(report["split_overlap"].values()):
        raise ValueError("Train and test sets share a domain, campaign, or duplicate message")
    for mode, model in models.items():
        started = time.perf_counter()
        predictions = [predict(model, row["message"], row["url"], mode) for row in test]
        elapsed_ms = (time.perf_counter() - started) * 1000
        report["metrics"][mode] = _metrics([row["label"] for row in test], predictions, elapsed_ms)
    return report


def evaluate_dataset(rows, seed=42):
    train, test = split_rows(rows, seed)
    return {"seed": seed, **_evaluate_split(train, test)}


def evaluate_fixed_split(train, test):
    """Evaluate a previously frozen split without selecting a new test set."""
    return {"split_type": "locked", **_evaluate_split(train, test)}


def evaluate_many(rows, seeds):
    """Repeat group-held-out evaluation on fixed seeds as a robustness check."""
    seeds = list(seeds)
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Provide at least one distinct evaluation seed")
    runs = [evaluate_dataset(rows, seed) for seed in seeds]
    fields = ("precision", "recall", "f1", "macro_f1", "false_positive_rate", "latency_ms_per_case")
    summary = {}
    for mode in ("message", "url", "combined"):
        summary[mode] = {}
        for field in fields:
            values = [run["metrics"][mode][field] for run in runs]
            summary[mode][field] = {
                "count": len(values), "mean": statistics.mean(values),
                "min": min(values), "max": max(values),
            }
    return {"seeds": seeds, "runs": runs, "summary": summary}


def main():
    parser = argparse.ArgumentParser(description="Evaluate paired message/URL cases")
    parser.add_argument("csv", help="CSV containing paired cases and binary labels")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--seeds", help="Comma-separated fixed seeds for repeated group-held-out evaluation")
    parser.add_argument("--test-csv", help="Locked test CSV; the positional CSV is its training set")
    parser.add_argument("--model-out", help="Save models trained on all rows after held-out evaluation")
    parser.add_argument("--report-out", help="Save evaluation JSON")
    args = parser.parse_args()
    rows = load_rows(args.csv)
    if args.test_csv and args.seeds:
        parser.error("--test-csv cannot be combined with --seeds")
    seeds = [int(item.strip()) for item in args.seeds.split(",")] if args.seeds else None
    report = (evaluate_fixed_split(rows, load_rows(args.test_csv)) if args.test_csv else
              evaluate_many(rows, seeds) if seeds else evaluate_dataset(rows, args.seed))
    print(json.dumps(report, indent=2))
    if args.report_out:
        Path(args.report_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.model_out:
        Path(args.model_out).write_text(json.dumps(train_models(rows)), encoding="utf-8")


if __name__ == "__main__":
    main()
