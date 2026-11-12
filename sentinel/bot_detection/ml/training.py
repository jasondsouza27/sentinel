"""Train and evaluate the profile-metadata bot classifier (run in .venv-text-ml).

Evaluation is designed around source shift:
1. Leave-one-dataset-out (LODO): for each mixed-label dataset, train on every
   other dataset and test on the held-out one. This is the headline result.
2. In-distribution: a stratified 70/15/15 split over all datasets (per dataset
   and label), for comparison only.
Each source is capped per label so the 50k-account midterm set cannot dominate.
Candidates: gradient boosting, logistic regression, and Sentinel's existing hand-set
heuristic (its profile-based signals) as a baseline.
"""

import hashlib
import json
import platform
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from ..features import username_features
from ..scoring import HeuristicScorer
from .features import FEATURES, vector
from .source import load_accounts

CAP_PER_DATASET_LABEL = 4000
SEED = 2026
# Datasets with both labels become leave-one-dataset-out folds (only those present are used).
MIXED_CANDIDATES = ["gilani-2017", "cresci-rtbust-2019", "cresci-stock-2018", "midterm-2018",
                    "botometer-feedback-2019", "cresci-2015", "cresci-2017"]
# Release gate, fixed before any model is served: a live estimate is shown only if the
# chosen model generalises to every held-out dataset and is well calibrated.
GATE = {"min_lodo_auc_each_dataset": 0.80, "max_in_distribution_ece": 0.05}


def capped(rows, rng):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["dataset"], row["label"])].append(row)
    out = []
    for key in sorted(groups):
        group = groups[key]
        rng.shuffle(group)
        out.extend(group[:CAP_PER_DATASET_LABEL])
    return out


def split(rows, rng):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["dataset"], row["label"])].append(row)
    parts = {"train": [], "calibration": [], "test": []}
    for key in sorted(groups):
        group = groups[key]
        rng.shuffle(group)
        n = len(group)
        a, b = int(n * 0.7), int(n * 0.85)
        parts["train"] += group[:a]; parts["calibration"] += group[a:b]; parts["test"] += group[b:]
    return parts


def matrix(rows):
    X = np.array([vector(r) for r in rows], dtype=float)
    y = np.array([r["label"] == "bot" for r in rows], dtype=int)
    return X, y


def heuristic_scores(rows):
    """Sentinel's hand-set weights, using only the profile signals these rows support."""
    scorer = HeuristicScorer()
    out = []
    for r in rows:
        f = {"account_age_days": r["age_days"], "bio_promotional": None,
             "following_to_followers": round(r["following"] / max(r["followers"], 1), 2), "following_count": r["following"],
             **username_features(r["username"])}
        result = scorer.score(f, 0)
        score = result["score"] if result["score"] is not None else result["indicative_score"]
        out.append((score or 0) / 100)
    return np.array(out)


def metrics(y, p, threshold=0.5):
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    pred = p >= threshold
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum()); tn = int((~pred & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    out = {"n": int(len(y)), "bots": int(y.sum()), "humans": int((y == 0).sum()),
           "precision": round(precision, 4), "recall": round(recall, 4),
           "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
           "human_false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None,
           "accuracy": round((tp + tn) / len(y), 4)}
    if 0 < y.sum() < len(y):
        out["roc_auc"] = round(float(roc_auc_score(y, p)), 4)
        out["average_precision"] = round(float(average_precision_score(y, p)), 4)
    out["brier"] = round(float(brier_score_loss(y, np.clip(p, 0, 1))), 4)
    return out


def ece(y, p, bins=10):
    total = 0.0
    for low in np.linspace(0, 1, bins, endpoint=False):
        mask = (p >= low) & (p < low + 1 / bins) if low < 0.9 else (p >= low)
        if mask.any():
            total += mask.mean() * abs(y[mask].mean() - p[mask].mean())
    return round(float(total), 4)


def models():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "gradient_boosting": lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                                                     l2_regularization=1.0, class_weight="balanced",
                                                                     random_state=SEED),
        "logistic_regression": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")),
    }


def calibrate(raw_cal, y_cal):
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_cal, y_cal)
    return iso


