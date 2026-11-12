"""Fine-tune, calibrate, evaluate and export the SMS scam-text model.

Run in the `.venv-text-ml` environment (torch, transformers, scikit-learn, onnx,
onnxruntime). The test split is scored once, after every choice (epoch,
temperature, threshold) was made on the calibration split.
"""

import hashlib
import json
import math
import platform
import random
import shutil
import time
from collections import Counter
from pathlib import Path

import numpy as np

from . import LABELS
from .source import load_dataset

CONFIG = {
    "base_model": "distilbert-base-uncased",
    "max_length": 128,
    "epochs": 4,
    "batch_size": 32,
    "learning_rate": 3e-5,
    "weight_decay": 0.01,
    "warmup_fraction": 0.1,
    "seed": 13,
    "target_ham_fpr": 0.01,
}
SCAM = [LABELS.index("spam"), LABELS.index("smishing")]


# ---------- metrics ----------

def softmax(logits, temperature=1.0):
    z = np.asarray(logits, dtype=np.float64) / temperature
    z -= z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def ece(probabilities, labels, bins=15):
    confidence = probabilities.max(axis=1)
    correct = probabilities.argmax(axis=1) == labels
    total = 0.0
    for low in np.linspace(0, 1, bins, endpoint=False):
        mask = (confidence > low) & (confidence <= low + 1 / bins)
        if mask.any():
            total += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    return float(total)


