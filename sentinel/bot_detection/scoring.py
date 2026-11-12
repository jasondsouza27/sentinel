"""Configurable weighted heuristic scoring (replaceable by a trained model).

score = 100 * sum(weight * suspicion) / sum(weight) over *available* signals only.
coverage = share of total signal weight that had data. Confidence reflects
coverage and the number of posts analysed, never the score itself. The score
is a heuristic bot-likeness index, not a calibrated probability.
"""

import json
from pathlib import Path

WEIGHTS = Path(__file__).with_name("weights.json")


def load_config(path=WEIGHTS):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    for signal in config["signals"]:
        if signal["direction"] not in ("high", "low", "human_only") or signal["weight"] <= 0:
            raise ValueError(f"Invalid signal configuration: {signal['id']}")
    return config


def _suspicion(signal, value):
    if signal["direction"] == "human_only":
        return 0.0 if value else None  # only ever counts in the account's favour
    start, end = signal["ramp"]
    if start == end:
        return 1.0 if value >= end else 0.0
    return min(max((value - start) / (end - start), 0.0), 1.0)


def _text(template, value):
    if not template:
        return None
    shown = f"{value:g}" if isinstance(value, float) else str(value)
    return template.format(value=shown, pct=f"{value * 100:.0f}%" if isinstance(value, (int, float)) else shown)


class HeuristicScorer:
    """Interface shared with any future ML scorer: score(features, data) -> dict."""

    kind = "weighted_heuristic"

    def __init__(self, config=None):
        self.config = config or load_config()

    def score(self, features, posts_analysed):
        # coverage counts only signals that can raise suspicion; the score's denominator also
        # includes "human_only" signals (e.g. verified), which can only lower the score.
        signals, total_weight, coverage_weight, score_weight, weighted = [], 0.0, 0.0, 0.0, 0.0
        for spec in self.config["signals"]:
            weight = float(spec["weight"])
            total_weight += 0 if spec["direction"] == "human_only" else weight
            value = features.get(spec["feature"])
            reason = None
            if value is None:
                reason = "data not available"
            elif spec.get("min_posts") and posts_analysed < spec["min_posts"]:
                reason = f"needs at least {spec['min_posts']} posts"
            elif any((features.get(k) or 0) < v for k, v in spec.get("requires", {}).items()):
                reason = "not applicable at this account size"
            suspicion = None if reason else _suspicion(spec, value)
            if suspicion is None and reason is None:
                reason = "not applicable"
            entry = {"id": spec["id"], "category": spec["category"], "feature": spec["feature"],
                     "value": value, "weight": weight, "suspicion": None if suspicion is None else round(suspicion, 3),
                     "coordination": bool(spec.get("coordination"))}
            if suspicion is None:
                entry.update(state="unavailable", reason=reason)
            else:
                coverage_weight += 0 if spec["direction"] == "human_only" else weight
                score_weight += weight
                weighted += weight * suspicion
                state = "suspicious" if suspicion >= 0.5 else "human_like" if suspicion <= 0.15 else "neutral"
                text = _text(spec["human"], value) if state == "human_like" else _text(spec["bot"], value)
                entry.update(state=state, text=text)
            signals.append(entry)
        denominator = score_weight
        score = round(100 * weighted / denominator) if coverage_weight else None
        for s in signals:
            s["contribution"] = round(100 * s["weight"] * s["suspicion"] / denominator, 1) if s["suspicion"] and denominator else 0.0
        coverage = round(coverage_weight / total_weight, 3) if total_weight else 0.0
        available = [s for s in signals if s["state"] != "unavailable"]
        coordination = self._coordination(signals)
        classified = self._classify(score, coverage, len(available), coordination)
        insufficient = classified["classification"]["id"] == "insufficient_data"
        return {
            "model": {"type": self.kind, "version": self.config["version"]},
            # With insufficient data the score is withheld from the headline and kept only as indicative.
            "score": None if insufficient else score,
            "indicative_score": score if insufficient else None,
            "score_label": "Bot-likeness score (heuristic index 0-100, not a calibrated probability)",
            "coverage": coverage,
            "coordination_score": coordination,
            "coordination_flag": bool(coordination is not None and coordination >= self.config["classification"]["coordination_from"]),
            "confidence": self._confidence(coverage, posts_analysed, len(available)),
            **classified,
            "signals": sorted(signals, key=lambda s: (-s["contribution"], s["state"] == "unavailable")),
        }

    def _coordination(self, signals):
        parts = [(s["weight"], s["suspicion"]) for s in signals if s["coordination"] and s["suspicion"] is not None]
        if len(parts) < 2:
            return None
        return round(100 * sum(w * x for w, x in parts) / sum(w for w, _ in parts))

    def _confidence(self, coverage, posts, available):
        rules = self.config["confidence"]
        if coverage < rules["insufficient"]["coverage"] or available < rules["insufficient"]["signals"]:
            level, why = "Very low", "Too few signals had data to support a classification."
        elif coverage >= rules["high"]["coverage"] and posts >= rules["high"]["posts"]:
            level, why = "High", "Most signals had data and enough posts were analysed."
        elif coverage >= rules["medium"]["coverage"] and posts >= rules["medium"]["posts"]:
            level, why = "Medium", "A moderate share of signals had data."
        else:
            level, why = "Low", "Many signals lacked data or too few posts were available."
        return {"level": level, "reason": why, "signal_coverage": f"{coverage * 100:.0f}% of signal weight had data",
                "posts_analysed": posts}

    def _classify(self, score, coverage, available, coordination):
        c, rules = self.config["classification"], self.config["confidence"]["insufficient"]
        if score is None or coverage < rules["coverage"] or available < rules["signals"]:
            return {"classification": {"id": "insufficient_data", "label": "Insufficient data"},
                    "risk_level": "Unknown"}
        risk = next(label for limit, label in self.config["risk"] if score < limit)
        if score >= c["automated_from"]:
            label = ("likely_automated", "Likely bot or automated account")
        elif coordination is not None and coordination >= c["coordination_from"] and score >= c["coordination_min_score"]:
            label = ("suspicious_or_coordinated", "Suspicious: possibly coordinated activity")
        elif score < c["human_below"]:
            label = ("likely_human", "Likely human-operated")
        else:
            label = ("suspicious", "Suspicious: mixed or unusual patterns")
        return {"classification": {"id": label[0], "label": label[1]}, "risk_level": risk}
