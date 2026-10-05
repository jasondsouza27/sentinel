"""Cautious, explainable assessments. Rules are indicators, not trained models."""

import ipaddress
import re
from urllib.parse import urlsplit


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
PAYMENT_RE = re.compile(r"\b(pay|payment|registration fee|processing fee|send money|upi)\b", re.IGNORECASE)
SECRET_RE = re.compile(r"\b(password|one.time password|otp|verification code|login details)\b", re.IGNORECASE)
URGENCY_RE = re.compile(r"\b(act now|immediately|urgent|within \d+ (?:minute|hour)|limited time)\b", re.IGNORECASE)
ABUSE_RE = re.compile(r"\b(you are (?:stupid|an idiot|worthless)|kill yourself|i will hurt you)\b", re.IGNORECASE)


def _string(value, limit):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Text and URL fields must be strings")
    if len(value) > limit:
        raise ValueError(f"Input exceeds {limit} characters")
    return value.strip()


def _host(url):
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def _url_indicators(url):
    evidence = []
    if not url:
        return evidence
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return ["The supplied URL could not be parsed; verify it manually."]
    if parts.scheme not in ("http", "https") or not host:
        return ["The supplied URL is incomplete or uses an unexpected scheme."]
    if "@" in parts.netloc:
        evidence.append("The URL contains @, which can hide its real destination host.")
    if host.startswith("xn--") or ".xn--" in host:
        evidence.append("The domain uses punycode; verify the displayed name carefully.")
    try:
        ipaddress.ip_address(host)
        evidence.append("The destination is an IP address rather than a named site.")
    except ValueError:
        pass
    if host.count(".") >= 4:
        evidence.append("The domain has an unusually long chain of subdomains.")
    if len(url) > 180:
        evidence.append("The URL is unusually long.")
    return evidence


def _profile_assessment(profile):
    result = {
        "status": "insufficient_evidence",
        "bot_likelihood": "not_estimated",
        "evidence": [],
        "unavailable_checks": ["Independent account activity and identity verification are unavailable."],
        "action": "Check the account through an official channel before trusting sensitive requests.",
    }
    if not profile:
        return result
    for field in ("account_age_days", "posts_last_24h", "followers_count", "following_count"):
        value = profile.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"{field} must be a non-negative whole number")
    if profile.get("posts_last_24h", 0) >= 50:
        result["evidence"].append("The supplied data reports at least 50 posts in the last 24 hours; verify the activity pattern.")
    followers = profile.get("followers_count")
    following = profile.get("following_count")
    if followers is not None and following is not None and following >= 500 and following > 20 * max(followers, 1):
        result["evidence"].append("The supplied account follows many more accounts than follow it; this alone does not establish abuse.")
    official = _string(profile.get("official_domain"), 255).lower().removeprefix("www.")
    website = _string(profile.get("website_url"), 2048)
    if official and website and _host(website).lower().removeprefix("www.") != official:
        result["evidence"].append("The supplied profile website differs from the supplied official domain; verify both independently.")
    if result["evidence"]:
        result["status"] = "indicators_for_review"
    return result


def analyze(payload, known_phishing=None, model=None, url_model=None):
    """Assess submitted data without fetching URLs or scraping profiles."""
    if not isinstance(payload, dict):
        raise ValueError("Request must be a JSON object")
    message = _string(payload.get("message"), 10000)
    conversation = _string(payload.get("conversation"), 20000)
    supplied_url = _string(payload.get("url"), 2048)
    profile = payload.get("profile") or {}
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    if len(str(profile)) > 10000:
        raise ValueError("Profile data is too large")
    if not any((message, conversation, supplied_url, profile)):
        raise ValueError("Supply a message, URL, conversation, or profile details")
    match = URL_RE.search(message)
    url = supplied_url or (match.group(0).rstrip(".,);]") if match else "")
    evidence = []
    if message and PAYMENT_RE.search(message):
        evidence.append("The message asks for payment or a fee.")
    if message and SECRET_RE.search(message):
        evidence.append("The message asks for a password or verification code.")
    if message and URGENCY_RE.search(message):
        evidence.append("The message uses urgency to push a quick response.")
    url_evidence = _url_indicators(url)
    evidence.extend(url_evidence)
    known = known_phishing is not None and url in known_phishing
    if known:
        evidence.insert(0, "The exact submitted URL appears in the supplied verified phishing feed.")
    message_warning = bool(message and (PAYMENT_RE.search(message) or SECRET_RE.search(message)))
    level = "high" if known or (message_warning and url_evidence) else "review" if evidence else "low_observed_concern"
    unavailable = []
    if known_phishing is None:
        unavailable.append("Reputation feed is unavailable; absence of a match cannot show a link is safe.")
    elif url and not known:
        unavailable.append("The URL is not in the loaded reputation feed; unlisted links can still be harmful.")
    if not url:
        unavailable.append("No URL was supplied for destination checks.")
    fraud = {
        "level": level,
        "method": "evidence rules",
        "evidence": evidence,
        "unavailable_checks": unavailable,
        "uncertainty": "These observations cannot prove a message or link is safe or fraudulent.",
        "action": "Avoid entering credentials or paying through this link; verify the sender through an official channel." if level == "high" else "Verify unexpected requests through an official channel before acting.",
        "analyzed_url": url,
    }
    if model is not None and (message or url):
        from .research import predict

        votes = {}
        for mode in ("message", "url", "combined"):
            if mode == "message" and not message or mode == "url" and not url:
                continue
            vote = predict(model[mode], message, url, mode)
            votes[mode] = "suspicious" if vote else "not_flagged"
        fraud["model_votes"] = votes
        fraud["model_note"] = "Research model output is not calibrated and is separate from observed evidence."
    content = "\n".join(part for part in (message, conversation) if part)
    abuse = bool(ABUSE_RE.search(content))
    quoted_or_reported = bool(re.search(r"[\"“”]|\b(reported|quoted|someone wrote|someone said)\b", content, re.IGNORECASE))
    harmful = {
        "level": "review" if abuse else "low_observed_concern" if content else "not_assessed",
        "evidence": ["A direct insult or threat phrase appears in the submitted text." if not quoted_or_reported else "An insult or threat phrase appears in quoted or reported context; human review is needed."] if abuse else [],
        "uncertainty": "One text sample cannot establish a pattern of cyberbullying or the speaker's intent.",
        "action": "Review the surrounding conversation and preserve evidence before reporting abuse." if abuse else "Review the full context before drawing conclusions.",
    }
    result = {"fraud": fraud, "harmful_content": harmful, "profile": _profile_assessment(profile)}
    if url_model is not None:
        result["url_assessment"] = url_model.assess(supplied_url).to_dict()
    return result
