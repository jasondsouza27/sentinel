"""Runtime wrapper for the trained profile-metadata bot classifier.

The model is kept separate from the heuristic and replaceable. It only produces a
live estimate when its manifest says it passed the release gate; a research-only
model reports why it is withheld (its estimate is exposed only when research mode
is switched on explicitly). Files are checksum-verified before loading.
"""

import bisect
import hashlib
import json
from pathlib import Path

from .features import (ACTIVITY_FEATURES, FEATURES, MIN_POSTS, REQUIRED, account_features, activity_vector,
                       vector)

SCHEMA = "sentinel.bot_ml.artifact/1"


class BotProfileModel:
    def __init__(self, artifact_dir, research_mode=False):
        self.error, self.model, self.manifest, self.research_mode, self.kind = None, None, None, research_mode, "profile"
        try:
            directory = Path(artifact_dir)
            self.manifest = json.loads((directory / "manifest.json").read_text())
            self.kind = self.manifest.get("kind", "profile")
            expected = ACTIVITY_FEATURES + FEATURES if self.kind == "activity" else FEATURES
            if self.manifest.get("schema") != SCHEMA or self.manifest.get("features") != expected:
                raise ValueError("unsupported_artifact")
            for name, digest in self.manifest["files"].items():
                if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
                    raise ValueError("artifact_checksum_mismatch")
            calibration = json.loads((directory / "calibration.json").read_text())
            self.cal_x, self.cal_y = calibration["x"], calibration["y"]
            import joblib  # only after the checksums matched
            self.model = joblib.load(directory / "model.joblib")
        except ImportError:
            self.error = "runtime_not_installed"
        except FileNotFoundError:
            self.error = "artifact_not_found"
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self.error = str(error) if str(error) in ("unsupported_artifact", "artifact_checksum_mismatch") else "artifact_invalid"

    @property
    def released(self):
        return self.model is not None and self.manifest.get("release") == "released"

    def _calibrated(self, raw):
        xs, ys = self.cal_x, self.cal_y
        if raw <= xs[0]:
            return ys[0]
        if raw >= xs[-1]:
            return ys[-1]
        i = bisect.bisect_right(xs, raw)
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return y0 + (y1 - y0) * (raw - x0) / (x1 - x0) if x1 > x0 else y1

    def assess(self, platform, account, posts=None):
        """account: followers, following, posts, age_days, bio, username, display_name, has_url.
        posts: Post objects (used by activity models only)."""
        kind = (self.manifest or {}).get("kind", "profile")
        base = {"model_version": (self.manifest or {}).get("model_version"),
                "kind": "activity_classifier" if kind == "activity" else "profile_metadata_classifier"}
        if self.model is None:
            return {**base, "state": "unavailable", "reason": self.error}
        gate = self.manifest.get("release_gate", {})
        worst = gate.get("worst_lodo_auc", gate.get("worst_fold_auc"))
        needed = gate.get("min_lodo_auc_each_dataset", gate.get("min_auc_every_fold"))
        validation = f"Cross-dataset validation: worst held-out AUC {worst} (release needs ≥ {needed})."
        if platform not in self.manifest.get("platforms", []):
            return {**base, "state": "not_applicable", "reason": "Trained on Twitter/X accounts only.", "validation": validation}
        if kind == "activity":
            if not posts or len(posts) < MIN_POSTS:
                return {**base, "state": "insufficient_data", "validation": validation,
                        "reason": f"Needs at least {MIN_POSTS} timed posts."}
            features = activity_vector(account_features(posts), account)
        else:
            features = vector(account)
        if features is None:
            missing = [k for k in REQUIRED if account.get(k) is None]
            return {**base, "state": "insufficient_data", "reason": "Needs " + ", ".join(missing) + ".", "validation": validation}
        if not self.released and not self.research_mode:
            return {**base, "state": "research_only", "validation": validation,
                    "reason": "Failed cross-dataset validation, so its estimate is withheld and not used in the classification."}
        raw = float(self.model.predict_proba([features])[0][1])
        return {**base, "state": "released" if self.released else "research_only", "validation": validation,
                "bot_probability": round(self._calibrated(raw), 3),
                "note": (f"Calibrated on held-out data. Trained on "
                         f"{self.manifest.get('trained_on', 'Twitter bot datasets')}; "
                         "lower reliability on other populations.") + ("" if self.released else
                         " Research mode: shown for study only, not used in the classification.")}