def train(data_dir, artifact_dir, report_dir):
    import joblib
    import sklearn
    data_dir, artifact_dir, report_dir = Path(data_dir), Path(artifact_dir), Path(report_dir)
    started = time.time()
    rng = random.Random(SEED)
    rows = [r for r in load_accounts(data_dir / "accounts.jsonl") if vector(r) is not None]
    labels_by_dataset = defaultdict(set)
    for r in rows:
        labels_by_dataset[r["dataset"]].add(r["label"])
    MIXED = [d for d in MIXED_CANDIDATES if labels_by_dataset.get(d) == {"bot", "human"}]
    pool = capped(rows, rng)
    report = {"accounts_total": len(rows), "accounts_after_cap": len(pool),
              "pool_composition": {f"{d}/{l}": n for (d, l), n in sorted(Counter((r["dataset"], r["label"]) for r in pool).items())},
              "features": FEATURES, "cap_per_dataset_label": CAP_PER_DATASET_LABEL}

    # ---- 1. leave-one-dataset-out ----
    lodo = {}
    for held in MIXED:
        train_rows = [r for r in pool if r["dataset"] != held]
        test_rows = [r for r in rows if r["dataset"] == held]  # full held-out set, not capped
        inner = split(train_rows, random.Random(SEED))
        Xt, yt = matrix(inner["train"] + inner["test"])
        Xc, yc = matrix(inner["calibration"])
        Xh, yh = matrix(test_rows)
        lodo[held] = {"heuristic": metrics(yh, heuristic_scores(test_rows))}
        for name, make in models().items():
            model = make().fit(Xt, yt)
            iso = calibrate(model.predict_proba(Xc)[:, 1], yc)
            p = iso.predict(model.predict_proba(Xh)[:, 1])
            lodo[held][name] = {**metrics(yh, p), "ece": ece(yh, p)}
        print(held, json.dumps({k: (v.get("roc_auc"), v["f1"]) for k, v in lodo[held].items()}), flush=True)
    report["leave_one_dataset_out"] = lodo
    report["leave_one_dataset_out_mean_auc"] = {
        name: round(float(np.mean([lodo[d][name]["roc_auc"] for d in MIXED])), 4)
        for name in ("heuristic", "gradient_boosting", "logistic_regression")}

    # ---- 2. in-distribution split; choose the model on calibration data ----
    parts = split(pool, random.Random(SEED + 1))
    Xt, yt = matrix(parts["train"]); Xc, yc = matrix(parts["calibration"]); Xs, ys = matrix(parts["test"])
    fitted, chosen = {}, None
    for name, make in models().items():
        model = make().fit(Xt, yt)
        raw_cal = model.predict_proba(Xc)[:, 1]
        iso = calibrate(raw_cal, yc)
        cal_auc = metrics(yc, iso.predict(raw_cal))["roc_auc"]
        fitted[name] = (model, iso, cal_auc)
        if chosen is None or cal_auc > fitted[chosen][2]:
            chosen = name
    in_dist = {"heuristic": metrics(ys, heuristic_scores(parts["test"]))}
    for name, (model, iso, cal_auc) in fitted.items():
        p = iso.predict(model.predict_proba(Xs)[:, 1])
        in_dist[name] = {**metrics(ys, p), "ece": ece(ys, p), "calibration_auc": cal_auc}
        in_dist[name]["by_dataset"] = {
            d: metrics(ys[[i for i, r in enumerate(parts["test"]) if r["dataset"] == d]],
                       p[[i for i, r in enumerate(parts["test"]) if r["dataset"] == d]])
            for d in sorted({r["dataset"] for r in parts["test"]})}
    report["in_distribution"] = in_dist
    report["chosen_model"] = chosen
    report["selection_rule"] = "highest calibration-split ROC AUC (in-distribution); LODO results reported for every candidate"

    # ---- export the chosen model ----
    model, iso, _ = fitted[chosen]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact_dir / "model.joblib")
    calibration = {"x": [float(v) for v in iso.X_thresholds_], "y": [float(v) for v in iso.y_thresholds_]}
    (artifact_dir / "calibration.json").write_text(json.dumps(calibration))
    files = {n: hashlib.sha256((artifact_dir / n).read_bytes()).hexdigest() for n in ("model.joblib", "calibration.json")}
    worst = min(lodo[d][chosen]["roc_auc"] for d in MIXED)
    passed = worst >= GATE["min_lodo_auc_each_dataset"] and in_dist[chosen]["ece"] <= GATE["max_in_distribution_ece"]
    report["release_gate"] = {**GATE, "worst_lodo_auc": worst, "in_distribution_ece": in_dist[chosen]["ece"], "passed": passed}
    manifest = {"schema": "sentinel.bot_ml.artifact/1", "model_version": "bot-ml-v1", "model": chosen,
                "release_gate": report["release_gate"],
                "features": FEATURES, "files": files, "platforms": ["x"],
                "trained_on": "Bot Repository Twitter datasets 2017-2019 (profile metadata only)",
                "data_sha256": json.loads((data_dir / "audit.json").read_text())["accounts_sha256"],
                "sklearn": sklearn.__version__, "python": platform.python_version(),
                "lodo_mean_auc": report["leave_one_dataset_out_mean_auc"][chosen],
                "release": "released" if passed else "research_only"}
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report["train_seconds"] = round(time.time() - started, 1)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    (report_dir / "data-audit.json").write_text((data_dir / "audit.json").read_text())
    return report
