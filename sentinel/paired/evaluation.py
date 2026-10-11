"""Validation-only selection and one sealed, group-paired final comparison."""

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sentinel.url_ml.calibration import apply_calibration, fit_calibration
from sentinel.url_ml.metrics import bootstrap_weights, choose_threshold, point_metrics, predictions

from .models import BranchCandidate, score_candidate

BRANCHES = ("message", "url", "combined")


@dataclass
class Selection:
    candidate: BranchCandidate
    raw_threshold: float | None
    validation_report: dict


def _labels(rows):
    if not rows or any(row.get("label") not in {"0", "1"} for row in rows):
        raise ValueError("paired evaluation needs binary reviewed labels")
    ids = [row["case_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case_id in evaluation partition")
    return [int(row["label"]) for row in rows]


def select_candidates(candidates: dict[str, tuple[BranchCandidate, ...]],
                      validation: list[dict]) -> dict[str, Selection]:
    labels = _labels(validation)
    if set(labels) != {0, 1}:
        raise ValueError("validation needs both classes")
    selected = {}
    for branch in BRANCHES:
        options = candidates.get(branch, ())
        if not options:
            raise ValueError(f"{branch} has no fitted candidates")
        trials = []
        for candidate in options:
            scores = score_candidate(candidate, validation)
            if len(scores) != len(validation):
                raise ValueError("candidate scored a different case count")
            threshold = choose_threshold(labels, scores, max_fpr=.05)
            report = point_metrics(labels, scores, threshold)
            report.update({"rows": len(validation), "raw_threshold": threshold,
                           "fpr_budget": .05, "config_id": candidate.config_id})
            trials.append(Selection(candidate, threshold, report))
        selected[branch] = min(trials, key=lambda item: (
            -(item.validation_report["recall"] or 0),
            -(item.validation_report["precision"] or 0),
            item.validation_report["fpr"] if item.validation_report["fpr"] is not None else 1,
            item.candidate.config_id,
        ))
    return selected


def fit_calibrators(selections: dict[str, Selection], calibration: list[dict]) -> dict:
    labels = _labels(calibration)
    output = {}
    for branch in BRANCHES:
        scores = score_candidate(selections[branch].candidate, calibration)
        if len(scores) != len(calibration):
            raise ValueError("calibrator scored a different case count")
        output[branch] = fit_calibration(labels, scores, selections[branch].raw_threshold)
    return output


def _aggregate_breakdowns(rows, labels, branch_scores, thresholds, calibrators, *, train_domains=None, parser=None):
    source_map = {name: f"source_{i + 1}" for i, name in
                  enumerate(sorted({row.get("source_name", "unknown") for row in rows}))}
    categories = defaultdict(list)
    for i, row in enumerate(rows):
        categories[("source", source_map[row.get("source_name", "unknown")])].append(i)
        categories[("channel", row.get("channel", "unknown"))].append(i)
        date = row.get("observed_on", "")
        categories[("observation_date", date[:7] if date else "unknown")].append(i)
        url = row["url"]
        pattern = "query" if "?" in url else "punycode" if "xn--" in url else "userinfo" if "@" in url else "ordinary"
        categories[("url_pattern", pattern)].append(i)
        if train_domains is not None:
            domain = parser.normalize(url).domain_group if parser is not None else row.get("domain_group")
            categories[("unseen_domain", "unseen" if domain not in train_domains else "seen")].append(i)
    output = {}
    for (category, key), indices in sorted(categories.items()):
        entry = {"cases": len(indices), "class_counts": dict(Counter(str(labels[i]) for i in indices)),
                 "branches": {}}
        for branch in BRANCHES:
            metric = point_metrics([labels[i] for i in indices],
                                   [branch_scores[branch][i] for i in indices], thresholds[branch])
            entry["branches"][branch] = {name: metric[name] for name in
                                         ("confusion", "precision", "recall", "fpr", "f1")}
        output.setdefault(category, {})[key] = entry
    if train_domains is None:
        output["unseen_domain"] = {"status": "unavailable_without_training_domains"}
    return output


def evaluate_branches(selections: dict[str, Selection], test: list[dict],
                      calibrators: dict, groups: dict[str, str], *,
                      replicates: int = 1000, train_domains: set[str] | None = None,
                      baseline_train: list[dict] | None = None,
                      private_error_path: Path | None = None) -> dict:
    labels = _labels(test)
    ids = [row["case_id"] for row in test]
    if set(labels) != {0, 1} or any(case_id not in groups for case_id in ids):
        raise ValueError("final test needs both classes and a connected group for every case")
    if replicates < 2:
        raise ValueError("bootstrap needs at least two replicates")
    group_values = [groups[case_id] for case_id in ids]
    raw, calibrated, point, elapsed = {}, {}, {}, {}
    thresholds = {}
    for branch in BRANCHES:
        selection = selections[branch]
        started = time.perf_counter()
        scores = score_candidate(selection.candidate, test)
        elapsed[branch] = (time.perf_counter() - started) * 1000 / len(test)
        if len(scores) != len(test):
            raise ValueError("branches did not score identical final cases")
        raw[branch] = scores
        thresholds[branch] = selection.raw_threshold
        calibrated[branch] = apply_calibration(calibrators[branch], scores)
        point[branch] = point_metrics(labels, scores, selection.raw_threshold, calibrated[branch])

    support = all(len({group_values[i] for i, label in enumerate(labels) if label == target}) >= 2
                  for target in (0, 1))
    metric_names = ("recall", "fpr", "precision", "f1", "macro_f1", "pr_auc", "brier", "ece")
    distributions = {branch: {name: [] for name in metric_names} for branch in BRANCHES}
    deltas = {individual: {name: [] for name in ("recall", "fpr")} for individual in ("message", "url")}
    if support:
        for weights in bootstrap_weights(group_values, replicates=replicates, seed=42):
            sample = {branch: point_metrics(labels, raw[branch], thresholds[branch],
                                            calibrated[branch], weights) for branch in BRANCHES}
            for branch in BRANCHES:
                for name in metric_names:
                    if sample[branch][name] is not None:
                        distributions[branch][name].append(sample[branch][name])
            for individual in ("message", "url"):
                for name in ("recall", "fpr"):
                    if sample["combined"][name] is not None and sample[individual][name] is not None:
                        deltas[individual][name].append(sample["combined"][name] - sample[individual][name])

    def interval(values):
        return np.percentile(values, [2.5, 97.5]).tolist() if len(values) >= max(2, replicates // 2) else None

    branches = {}
    for branch in BRANCHES:
        branches[branch] = {
            **point[branch], "rows": len(test), "groups": len(set(group_values)),
            "config_id": selections[branch].candidate.config_id,
            "raw_threshold": thresholds[branch],
            "calibration_status": calibrators[branch].status,
            "latency_ms_per_case": elapsed[branch],
            "peak_memory_bytes": selections[branch].candidate.fit_record.get("peak_bytes"),
            "intervals": {name: interval(distributions[branch][name]) for name in metric_names},
        }
    paired = {}
    for individual in ("message", "url"):
        paired[f"combined_minus_{individual}"] = {
            name + "_delta": (point["combined"][name] - point[individual][name]
                              if point["combined"][name] is not None and point[individual][name] is not None else None)
            for name in ("recall", "fpr")
        } | {name + "_interval": interval(deltas[individual][name]) for name in ("recall", "fpr")}
    report = {
        "schema_version": 1, "study_status": "research_only",
        "final_cases": len(test), "branches": branches, "paired_deltas": paired,
        "bootstrap": {"unit": "connected_group", "seed": 42, "replicates": replicates,
                      "status": "complete" if support else "insufficient_group_support"},
        "breakdowns": _aggregate_breakdowns(test, labels, raw, thresholds, calibrators,
                                             train_domains=train_domains,
                                             parser=getattr(selections["url"].candidate.model, "parser", None)),
    }
    if baseline_train is not None:
        from sentinel import research
        baseline = research.train_models(baseline_train)
        report["naive_bayes_fixed_baseline"] = {
            "selection": "fixed_default_decision_no_fpr_budget",
            "branches": {mode: research._metrics([row["label"] for row in test],
                                                [research.predict(baseline[mode], row["message"], row["url"], mode)
                                                 for row in test], 0)
                         for mode in ("message", "url", "combined")},
        }
    if private_error_path is not None:
        errors = {branch: {"false_positive": [], "false_negative": []} for branch in BRANCHES}
        for branch in BRANCHES:
            predicted = predictions(raw[branch], thresholds[branch])
            for case_id, label, value in zip(ids, labels, predicted):
                if int(value) != label:
                    errors[branch]["false_positive" if value else "false_negative"].append(case_id)
        Path(private_error_path).write_text(json.dumps(errors, indent=2), encoding="utf-8")
    return report
