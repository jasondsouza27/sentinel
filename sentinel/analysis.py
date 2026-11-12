"""Cautious, explainable assessments. Rules are indicators, not trained models."""

import ipaddress
import re
from urllib.parse import urlsplit

from .harm_rules import assessment as harm_assessment


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
PAYMENT_RE = re.compile(r"\b(pay|payment|registration fee|processing fee|send money|upi)\b", re.IGNORECASE)
SECRET_RE = re.compile(r"\b(password|one.time password|otp|verification code|login details)\b", re.IGNORECASE)
URGENCY_RE = re.compile(r"\b(act now|immediately|urgent|within \d+ (?:minute|hour)|limited time)\b", re.IGNORECASE)
# The checks above match *mentions* and stay as they are: the paired and bot models were trained on them.
# Fraud evidence uses *requests*, so a bank alert that reports a UPI payment, or an email saying
# "never share your OTP", is not read as asking for money or a code.
PAYMENT_REQUEST_RE = re.compile(
    r"\b(?:(?:pay|send|transfer|deposit)\s+(?:(?:the|a|an|your|us|me|rs\.?|inr|usd|₹|\$)\s*)*"
    r"(?:\d|fee|fees|money|amount|charges?|deposit|now|immediately|today|token)"
    r"|(?:registration|processing|clearance|customs|redelivery|activation|verification|joining|release|handling)\s+(?:fee|charges?|amount)"
    r"|send\s+money|pay\s+(?:\w+\s+){0,3}(?:fee|fees|charges?))", re.IGNORECASE)
SECRET_REQUEST_RE = re.compile(
    r"\b(?:share|send|enter|provide|confirm|reply\s+with|give|tell|update|verify|submit)\s+(?:me\s+|us\s+)?(?:your\s+|the\s+)?"
    r"(?:one.time\s+password|otp|password|passcode|pin|upi\s+pin|cvv|card\s+(?:details|number)|bank\s+details|login\s+details|"
    r"verification\s+code|security\s+code|credentials)", re.IGNORECASE)
NEGATED_REQUEST_RE = re.compile(r"\b(?:never|don'?t|do\s+not|not|no\s+one\s+will|we\s+will\s+never|won'?t)\s+(?:\w+\s+){0,4}$", re.IGNORECASE)


def _asks(pattern, text):
    """A request that is not negated ("never share your OTP" is advice, not a request)."""
    return any(not NEGATED_REQUEST_RE.search(text[max(0, m.start() - 30):m.start()]) for m in pattern.finditer(text))


PRIZE_RE = re.compile(
    r"\b(?:you(?:'ve|\s+have)?\s+(?:won|been\s+selected\s+for\s+a\s+(?:prize|reward|gift))|claim\s+(?:your|the|a)?\s*(?:prize|reward|gift|cash|winnings)"
    r"|lucky\s+draw|lottery|jackpot|(?:cash\s+)?prize\s+of)\b", re.IGNORECASE)
# Original three-phrase rule, kept only as the frozen baseline used by research evaluation
# (sentinel/context_harm/evaluation.py). Live detection uses sentinel/harm_rules.py.
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


def analyze(payload, known_phishing=None, model=None, url_model=None, paired_model=None,
            harm_model=None, optional_budget=None, text_model=None, network=None):
    """Assess submitted data without fetching URLs or scraping profiles."""
    if not isinstance(payload, dict):
        raise ValueError("Request must be a JSON object")
    from .context_harm.conversation import parse_submission
    submitted_conversation = parse_submission(payload)
    message = submitted_conversation.model_input.target.strip()
    structured = any(key in payload for key in ("conversation_kind", "conversation_turns", "target_turn_id"))
    conversation = ("\n".join(submitted_conversation.model_input.context) if structured
                    else _string(payload.get("conversation"), 20000))
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
    if message and _asks(PAYMENT_REQUEST_RE, message):
        evidence.append("The message asks for payment or a fee.")
    if message and _asks(SECRET_REQUEST_RE, message):
        evidence.append("The message asks for a password, code or card details.")
    if message and PRIZE_RE.search(message):
        evidence.append("The message announces a prize or win, a common scam opener.")
    if message and URGENCY_RE.search(message):
        evidence.append("The message uses urgency to push a quick response.")
    url_evidence = _url_indicators(url)
    evidence.extend(url_evidence)
    known = known_phishing is not None and url in known_phishing
    if known:
        evidence.insert(0, "The exact submitted URL appears in the supplied verified phishing feed.")
    message_warning = bool(message and (_asks(PAYMENT_REQUEST_RE, message) or _asks(SECRET_REQUEST_RE, message)))
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
    harmful = harm_assessment(content)
    result = {"fraud": fraud, "harmful_content": harmful, "profile": _profile_assessment(profile)}
    if url_model is not None:
        def url_unavailable():
            from .url_ml.contracts import UrlAssessment
            return UrlAssessment("unavailable", None, None, (),
                ("The optional URL check could not assess this input.",),
                ("The optional-model budget is busy or the worker is unavailable.",),
                "Verify independently or retry after the current assessment.").to_dict()
        try:
            operation = lambda: url_model.assess(supplied_url).to_dict()
            result["url_assessment"] = (optional_budget.run("url", operation, url_unavailable)
                                         if optional_budget else operation())
        except Exception:
            result["url_assessment"] = url_unavailable()
    if paired_model is not None:
        try:
            from .paired.service import unavailable
            operation = lambda: paired_model.assess(message, url)
            result["paired_assessment"] = (optional_budget.run("paired", operation,
                lambda: unavailable("optional_model_busy")) if optional_budget else operation())
        except Exception:
            from .paired.service import unavailable
            result["paired_assessment"] = unavailable(
                "inference_unavailable", "The paired model could not assess this input.")
    if text_model is not None:
        try:
            result["text_model"] = text_model.assess(message)
        except Exception:
            result["text_model"] = {"state": "unavailable", "reason": "inference_failed", "model_version": None}
    if network is not None and message:
        try:
            match = network.match(message)
            learned = result.get("text_model") or {}
            if learned.get("flagged") and learned.get("calibrated_probability", 0) >= 0.9:
                network.report(message, learned["category"], learned["calibrated_probability"])
            result["community"] = {"state": "matched" if match else "no_match", "match": match,
                                   "note": "Compared with campaigns other Sentinel users flagged; only anonymous fingerprints are shared."}
        except Exception:
            result["community"] = {"state": "unavailable", "match": None}
    if harm_model is not None:
        from .context_harm.service import unavailable
        try:
            operation = lambda: harm_model.assess(submitted_conversation)
            result["harm_assessment"] = (optional_budget.run("harm", operation,
                lambda: unavailable(submitted_conversation, "optional_model_busy"))
                if optional_budget else operation())
        except Exception:
            result["harm_assessment"] = unavailable(submitted_conversation, "inference_unavailable")
    return result
