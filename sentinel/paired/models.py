"""Bounded, sequential branch candidates for paired messages and URLs."""

import hashlib
import math
import multiprocessing
import os
import time
from dataclasses import dataclass
from pathlib import Path

MAX_PEAK_BYTES = 8 * 1024**3
MAX_NATIVE_THREADS = 4


@dataclass
class BranchCandidate:
    kind: str
    config_id: str
    model: object
    fit_record: dict


class LateFusionUnavailable(ValueError):
    """Group-held-out fusion cannot be fit without leakage."""


class LateFusionModel:
    def __init__(self, parser, message_model, url_model, classifier):
        self.parser = parser
        self.message_model = message_model
        self.url_model = url_model
        self.classifier = classifier

    @property
    def classes_(self):
        return self.classifier.classes_

    def predict_proba(self, rows):
        import numpy as np
        from threadpoolctl import threadpool_limits

        message = _positive_scores(self.message_model, rows)
        url = _positive_scores(self.url_model, rows)
        with threadpool_limits(limits=MAX_NATIVE_THREADS):
            return self.classifier.predict_proba(np.column_stack((message, url)))


def _positive_scores(model, rows):
    classes = list(model.classes_)
    if "1" not in classes:
        raise ValueError("branch lacks phishing class")
    return model.predict_proba(rows)[:, classes.index("1")]


class BranchModel:
    def __init__(self, kind, parser, config):
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sentinel.url_ml.features import LexicalTransformer

        self.kind, self.parser, self.config = kind, parser, dict(config)
        self.vectorizer = None
        self.transformer = None
        self.scaler = None
        if kind == "message":
            self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=30000,
                                               dtype=__import__("numpy").float32)
            self.classifier = LogisticRegression(C=config["C"], solver="liblinear",
                                                 max_iter=1000, random_state=42)
        elif kind == "url":
            self.transformer = LexicalTransformer(parser)
            self.classifier = HistGradientBoostingClassifier(
                max_depth=config["max_depth"], max_iter=150, early_stopping=False,
                random_state=42,
            )
        elif kind == "early":
            self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=30000,
                                               dtype=__import__("numpy").float32)
            self.transformer = LexicalTransformer(parser)
            from sklearn.preprocessing import StandardScaler
            self.scaler = StandardScaler(with_mean=False)
            self.classifier = LogisticRegression(C=config["C"], solver="liblinear",
                                                 max_iter=1000, random_state=42)
        else:
            raise ValueError("unsupported branch kind")

    def _matrix(self, rows, *, fit):
        from scipy.sparse import csr_matrix, hstack
        from .features import paired_inputs

        inputs = paired_inputs(self.kind, rows, self.parser)
        if self.kind == "url":
            return self.transformer.transform(inputs[0])
        texts = inputs[0]
        text_matrix = self.vectorizer.fit_transform(texts) if fit else self.vectorizer.transform(texts)
        if self.kind == "message":
            return text_matrix
        lexical = self.transformer.transform(inputs[1])
        lexical = self.scaler.fit_transform(lexical) if fit else self.scaler.transform(lexical)
        return hstack((text_matrix, csr_matrix(lexical)), format="csr")

    def fit(self, rows):
        from threadpoolctl import threadpool_limits
        labels = [row["label"] for row in rows]
        if set(labels) != {"0", "1"}:
            raise ValueError("branch training requires both classes")
        with threadpool_limits(limits=MAX_NATIVE_THREADS):
            self.classifier.fit(self._matrix(rows, fit=True), labels)
        return self

    def predict_proba(self, rows):
        from threadpoolctl import threadpool_limits
        with threadpool_limits(limits=MAX_NATIVE_THREADS):
            return self.classifier.predict_proba(self._matrix(rows, fit=False))

    @property
    def classes_(self):
        return self.classifier.classes_


def build_branch(kind: str, parser, config: dict) -> object:
    from .protocol import _parser_checked
    _parser_checked(parser)
    config = dict(config)
    if kind in {"message", "early"} and config.get("C") not in {0.5, 1.0}:
        raise ValueError("linear C must be 0.5 or 1.0")
    if kind == "url" and config.get("max_depth") not in {3, 5}:
        raise ValueError("URL max_depth must be 3 or 5")
    return BranchModel(kind, parser, config)


