"""Batch rule checks for page content read by the opt-in auto-scan extension.

Auto-scan sends many short, visible page fragments. Each one gets the same
cautious evidence rules as /api/analyze, plus a check for link text that names a
different site than the link opens. When the experimental text model is
loaded it scores the batch in one pass and explains only flagged items. Other
optional models are not run here. Nothing is stored.
"""

import re

from .analysis import _host, _string, analyze

MAX_SCAN_ITEMS = 40
MAX_ITEM_TEXT = 4000
MAX_LINK_TEXT = 500
MAX_EXPLAINED = 5
DOMAIN_IN_TEXT = re.compile(r"(?:https?://)?((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})\b",
                            re.IGNORECASE)
HIGH_ACTION = ("Avoid entering credentials or paying through this link; "
               "verify the sender through an official channel.")
MODEL_UNCERTAINTY = ("Auto-scan combines evidence rules with an experimental text model trained on "
                     "English SMS. A missing marker does not show content is safe, and a marker "
                     "does not prove fraud or abuse.")
UNCERTAINTY = ("Auto-scan uses evidence rules only. A missing marker does not show that content "
               "is safe, and a marker does not prove fraud or abuse.")


def _bare(host):
    host = (host or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def link_text_mismatch(link_text, url):
    """Return evidence when visible link text names a different site than the link opens."""
    match = DOMAIN_IN_TEXT.search(link_text or "")
    actual = _bare(_host(url))
    if not match or not actual:
        return None
    shown = _bare(match.group(1))
    if "." not in shown or shown == actual or actual.endswith("." + shown) or shown.endswith("." + actual):
        return None
    return f"The link text shows {shown} but the link opens {actual}."


def _model_results(text_model, texts):
    """Batch learned predictions; None for every item when the model is absent or fails."""
    if text_model is None or not getattr(text_model, "available", False):
        return [None] * len(texts)
    wanted = [i for i, text in enumerate(texts) if text]
    results = [None] * len(texts)
    try:
        for i, prediction in zip(wanted, text_model.predict([texts[i] for i in wanted])):
            results[i] = prediction
        # Explanations cost one model pass per word: bound them per batch.
        for i in [i for i in wanted if results[i]["flagged"]][:MAX_EXPLAINED]:
            results[i]["explanation"] = text_model.explain(texts[i], top=4)
    except Exception:
        return [None] * len(texts)
    return results


def _community(network, text, severity, model_flag, fraud, prediction, evidence):
    """Match against the community campaign feed and, if Sentinel itself flagged the
    message with high confidence, share its fingerprint (never its text)."""
    if network is None or not text:
        return None
    try:
        match = network.match(text)
        if model_flag and prediction["scam_probability"] >= 0.9:
            network.report(text, prediction["category"], prediction["scam_probability"])
        elif fraud["level"] == "high":
            network.report(text, "rules", 0.9)
    except Exception:
        return None
    if match:
        topics = ", ".join(match["topics"][:3])
        evidence.insert(0, f"Matches an active scam campaign reported by {match['reporters']} Sentinel users"
                           + (f" (about: {topics})." if topics else "."))
    return match


def scan(payload, known_phishing=None, text_model=None, network=None):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("Supply an items list")
    items = payload["items"]
    if not items:
        raise ValueError("Supply at least one item")
    if len(items) > MAX_SCAN_ITEMS:
        raise ValueError(f"Scan at most {MAX_SCAN_ITEMS} items per request")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each item must be an object")
    texts = [_string(item.get("text"), MAX_ITEM_TEXT) for item in items]
    learned = _model_results(text_model, texts)
    results = []
    for item, prediction in zip(items, learned):
        item_id = _string(item.get("id"), 64)
        if not item_id:
            raise ValueError("Each item needs an id")
        text = _string(item.get("text"), MAX_ITEM_TEXT)
        url = _string(item.get("url"), 2048)
        link_text = _string(item.get("link_text"), MAX_LINK_TEXT)
        if not (text or url):
            raise ValueError("Each item needs text or a url")
        assessment = analyze({"message": text, "url": url}, known_phishing)
        fraud, harm = assessment["fraud"], assessment["harmful_content"]
        evidence = list(fraud["evidence"]) + list(harm["evidence"])
        mismatch = link_text_mismatch(link_text, fraud["analyzed_url"] or url) if link_text else None
        if mismatch:
            evidence.insert(0, mismatch)
        # The text model was trained on SMS. On email and web pages it rates ordinary notices
        # ("Dear Customer... your account", "Amazon Web Services") as phishing, so while scanning it
        # only counts when something independent backs it up: a link, a rule hit or a link mismatch.
        model_says = bool(prediction and prediction["flagged"])
        corroborated = bool(fraud["evidence"] or fraud["analyzed_url"] or mismatch)
        model_flag = model_says and corroborated
        if prediction is not None:
            prediction["counted"] = model_flag
            if model_says and not corroborated:
                prediction["not_counted_reason"] = "No link, request or other warning sign backs up the model."
        if model_flag:
            words = ", ".join(repr(c["word"]) for c in prediction.get("explanation", [])[:3])
            kind = "phishing (smishing)" if prediction["category"] == "smishing" else "spam"
            evidence.insert(0, f"The learned text model rates this as likely {kind} "
                               f"({prediction['scam_probability']:.0%} calibrated)" + (f"; key words: {words}." if words else "."))
        if (fraud["level"] == "high" or harm["level"] == "high" or (mismatch and len(fraud["evidence"]) >= 1)
                or (model_flag and (fraud["evidence"] or mismatch or prediction["scam_probability"] >= 0.9))):
            severity = "high"
        elif model_flag or mismatch or harm["level"] == "review" or len(fraud["evidence"]) >= 2:
            severity = "review"
        else:
            # A single weak indicator, such as one urgent word, is too common in
            # ordinary pages to mark while scanning automatically.
            severity = "none"
        community = _community(network, text, severity, model_flag, fraud, prediction, evidence)
        if community and severity == "none":
            severity = "review"
        elif community and (model_flag or fraud["evidence"] or mismatch):
            severity = "high"
        action = (harm["action"] if harm["level"] in ("high", "review") and fraud["level"] != "high" and not model_flag
                  else HIGH_ACTION if severity == "high"
                  else harm["action"] if harm["level"] == "review"
                  else "Verify unexpected requests through an official channel before acting.")
        results.append({"id": item_id, "severity": severity, "fraud_level": fraud["level"],
                        "harm_level": harm["level"], "evidence": evidence,
                        "model": prediction, "community": community,
                        "action": action if severity != "none" else None})
    method = "evidence rules + learned text model" if any(learned) else "evidence rules"
    return {"method": method, "uncertainty": UNCERTAINTY if method == "evidence rules" else MODEL_UNCERTAINTY,
            "results": results}