def classification(probabilities, labels, threshold=None):
    predicted = probabilities.argmax(axis=1)
    report = {}
    for index, name in enumerate(LABELS):
        tp = int(((predicted == index) & (labels == index)).sum())
        fp = int(((predicted == index) & (labels != index)).sum())
        fn = int(((predicted != index) & (labels == index)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        report[name] = {"precision": round(precision, 4), "recall": round(recall, 4),
                        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
                        "support": int((labels == index).sum())}
    confusion = [[int(((labels == a) & (predicted == b)).sum()) for b in range(len(LABELS))] for a in range(len(LABELS))]
    scam_true = np.isin(labels, SCAM)
    scam_score = probabilities[:, SCAM].sum(axis=1)
    scam_pred = scam_score >= (threshold if threshold is not None else 0.5)
    tp = int((scam_pred & scam_true).sum()); fp = int((scam_pred & ~scam_true).sum())
    fn = int((~scam_pred & scam_true).sum()); tn = int((~scam_pred & ~scam_true).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "accuracy": round(float((predicted == labels).mean()), 4),
        "macro_f1": round(float(np.mean([report[n]["f1"] for n in LABELS])), 4),
        "per_class": report,
        "confusion_matrix": {"rows_true_cols_predicted": list(LABELS), "counts": confusion},
        "scam_vs_ham": {"threshold": round(float(threshold if threshold is not None else 0.5), 4),
                        "precision": round(precision, 4), "recall": round(recall, 4),
                        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
                        "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
                        "counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}},
        "ece": round(ece(probabilities, labels), 4),
    }


def threshold_for_fpr(probabilities, labels, target, floor=0.05, cap=0.9):
    """Scam-score threshold: best recall with ham false-positive rate <= target.

    Among thresholds with equal recall the highest is kept, so no extra ham is
    flagged for no gain; `cap` leaves margin for scams unlike the calibration
    data. (text-ml-v1 first used the lowest qualifying threshold; see
    `revise_threshold`.)
    """
    scores = probabilities[:, SCAM].sum(axis=1)
    is_scam = np.isin(labels, SCAM)
    ham, scam = scores[~is_scam], scores[is_scam]
    best = None
    for threshold in sorted(set(np.round(np.concatenate([scores, [floor, cap]]), 6))):
        if threshold < floor or threshold > cap:
            continue
        if (ham >= threshold).mean() > target:
            continue
        recall = (scam >= threshold).mean() if len(scam) else 0.0
        if best is None or recall > best[0] + 1e-12 or abs(recall - best[0]) <= 1e-12:
            best = (recall, float(threshold))
    return best[1] if best else cap


def revise_threshold(data_dir, artifact_dir, report_dir):
    """Re-choose the threshold on the calibration split with the current rule and
    re-score the test split. The earlier result is kept in the report."""
    from .service import OnnxBackend
    data_dir, artifact_dir, report_dir = Path(data_dir), Path(artifact_dir), Path(report_dir)
    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    records = {r["id"]: r for r in load_dataset(data_dir / "dataset.jsonl")}
    ids = json.loads((data_dir / "splits.json").read_text())["ids"]
    backend = OnnxBackend(artifact_dir / "model.onnx", artifact_dir / "tokenizer.json", manifest["max_length"])
    def scored(name):
        rows = [records[i] for i in ids[name]]
        return (softmax(backend.logits([r["text"] for r in rows]), manifest["temperature"]),
                np.array([LABELS.index(r["label"]) for r in rows]))
    cal_p, cal_y = scored("calibration")
    previous = manifest["scam_threshold"]
    threshold = threshold_for_fpr(cal_p, cal_y, CONFIG["target_ham_fpr"])
    test_p, test_y = scored("test")
    manifest["scam_threshold"] = round(threshold, 6)
    manifest.setdefault("revisions", []).append({
        "change": "threshold rule: best calibration recall within the ham FPR target, highest tied threshold, capped at 0.9",
        "previous_threshold": previous, "threshold": manifest["scam_threshold"],
        "reason": "the first rule took the lowest qualifying threshold, which flagged more ham with no recall gain"})
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    report_path = report_dir / "evaluation.json"
    evaluation = json.loads(report_path.read_text())
    evaluation["first_threshold_result"] = {"scam_threshold": previous,
                                            "calibrated": evaluation["results"]["transformer"]["calibrated"]}
    evaluation["results"]["transformer"]["calibrated"] = classification(test_p, test_y, threshold)
    evaluation["results"]["transformer"]["uncalibrated_note"] = "uses the first threshold; superseded"
    evaluation["scam_threshold"] = manifest["scam_threshold"]
    evaluation["threshold_revision"] = manifest["revisions"][-1]
    report_path.write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    return evaluation["results"]["transformer"]["calibrated"]


# ---------- perturbations for the robustness study ----------

LEET = str.maketrans({"a": "4", "e": "3", "o": "0", "i": "1", "s": "5"})
HOMOGLYPH = str.maketrans({"a": "а", "e": "е", "o": "о", "c": "с", "p": "р"})


def perturb(text, kind, rng):
    words = text.split()
    chosen = [i for i in range(len(words)) if len(words[i]) > 3 and rng.random() < 0.3]
    for i in chosen:
        if kind == "leetspeak":
            words[i] = words[i].lower().translate(LEET)
        elif kind == "homoglyph":
            words[i] = words[i].translate(HOMOGLYPH)
        elif kind == "spacing":
            words[i] = ".".join(words[i])
    return " ".join(words)


# ---------- baseline ----------

def baseline(train, calibration, test):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, make_pipeline

    model = make_pipeline(
        FeatureUnion([("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
                      ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True))]),
        LogisticRegression(max_iter=3000, class_weight="balanced", C=10.0))
    model.fit([r["text"] for r in train], [LABELS.index(r["label"]) for r in train])
    proba = lambda rows: model.predict_proba([r["text"] if isinstance(r, dict) else r for r in rows])
    cal_labels = np.array([LABELS.index(r["label"]) for r in calibration])
    threshold = threshold_for_fpr(proba(calibration), cal_labels, CONFIG["target_ham_fpr"])
    return proba, threshold


# ---------- transformer ----------

def _seed(seed):
    import torch
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)


def _logits(model, tokenizer, texts, device, batch=64):
    import torch
    model.eval()
    out = []
    with torch.no_grad():
        for start in range(0, len(texts), batch):
            enc = tokenizer(texts[start:start + batch], truncation=True, max_length=CONFIG["max_length"],
                            padding=True, return_tensors="pt").to(device)
            out.append(model(**enc).logits.float().cpu().numpy())
    return np.concatenate(out)


def fit_temperature(logits, labels):
    """Temperature that minimizes calibration negative log-likelihood (golden-section search)."""
    def nll(t):
        p = softmax(logits, t)
        return -float(np.log(p[np.arange(len(labels)), labels] + 1e-12).mean())
    low, high = 0.05, 10.0
    ratio = (math.sqrt(5) - 1) / 2
    for _ in range(80):
        a = high - ratio * (high - low); b = low + ratio * (high - low)
        if nll(a) < nll(b): high = b
        else: low = a
    return round((low + high) / 2, 4)


CHALLENGE_SET = Path(__file__).with_name("challenge_set.jsonl")


def challenge(score_fn, threshold):
    """Independent author-written challenge set: genuine Indian transactional and
    personal messages vs modern scams (written before text-ml-v2 was trained)."""
    rows = [json.loads(line) for line in CHALLENGE_SET.read_text().splitlines() if line.strip()]
    scores = score_fn([r["text"] for r in rows])
    ham = [s >= threshold for r, s in zip(rows, scores) if r["label"] == "ham"]
    scam = [s >= threshold for r, s in zip(rows, scores) if r["label"] == "scam"]
    return {"genuine_flagged": f"{sum(ham)}/{len(ham)}", "genuine_false_alarm_rate": round(sum(ham) / len(ham), 4),
            "scams_caught": f"{sum(scam)}/{len(scam)}", "scam_recall": round(sum(scam) / len(scam), 4)}


def train(data_dir, artifact_dir, report_dir, dataset="dataset.jsonl", splits_file="splits.json",
          audit_file="audit.json", version="text-ml-v1"):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    data_dir, artifact_dir, report_dir = Path(data_dir), Path(artifact_dir), Path(report_dir)
    records = load_dataset(data_dir / dataset)
    split_bytes = (data_dir / splits_file).read_bytes()
    split_ids = json.loads(split_bytes)["ids"]
    by_id = {r["id"]: r for r in records}
    train_rows, cal_rows, test_rows = ([by_id[i] for i in split_ids[n]] for n in ("train", "calibration", "test"))
    y = lambda rows: np.array([LABELS.index(r["label"]) for r in rows])
    cal_y, test_y = y(cal_rows), y(test_rows)

    _seed(CONFIG["seed"])
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(CONFIG["base_model"])
    model = AutoModelForSequenceClassification.from_pretrained(
        CONFIG["base_model"], num_labels=len(LABELS), id2label=dict(enumerate(LABELS)),
        label2id={n: i for i, n in enumerate(LABELS)}).to(device)

    counts = Counter(r["label"] for r in train_rows)
    weights = torch.tensor([math.sqrt(len(train_rows) / (len(LABELS) * counts[n])) for n in LABELS],
                           dtype=torch.float32, device=device)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=CONFIG["learning_rate"], weight_decay=CONFIG["weight_decay"])
    steps = CONFIG["epochs"] * math.ceil(len(train_rows) / CONFIG["batch_size"])
    scheduler = get_linear_schedule_with_warmup(optimizer, int(steps * CONFIG["warmup_fraction"]), steps)

    history, best = [], None
    started = time.time()
    order = list(range(len(train_rows)))
    for epoch in range(1, CONFIG["epochs"] + 1):
        model.train()
        random.Random(CONFIG["seed"] + epoch).shuffle(order)
        running = 0.0
        for start in range(0, len(order), CONFIG["batch_size"]):
            batch = [train_rows[i] for i in order[start:start + CONFIG["batch_size"]]]
            enc = tokenizer([r["text"] for r in batch], truncation=True, max_length=CONFIG["max_length"],
                            padding=True, return_tensors="pt").to(device)
            target = torch.tensor([LABELS.index(r["label"]) for r in batch], device=device)
            loss = loss_fn(model(**enc).logits, target)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step(); scheduler.step(); optimizer.zero_grad()
            running += float(loss) * len(batch)
        cal_metrics = classification(softmax(_logits(model, tokenizer, [r["text"] for r in cal_rows], device)), cal_y)
        history.append({"epoch": epoch, "train_loss": round(running / len(order), 4),
                        "calibration_macro_f1": cal_metrics["macro_f1"]})
        print(json.dumps(history[-1]), flush=True)
        if best is None or cal_metrics["macro_f1"] > best[0]:
            best = (cal_metrics["macro_f1"], epoch, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()})
    train_seconds = round(time.time() - started, 1)
    model.load_state_dict(best[2])
    model.to("cpu").eval()

    cal_logits = _logits(model, tokenizer, [r["text"] for r in cal_rows], "cpu")
    temperature = fit_temperature(cal_logits, cal_y)
    threshold = threshold_for_fpr(softmax(cal_logits, temperature), cal_y, CONFIG["target_ham_fpr"])

    # ---- export ONNX + tokenizer ----
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    artifact_dir.mkdir(parents=True)
    sample = tokenizer(["export example"], return_tensors="pt")
    torch.onnx.export(model, (sample["input_ids"], sample["attention_mask"]), str(artifact_dir / "model.onnx"),
                      input_names=["input_ids", "attention_mask"], output_names=["logits"],
                      dynamic_axes={"input_ids": {0: "batch", 1: "sequence"}, "attention_mask": {0: "batch", 1: "sequence"},
                                    "logits": {0: "batch"}}, opset_version=17, dynamo=False)
    tokenizer.backend_tokenizer.save(str(artifact_dir / "tokenizer.json"))

    # ---- score the test split once, through the exported runtime ----
    from .service import OnnxBackend
    backend = OnnxBackend(artifact_dir / "model.onnx", artifact_dir / "tokenizer.json", CONFIG["max_length"])
    # Choose the threshold on the runtime the app serves (ONNX), not on PyTorch scores:
    # tiny numeric differences can otherwise move a threshold across a flat region.
    threshold = threshold_for_fpr(softmax(backend.logits([r["text"] for r in cal_rows]), temperature), cal_y,
                                  CONFIG["target_ham_fpr"])
    test_texts = [r["text"] for r in test_rows]
    parity = float(np.abs(backend.logits([r["text"] for r in cal_rows[:64]]) - cal_logits[:64]).max())
    started = time.time()
    test_logits = backend.logits(test_texts)
    latency_ms = round((time.time() - started) * 1000 / len(test_texts), 2)
    raw_test, calibrated_test = softmax(test_logits), softmax(test_logits, temperature)

    base_proba, base_threshold = baseline(train_rows, cal_rows, test_rows)
    results = {
        "transformer": {
            "uncalibrated": classification(raw_test, test_y, threshold),
            "calibrated": classification(calibrated_test, test_y, threshold),
            "latency_ms_per_message_cpu_batch": latency_ms,
        },
        "baseline_tfidf_logistic_regression": classification(base_proba(test_rows), test_y, base_threshold),
    }
    # Per-source results on the test split (v1 rows are the unchanged v1 test set).
    sources = sorted({r.get("source", "mendeley") for r in test_rows})
    if len(sources) > 1:
        results["by_source"] = {}
        for name in sources:
            index = [i for i, r in enumerate(test_rows) if r.get("source", "mendeley") == name]
            part = [test_rows[i] for i in index]
            results["by_source"][name] = {
                "rows": len(index),
                "transformer": classification(calibrated_test[index], test_y[index], threshold),
                "baseline": classification(base_proba(part), test_y[index], base_threshold)}
    scam_score = lambda proba: proba[:, SCAM].sum(axis=1)
    results["challenge_set"] = {
        "transformer": challenge(lambda texts: scam_score(softmax(backend.logits(texts), temperature)), threshold),
        "baseline": challenge(lambda texts: scam_score(base_proba(texts)), base_threshold)}

    rng = random.Random(7)
    scam_rows = [r for r in test_rows if r["label"] != "ham"]
    scam_y = y(scam_rows)
    robustness = {}
    for kind in ("leetspeak", "homoglyph", "spacing"):
        texts = [perturb(r["text"], kind, rng) for r in scam_rows]
        def recall(proba, thr):
            return round(float((proba[:, SCAM].sum(axis=1) >= thr).mean()), 4)
        robustness[kind] = {
            "transformer_scam_recall": recall(softmax(backend.logits(texts), temperature), threshold),
            "baseline_scam_recall": recall(base_proba(texts), base_threshold),
        }
    robustness["clean"] = {"transformer_scam_recall": round(float((calibrated_test[np.isin(test_y, SCAM)][:, SCAM].sum(axis=1) >= threshold).mean()), 4),
                           "baseline_scam_recall": round(float((base_proba(scam_rows)[:, SCAM].sum(axis=1) >= base_threshold).mean()), 4)}
    del scam_y

    audit = json.loads((data_dir / audit_file).read_text())
    files = {name: hashlib.sha256((artifact_dir / name).read_bytes()).hexdigest() for name in ("model.onnx", "tokenizer.json")}
    manifest = {
        "schema": "sentinel.text_ml.artifact/1",
        "model_version": version,
        "labels": list(LABELS),
        "max_length": CONFIG["max_length"],
        "temperature": temperature,
        "scam_threshold": round(threshold, 6),
        "files": files,
        "data": {"dataset_sha256": audit["dataset_sha256"], "splits_sha256": hashlib.sha256(split_bytes).hexdigest()},
        "training": {**CONFIG, "best_epoch": best[1], "history": history, "train_seconds": train_seconds,
                     "device": device, "torch": torch.__version__, "python": platform.python_version()},
        "onnx_parity_max_abs_logit_difference": round(parity, 6),
        "release": "experimental",
    }
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    report_dir.mkdir(parents=True, exist_ok=True)
    evaluation = {"model_version": version, "test_rows": len(test_rows), "results": results,
                  "robustness": robustness, "manifest_files": files, "data": manifest["data"],
                  "training": manifest["training"], "temperature": temperature, "scam_threshold": manifest["scam_threshold"],
                  "onnx_parity_max_abs_logit_difference": manifest["onnx_parity_max_abs_logit_difference"]}
    (report_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")
    (report_dir / "data-audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return evaluation


def select_ensemble(data_dir, artifact_dir, report_dir, dataset="dataset-v2.jsonl", splits_file="splits-v2.json"):
    """Choose among {transformer, TF-IDF baseline, their average} on the calibration
    split only, then score test and the challenge set once for all three.

    Pre-stated rule: among candidates whose calibration ham FPR at their own
    threshold is <= the target, take the highest calibration macro-F1; ties go to the
    lower calibration FPR. The chosen ensemble is written into the artifact."""
    import joblib
    from .service import OnnxBackend
    data_dir, artifact_dir, report_dir = Path(data_dir), Path(artifact_dir), Path(report_dir)
    manifest = json.loads((artifact_dir / "manifest.json").read_text())
    records = {r["id"]: r for r in load_dataset(data_dir / dataset)}
    ids = json.loads((data_dir / splits_file).read_text())["ids"]
    train_rows, cal_rows, test_rows = ([records[i] for i in ids[n]] for n in ("train", "calibration", "test"))
    y = lambda rows: np.array([LABELS.index(r["label"]) for r in rows])
    backend = OnnxBackend(artifact_dir / "model.onnx", artifact_dir / "tokenizer.json", manifest["max_length"])
    temperature = manifest["temperature"]

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, make_pipeline
    lexical = make_pipeline(
        FeatureUnion([("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
                      ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True))]),
        LogisticRegression(max_iter=3000, class_weight="balanced", C=10.0))
    lexical.fit([r["text"] for r in train_rows], y(train_rows))

    def candidates(texts):
        t = softmax(backend.logits(texts), temperature)
        b = lexical.predict_proba(texts)
        return {"transformer": t, "baseline": b, "average": (t + b) / 2}

    cal = candidates([r["text"] for r in cal_rows])
    test = candidates([r["text"] for r in test_rows])
    cal_y, test_y = y(cal_rows), y(test_rows)
    summary, chosen = {}, None
    for name in ("transformer", "baseline", "average"):
        threshold = threshold_for_fpr(cal[name], cal_y, CONFIG["target_ham_fpr"])
        cal_metrics = classification(cal[name], cal_y, threshold)
        summary[name] = {"threshold": round(threshold, 6), "calibration": cal_metrics}
        key = (cal_metrics["macro_f1"], -cal_metrics["scam_vs_ham"]["false_positive_rate"])
        if cal_metrics["scam_vs_ham"]["false_positive_rate"] <= CONFIG["target_ham_fpr"] and (chosen is None or key > chosen[1]):
            chosen = (name, key)
    # Only now look at test and the challenge set, for every candidate.
    scam_score = lambda proba: proba[:, SCAM].sum(axis=1)
    for name in summary:
        threshold = summary[name]["threshold"]
        summary[name]["test"] = classification(test[name], test_y, threshold)
        summary[name]["challenge_set"] = challenge(lambda texts: scam_score(candidates(texts)[name]), threshold)
    name = chosen[0]
    if name != "transformer":
        joblib.dump(lexical, artifact_dir / "lexical.joblib")
        manifest["files"]["lexical.joblib"] = hashlib.sha256((artifact_dir / "lexical.joblib").read_bytes()).hexdigest()
        manifest["ensemble"] = {"method": name, "members": ["model.onnx", "lexical.joblib"],
                                "note": "transformer probabilities are temperature-scaled before averaging"
                                        if name == "average" else "lexical model only"}
    manifest["scam_threshold"] = summary[name]["threshold"]
    manifest.setdefault("revisions", []).append({
        "change": f"model selection on calibration data: chose '{name}'",
        "rule": "highest calibration macro-F1 with calibration ham FPR <= target; ties to lower FPR",
        "threshold": manifest["scam_threshold"]})
    (artifact_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    report = json.loads((report_dir / "evaluation.json").read_text())
    report["model_selection"] = {"chosen": name, "candidates": summary}
    report["scam_threshold"] = manifest["scam_threshold"]
    (report_dir / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return name, summary
