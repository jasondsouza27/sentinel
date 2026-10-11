"""Optional live boundary: schema-1 research artifacts never issue ML warnings."""

from pathlib import Path
from urllib.parse import urlsplit


def unavailable(reason, check=None):
    return {
        "state": "unavailable", "category": "not_assessed", "evidence": [],
        "uncertainty": "The paired model has not produced a usable live assessment.",
        "unavailable_checks": [check or reason.replace("_", " ")],
        "action": "Verify unexpected requests through the sender's official channel.",
        "model_version": None,
    }


class PairedService:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._bundle = None
        self._metadata = None

    def health(self) -> dict:
        try:
            from . import artifacts
            metadata = artifacts.inspect_study_artifact(self.path)
            if metadata["release_status"] != "approved":
                return {"state": "unavailable", "reason": "research_only_artifact"}
            if self._bundle is None:
                self._bundle = artifacts.load_study_artifact(self.path)
                self._metadata = metadata
            return {"state": "available", "model_version": metadata["protocol_sha256"][:12]}
        except (ValueError, FileNotFoundError, OSError, ImportError, KeyError, AttributeError):
            return {"state": "unavailable", "reason": "artifact_unavailable"}

    def assess(self, message: str, url: str) -> dict:
        if not message or not message.strip():
            return unavailable("missing_message", "A message is required for paired analysis.")
        if not url or not url.strip():
            return unavailable("missing_url", "A URL is required for paired analysis.")
        try:
            parts = urlsplit(url)
            _ = parts.port
            if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
                return unavailable("malformed_url", "The supplied URL is malformed or unsupported.")
        except ValueError:
            return unavailable("malformed_url", "The supplied URL is malformed or unsupported.")
        health = self.health()
        if health["state"] != "available":
            if health["reason"] == "research_only_artifact":
                return unavailable("research_only_artifact",
                                   "The paired model is research-only and has not been approved for live warnings.")
            return unavailable("artifact_unavailable", "The paired model artifact or ML dependency is unavailable.")
        try:
            from sentinel.analysis import PAYMENT_RE, SECRET_RE, URGENCY_RE, _url_indicators
            from .models import score_candidate

            selection = self._bundle.selections["combined"]
            if selection.raw_threshold is None:
                return unavailable("decision_threshold_unavailable",
                                   "A supported paired decision threshold is unavailable.")
            score = score_candidate(selection.candidate, [{"case_id": "live", "message": message, "url": url}])[0]
            category = "review" if score >= selection.raw_threshold else "not_flagged"
            evidence = []
            if PAYMENT_RE.search(message):
                evidence.append("The submitted message asks for payment or a fee.")
            if SECRET_RE.search(message):
                evidence.append("The submitted message asks for a password or verification code.")
            if URGENCY_RE.search(message):
                evidence.append("The submitted message uses urgent wording.")
            evidence.extend(_url_indicators(url))
            return {
                "state": "available", "category": category, "evidence": evidence,
                "uncertainty": "A learned result cannot establish that a request is genuine or fraudulent.",
                "unavailable_checks": [],
                "action": "Verify the request through the sender's official channel before acting.",
                "model_version": self._metadata["protocol_sha256"][:12],
            }
        except (ValueError, KeyError, IndexError, ImportError, AttributeError, OSError):
            return unavailable("inference_unavailable", "The paired model could not assess this input.")
