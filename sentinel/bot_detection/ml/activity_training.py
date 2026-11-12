"""Train and evaluate the activity + profile bot classifier on cresci post histories.

Protocol (fixed before training):
- Leave-one-bot-family-out (B): hold out one bot family (fake followers, social
  spambots 1/2/3, traditional spambots) together with a fixed 20% of each human
  subset; train on the rest. Tests whether a *new kind* of bot is caught.
- Cross-dataset (A): train on cresci-2015, test on cresci-2017, and the reverse.
- Model selection uses only B: highest worst-fold AUC. A is the untouched check.
- Release gate: AUC >= 0.80 on every A and B fold, and in-distribution ECE <= 0.05.
Candidates: gradient boosting, logistic regression, and Sentinel's heuristic on the
same features.
"""

import hashlib
import json
import platform
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from ..features import username_features
from ..scoring import HeuristicScorer
from .features import ACTIVITY_FEATURES, FEATURES as PROFILE_FEATURES, activity_vector
from .training import calibrate, ece, metrics

FEATURES = ACTIVITY_FEATURES + PROFILE_FEATURES
FAMILIES = {"FSF": "fake_followers", "INT": "fake_followers", "TWT": "fake_followers", "fake_followers": "fake_followers",
            "social_spambots_1": "social_spambots_1", "social_spambots_2": "social_spambots_2",
            "social_spambots_3": "social_spambots_3", "traditional_spambots_1": "traditional_spambots",
            "traditional_spambots_2": "traditional_spambots", "traditional_spambots_3": "traditional_spambots",
            "traditional_spambots_4": "traditional_spambots"}
GATE = {"min_auc_every_fold": 0.80, "max_in_distribution_ece": 0.05}
SEED = 2026


def load(path):
    rows = []
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            row["x"] = activity_vector(row["activity"], row["profile"])
            if row["x"] is not None:
                row["family"] = FAMILIES.get(row["subset"], "human") if row["label"] == "bot" else "human"
                rows.append(row)
    return rows


def matrix(rows):
    return np.array([r["x"] for r in rows], dtype=float), np.array([r["label"] == "bot" for r in rows], dtype=int)


def heuristic(rows):
    scorer, out = HeuristicScorer(), []
    for r in rows:
        p = r["profile"]
        f = {**r["activity"], "account_age_days": p["age_days"], "following_count": p["following"],
             "following_to_followers": round(p["following"] / max(p["followers"], 1), 2), **username_features(p["username"])}
        result = scorer.score(f, 100)
        score = result["score"] if result["score"] is not None else result["indicative_score"]
        out.append((score or 0) / 100)
    return np.array(out)


def candidates():
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return {
        "gradient_boosting": lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                                                                     l2_regularization=1.0, class_weight="balanced",
                                                                     random_state=SEED),
        "logistic_regression": lambda: make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                                                     LogisticRegression(max_iter=3000, class_weight="balanced")),
    }


def fit_and_score(train_rows, test_rows, seed):
    """Fit every candidate (calibrated on an inner 20% split) and score test rows."""
    rng = random.Random(seed)
    train_rows = list(train_rows)
    rng.shuffle(train_rows)
    cut = int(len(train_rows) * 0.8)
    Xt, yt = matrix(train_rows[:cut]); Xc, yc = matrix(train_rows[cut:]); Xs, ys = matrix(test_rows)
    out = {"heuristic": metrics(ys, heuristic(test_rows))}
    fitted = {}
    for name, make in candidates().items():
        model = make().fit(Xt, yt)
        iso = calibrate(model.predict_proba(Xc)[:, 1], yc)
        p = iso.predict(model.predict_proba(Xs)[:, 1])
        out[name] = {**metrics(ys, p), "ece": ece(ys, p)}
        fitted[name] = (model, iso)
    return out, fitted


