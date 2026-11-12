"""Checked loading, inference and word-level explanations for the text model.

Needs onnxruntime, tokenizers and numpy (the `.venv-text-ml` environment). When
they or the artifact are missing, the service reports itself unavailable and
the app keeps working with rules only.
"""

import hashlib
import math
import json
import re
from pathlib import Path

from . import LABELS

SCHEMA = "sentinel.text_ml.artifact/1"
MAX_EXPLAIN_WORDS = 60
WORD = re.compile(r"\S+")
LIMITS = ("A learned model trained on English SMS (Mendeley/UCI corpora, 2011-2022). "
          "Other platforms, languages and newer scam styles can be missed or misjudged; "
          "the probability is calibrated only on that distribution.")
LIMITS_BY_VERSION = {
    "text-ml-v2": ("A learned model trained on English SMS (2011-2022) plus synthetic English and Hinglish "
                   "Indian messages. It has not been validated on real recent Indian SMS at scale; other "
                   "languages and new scam styles can be missed, and the probability is calibrated only "
                   "on its training distribution."),
}


class OnnxBackend:
    def __init__(self, model_path, tokenizer_path, max_length):
        import numpy as np
        import onnxruntime
        from tokenizers import Tokenizer
        self.np = np
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 4
        self.session = onnxruntime.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.tokenizer.enable_truncation(max_length)
        self.tokenizer.enable_padding()

    def logits(self, texts, batch=64):
        np = self.np
        out = []
        for start in range(0, len(texts), batch):
            encoded = self.tokenizer.encode_batch(list(texts[start:start + batch]))
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            out.append(self.session.run(["logits"], {"input_ids": ids, "attention_mask": mask})[0])
        return np.concatenate(out)


def _softmax(row, temperature):
    import math
    scaled = [v / temperature for v in row]
    top = max(scaled)
    exps = [math.exp(v - top) for v in scaled]
    total = sum(exps)
    return [e / total for e in exps]


class TextModelService:
    """Wraps a backend with calibration, the decision threshold and explanations."""

    def __init__(self, artifact_dir=None, backend=None, manifest=None):
        self.error = None
        self.lexical = None
        self.ensemble = None
        self.manifest = manifest
        self.backend = backend
        if backend is not None:
            return
        try:
            directory = Path(artifact_dir)
            self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if self.manifest.get("schema") != SCHEMA or list(self.manifest.get("labels", [])) != list(LABELS):
                raise ValueError("unsupported_artifact")
            for name, digest in self.manifest["files"].items():
                if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
                    raise ValueError("artifact_checksum_mismatch")
            self.backend = OnnxBackend(directory / "model.onnx", directory / "tokenizer.json", self.manifest["max_length"])
            ensemble = self.manifest.get("ensemble")
            if ensemble:
                # Loaded only after every listed file passed its checksum above.
                import joblib
                self.lexical = joblib.load(directory / "lexical.joblib")
                self.ensemble = ensemble["method"]
        except ImportError:
            self.error = "runtime_not_installed"
        except FileNotFoundError:
            self.error = "artifact_not_found"
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self.error = str(error) if str(error) in ("unsupported_artifact", "artifact_checksum_mismatch") else "artifact_invalid"

    @property
    def available(self):
        return self.backend is not None and self.error is None

    def health(self):
        if not self.available:
            return {"state": "unavailable", "reason": self.error, "model_version": None}
        return {"state": "ready", "model_version": self.manifest["model_version"],
                "ensemble": self.ensemble or "transformer",
                "release": self.manifest.get("release", "experimental")}

    def _scores(self, texts):
        temperature = self.manifest["temperature"]
        rows = [_softmax(list(map(float, row)), temperature) for row in self.backend.logits(texts)]
        if self.lexical is not None:
            lexical = self.lexical.predict_proba(list(texts))
            if self.ensemble == "average":
                rows = [[(a + float(b)) / 2 for a, b in zip(row, lex)] for row, lex in zip(rows, lexical)]
            else:
                rows = [[float(b) for b in lex] for lex in lexical]
        return [dict(zip(LABELS, row)) for row in rows]

    def predict(self, texts):
        """Calibrated probabilities and the scam decision for many texts (used by auto-scan)."""
        threshold = self.manifest["scam_threshold"]
        results = []
        for probabilities in self._scores(texts):
            scam = probabilities["spam"] + probabilities["smishing"]
            flagged = scam >= threshold
            category = ("smishing" if probabilities["smishing"] >= probabilities["spam"] else "spam") if flagged else "ham"
            results.append({"category": category, "scam_probability": round(scam, 4), "flagged": flagged,
                            "probabilities": {k: round(v, 4) for k, v in probabilities.items()}})
        return results

    def explain(self, text, top=6):
        """Words whose removal lowers the scam log-odds the most (leave-one-word-out).

        Log-odds are used instead of probability because a confident prediction
        (for example 0.99) barely moves in probability when one of several
        warning words is removed, which would hide all but the strongest word.
        """
        words = [(m.group(0), m.start(), m.end()) for m in WORD.finditer(text)][:MAX_EXPLAIN_WORDS]
        if not words:
            return []
        variants = [text[:start] + text[end:] for _, start, end in words]
        scores = self._scores([text] + variants)
        def log_odds(score):
            p = min(max(score["spam"] + score["smishing"], 1e-6), 1 - 1e-6)
            return math.log(p / (1 - p))
        base = log_odds(scores[0])
        contributions = []
        for (word, start, end), score in zip(words, scores[1:]):
            delta = base - log_odds(score)
            if delta > 0.05:
                contributions.append({"word": word, "start": start, "end": end, "weight": round(delta, 4)})
        contributions.sort(key=lambda item: item["weight"], reverse=True)
        return contributions[:top]

    def assess(self, text):
        if not self.available:
            return {"state": "unavailable", "reason": self.error, "model_version": None}
        if not text.strip():
            return {"state": "not_assessed", "reason": "no_message_text",
                    "model_version": self.manifest["model_version"]}
        result = self.predict([text])[0]
        explanation = self.explain(text) if result["flagged"] else []
        names = {"ham": "no learned scam signal", "spam": "likely spam", "smishing": "likely phishing (smishing)"}
        evidence = ([f"Words that most raised the learned scam score: {', '.join(repr(c['word']) for c in explanation[:4])}."]
                    if explanation else [])
        return {
            "state": "available",
            "model_version": self.manifest["model_version"],
            "release": self.manifest.get("release", "experimental"),
            "category": result["category"],
            "label": names[result["category"]],
            "flagged": result["flagged"],
            "calibrated_probability": result["scam_probability"],
            "probabilities": result["probabilities"],
            "threshold": self.manifest["scam_threshold"],
            "explanation": explanation,
            "evidence": evidence,
            "uncertainty": LIMITS_BY_VERSION.get(self.manifest["model_version"], LIMITS),
            "action": ("Do not reply, pay or open links until you verify the sender through an official channel."
                       if result["flagged"] else "No learned scam signal; still verify unexpected requests."),
        }