def _fit_worker(connection, rows, kind, params, suffix_path):
    import psutil
    from sentinel.url_ml.urls import UrlParser

    started = time.perf_counter()
    try:
        parser = UrlParser(Path(suffix_path))
        model = build_branch(kind, parser, params).fit(rows)
        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None) or getattr(info, "peak_rss", None) or info.rss
        connection.send((model, {"status": "ok", "fit_seconds": time.perf_counter() - started,
                                 "worker_peak_bytes": int(peak)}))
    except Exception as error:
        connection.send((None, {"status": "fit_failed", "error_type": type(error).__name__}))
    finally:
        connection.close()


def _fit_monitored(rows, kind, params, parser, *, max_peak_bytes=MAX_PEAK_BYTES):
    import psutil

    budget = min(int(max_peak_bytes), MAX_PEAK_BYTES)
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_fit_worker, args=(sender, rows, kind, params, str(parser.psl_path)))
    keys = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        for key in keys:
            os.environ[key] = str(MAX_NATIVE_THREADS)
        process.start()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    sender.close()
    peak = 0
    started = time.perf_counter()
    result, record = None, {"status": "worker_exited"}
    try:
        while True:
            try:
                worker = psutil.Process(process.pid)
                members = [worker, *worker.children(recursive=True)]
                observed = sum(member.memory_info().rss for member in members)
                peak = max(peak, observed)
            except psutil.NoSuchProcess:
                pass
            if peak > budget:
                record = {"status": "memory_budget_exceeded"}
                break
            if receiver.poll(.05):
                try:
                    result, record = receiver.recv()
                except EOFError:
                    record = {"status": "worker_exited"}
                break
            if not process.is_alive():
                record = {"status": "worker_exited", "exit_code": process.exitcode}
                break
            if time.perf_counter() - started > 600:
                record = {"status": "fit_timeout"}
                break
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join()
        receiver.close()
    record.update({"peak_bytes": max(peak, record.get("worker_peak_bytes", 0)),
                   "max_peak_bytes": budget, "native_threads": MAX_NATIVE_THREADS,
                   "train_rows": len(rows),
                   "train_ids_sha256": hashlib.sha256("\0".join(sorted(row["case_id"] for row in rows)).encode()).hexdigest()})
    if record["peak_bytes"] > budget:
        record["status"] = "memory_budget_exceeded"
        result = None
    return result, record


def fit_branch_candidates(train: list[dict], parser, config: dict) -> dict[str, tuple[BranchCandidate, ...]]:
    from .features import paired_inputs
    from .protocol import _parser_checked

    _parser_checked(parser)
    paired_inputs("early", train, parser)
    if {row["label"] for row in train} != {"0", "1"}:
        raise ValueError("branch training requires both classes")
    output = {"message": [], "url": [], "combined": []}
    grid = [("message", {"C": c}) for c in (.5, 1.0)]
    grid += [("url", {"max_depth": d}) for d in (3, 5)]
    grid += [("early", {"C": c}) for c in (.5, 1.0)]
    for kind, params in grid:
        model, record = _fit_monitored(train, kind, params, parser,
                                       max_peak_bytes=config.get("max_peak_bytes", MAX_PEAK_BYTES))
        if model is None or record["status"] != "ok":
            raise ValueError("paired branch fit unavailable: " + record["status"])
        config_id = f"{kind}-" + "-".join(f"{key}{value}" for key, value in sorted(params.items()))
        key = "combined" if kind == "early" else kind
        output[key].append(BranchCandidate(kind, config_id, model, record))
    try:
        output["combined"].append(fit_late_fusion(train, parser, config))
    except LateFusionUnavailable:
        for candidate in output["combined"]:
            candidate.fit_record["late_fusion_status"] = "late_fusion_unavailable"
    return {key: tuple(value) for key, value in output.items()}