def human_holdout(rows):
    """Fixed 20% of each human subset, reused by every family fold."""
    held = set()
    by_subset = defaultdict(list)
    for i, r in enumerate(rows):
        if r["label"] == "human":
            by_subset[r["subset"]].append(i)
    rng = random.Random(SEED)
    for subset in sorted(by_subset):
        ids = by_subset[subset]
        rng.shuffle(ids)
        held.update(ids[:max(1, len(ids) // 5)])
    return held


def train(data_dir, artifact_dir, report_dir):
    import joblib
    import sklearn
    started = time.time()
    data_dir, artifact_dir, report_dir = Path(data_dir), Path(artifact_dir), Path(report_dir)
    rows = load(data_dir / "activity.jsonl")
    report = {"accounts": len(rows), "features": FEATURES,
              "composition": {f: sum(1 for r in rows if r["family"] == f) for f in sorted({r["family"] for r in rows})}}

    # B. leave one bot family out (selection folds)
    held_humans = human_holdout(rows)
    families = sorted({r["family"] for r in rows} - {"human"})
    family_folds = {}
    for family in families:
        test = [r for i, r in enumerate(rows) if r["family"] == family or i in held_humans]
        trainset = [r for i, r in enumerate(rows) if r["family"] != family and i not in held_humans]
        family_folds[family], _ = fit_and_score(trainset, test, SEED)
        print("family", family, json.dumps({k: v.get("roc_auc") for k, v in family_folds[family].items()}), flush=True)
    report["leave_one_bot_family_out"] = family_folds
    names = list(candidates())
    worst = {n: min(family_folds[f][n]["roc_auc"] for f in families) for n in names}
    chosen = max(names, key=lambda n: worst[n])
    report["selection"] = {"rule": "highest worst-fold AUC over leave-one-bot-family-out", "worst_family_auc": worst,
                           "chosen": chosen}

    # A. cross-dataset (untouched check)
    cross = {}
    for train_name, test_name in (("cresci-2015", "cresci-2017"), ("cresci-2017", "cresci-2015")):
        trainset = [r for r in rows if r["dataset"] == train_name]
        test = [r for r in rows if r["dataset"] == test_name]
        cross[f"{train_name}->{test_name}"], _ = fit_and_score(trainset, test, SEED)
        print("cross", train_name, "->", test_name, json.dumps({k: v.get("roc_auc") for k, v in cross[f"{train_name}->{test_name}"].items()}), flush=True)
    report["cross_dataset"] = cross

    # In-distribution stratified split, then the final model on train + calibration
    rng = random.Random(SEED + 7)
    groups = defaultdict(list)
    for r in rows:
        groups[(r["subset"], r["label"])].append(r)
    train_rows, test_rows = [], []
    for key in sorted(groups):
        g = groups[key]
        rng.shuffle(g)
        cut = int(len(g) * 0.85)
        train_rows += g[:cut]; test_rows += g[cut:]
    in_dist, fitted = fit_and_score(train_rows, test_rows, SEED + 11)
    report["in_distribution"] = in_dist

    fold_aucs = [family_folds[f][chosen]["roc_auc"] for f in families] + [cross[k][chosen]["roc_auc"] for k in cross]
    passed = min(fold_aucs) >= GATE["min_auc_every_fold"] and in_dist[chosen]["ece"] <= GATE["max_in_distribution_ece"]
    report["release_gate"] = {**GATE, "worst_fold_auc": min(fold_aucs), "in_distribution_ece": in_dist[chosen]["ece"],
                              "passed": passed}

    model, iso = fitted[chosen]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, artifact_dir / "model.joblib")
    (artifact_dir / "calibration.json").write_text(json.dumps({"x": [float(v) for v in iso.X_thresholds_],
                                                               "y": [float(v) for v in iso.y_thresholds_]}))
    files = {n: hashlib.sha256((artifact_dir / n).read_bytes()).hexdigest() for n in ("model.joblib", "calibration.json")}
    manifest = {"schema": "sentinel.bot_ml.artifact/1", "kind": "activity", "model_version": "bot-ml-activity-v1",
                "model": chosen, "features": FEATURES, "files": files, "platforms": ["x"], "min_posts": 20,
                "posts_used": 100, "release_gate": report["release_gate"],
                "trained_on": "cresci-2015 and cresci-2017 post histories (Twitter, 2009-2017)",
                "data_sha256": json.loads((data_dir / "activity-audit.json").read_text())["activity_sha256"],
                "sklearn": sklearn.__version__, "python": platform.python_version(),
                "release": "released" if passed else "research_only"}
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report["train_seconds"] = round(time.time() - started, 1)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "evaluation-activity.json").write_text(json.dumps(report, indent=2) + "\n")
    (report_dir / "activity-audit.json").write_text((data_dir / "activity-audit.json").read_text())
    return report