def fit_late_fusion(train: list[dict], parser, config: dict, *, folds: int = 5) -> BranchCandidate:
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedGroupKFold
    from threadpoolctl import threadpool_limits
    from .protocol import connected_groups

    if folds != 5:
        raise LateFusionUnavailable("late_fusion_unavailable: fixed protocol uses five folds")
    groups = connected_groups(train, parser)
    if len(set(groups.values())) < folds:
        raise LateFusionUnavailable("late_fusion_unavailable: too few connected groups")
    labels = [row["label"] for row in train]
    if any(labels.count(label) < folds for label in ("0", "1")):
        raise LateFusionUnavailable("late_fusion_unavailable: class-sparse fold")
    splitter = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=42)
    try:
        splits = [(list(inside), list(outside)) for inside, outside in
                  splitter.split(np.zeros(len(train)), labels, [groups[row["case_id"]] for row in train])]
    except ValueError as error:
        raise LateFusionUnavailable("late_fusion_unavailable: fold allocation failed") from error
    for inside, outside in splits:
        if {labels[i] for i in inside} != {"0", "1"} or {labels[i] for i in outside} != {"0", "1"}:
            raise LateFusionUnavailable("late_fusion_unavailable: class-sparse fold")
    oof = np.full((len(train), 2), np.nan, dtype=float)
    fold_records = []
    all_fit_records = []
    for fold_id, (inside, outside) in enumerate(splits):
        training = [train[i] for i in inside]
        heldout = [train[i] for i in outside]
        trained_groups = {groups[row["case_id"]] for row in training}
        heldout_groups = {groups[row["case_id"]] for row in heldout}
        if trained_groups & heldout_groups:
            raise LateFusionUnavailable("late_fusion_unavailable: connected group crossed fold")
        fitted = []
        for kind, params in (("message", {"C": 1.0}), ("url", {"max_depth": 3})):
            model, record = _fit_monitored(training, kind, params, parser,
                                            max_peak_bytes=config.get("max_peak_bytes", MAX_PEAK_BYTES))
            if model is None or record["status"] != "ok":
                raise LateFusionUnavailable("late_fusion_unavailable: fold branch fit failed")
            fitted.append(model)
            all_fit_records.append(record)
        for column, model in enumerate(fitted):
            oof[outside, column] = _positive_scores(model, heldout)
        fold_records.append({
            "fold": fold_id, "train_groups": len(trained_groups), "holdout_groups": len(heldout_groups),
            "train_classes": dict(__import__("collections").Counter(labels[i] for i in inside)),
            "holdout_classes": dict(__import__("collections").Counter(labels[i] for i in outside)),
            "train_ids_sha256": hashlib.sha256("\0".join(sorted(train[i]["case_id"] for i in inside)).encode()).hexdigest(),
            "holdout_ids_sha256": hashlib.sha256("\0".join(sorted(train[i]["case_id"] for i in outside)).encode()).hexdigest(),
        })
    if not np.all(np.isfinite(oof)):
        raise LateFusionUnavailable("late_fusion_unavailable: incomplete held-out scores")
    with threadpool_limits(limits=MAX_NATIVE_THREADS):
        classifier = LogisticRegression(C=1.0, solver="liblinear", max_iter=1000, random_state=42)
        classifier.fit(oof, labels)
    final_models = []
    final_records = []
    for kind, params in (("message", {"C": 1.0}), ("url", {"max_depth": 3})):
        model, record = _fit_monitored(train, kind, params, parser,
                                        max_peak_bytes=config.get("max_peak_bytes", MAX_PEAK_BYTES))
        if model is None or record["status"] != "ok":
            raise LateFusionUnavailable("late_fusion_unavailable: final branch fit failed")
        final_models.append(model)
        final_records.append(record)
        all_fit_records.append(record)
    fit_record = {
        "status": "ok", "folds": fold_records, "out_of_fold_rows": len(train),
        "train_rows": len(train), "train_groups": len(set(groups.values())),
        "train_ids_sha256": hashlib.sha256("\0".join(sorted(groups)).encode()).hexdigest(),
        "peak_bytes": max(record.get("peak_bytes", 0) for record in all_fit_records),
        "native_threads": MAX_NATIVE_THREADS,
    }
    return BranchCandidate("late", "late-logistic-oof5",
                           LateFusionModel(parser, final_models[0], final_models[1], classifier), fit_record)


def score_candidate(candidate: BranchCandidate, rows: list[dict]) -> list[float]:
    import numpy as np
    from .features import paired_inputs

    kind = "early" if candidate.kind == "late" else candidate.kind
    paired_inputs(kind, rows, candidate.model.parser)
    probabilities = candidate.model.predict_proba(rows)
    classes = list(candidate.model.classes_)
    if "1" not in classes:
        raise ValueError("candidate lacks phishing class")
    scores = np.asarray(probabilities[:, classes.index("1")], dtype=float)
    if not np.all(np.isfinite(scores)) or np.any((scores < 0) | (scores > 1)):
        raise ValueError("candidate produced invalid scores")
    return scores.tolist()
