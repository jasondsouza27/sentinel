"""Bot-detection orchestration: validate -> collect data -> features -> score -> report.

Nothing is stored. Logs record platform, data source and outcome only, never
usernames, profile text or posts.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

from . import features as feature_extraction
from .adapters import SourceUnavailable, UpstreamError
from .adapters import reddit, supplied, youtube
from .adapters.supplied import InvalidData
from .platforms import PLATFORMS, InvalidAccount, describe, parse_account
from .scoring import HeuristicScorer

log = logging.getLogger("sentinel.bot_detection")
API_ADAPTERS = {"youtube": youtube, "reddit": reddit}
DISCLAIMER = ("This is a heuristic assessment of observable patterns. No single signal proves an account is a bot, "
              "and automated accounts are not necessarily malicious. Verify before acting or reporting.")


class BadRequest(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


class RateLimiter:
    """Sliding-window limit on analyses (the app is single-user and loopback-only)."""

    def __init__(self, limit=12, window_seconds=60, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window_seconds, clock
        self.events, self.lock = deque(), threading.Lock()

    def allow(self):
        with self.lock:
            now = self.clock()
            while self.events and now - self.events[0] > self.window:
                self.events.popleft()
            if len(self.events) >= self.limit:
                return False
            self.events.append(now)
            return True


class BotDetectionService:
    def __init__(self, scorer=None, limiter=None, adapters=None, ml_model=None, ml_activity_model=None):
        self.scorer = scorer or HeuristicScorer()
        self.ml_model = ml_model  # optional trained profile classifier (sentinel.bot_detection.ml.model)
        self.ml_activity_model = ml_activity_model  # optional activity + profile classifier
        self.limiter = limiter or RateLimiter()
        self.adapters = adapters or API_ADAPTERS

    def platforms(self):
        describe_model = lambda m: None if m is None else {
            "model_version": (m.manifest or {}).get("model_version"), "release": (m.manifest or {}).get("release"),
            "error": m.error}
        ml = describe_model(self.ml_model)
        return {"platforms": describe({name: module.configured() for name, module in self.adapters.items()}),
                "scoring": {"type": self.scorer.kind, "version": self.scorer.config["version"]}, "ml_model": ml,
                "ml_activity_model": describe_model(self.ml_activity_model)}

    def analyze(self, body):
        if not isinstance(body, dict):
            raise BadRequest("invalid_request", "Request must be a JSON object.")
        platform = body.get("platform")
        source = body.get("source")
        if platform not in PLATFORMS:
            raise BadRequest("unsupported_platform", "Choose one of: " + ", ".join(spec["name"] for spec in PLATFORMS.values()))
        if source not in ("api", "upload", "manual"):
            raise BadRequest("invalid_source", "Data source must be api, upload or manual.")
        try:
            account = parse_account(platform, body.get("account"))
        except InvalidAccount as error:
            raise BadRequest("invalid_account", str(error)) from None
        if not self.limiter.allow():
            raise BadRequest("rate_limited", "Too many analyses in a short time. Wait a minute and try again.", 429)
        try:
            data = self._collect(account, source, body)
        except (InvalidData, SourceUnavailable, UpstreamError) as error:
            code = getattr(error, "code", "invalid_data")
            log.info("bot analysis refused platform=%s source=%s code=%s", platform, source, code)
            status = 429 if code == "rate_limited" else 502 if isinstance(error, UpstreamError) and code != "not_found" else 400
            raise BadRequest(code, str(error), status) from None
        report = self.report(data)
        log.info("bot analysis platform=%s source=%s posts=%d class=%s confidence=%s", platform, source,
                 len(data.posts), report["classification"]["id"], report["confidence"]["level"])
        return report

    def _collect(self, account, source, body):
        if source == "api":
            adapter_name = PLATFORMS[account["platform"]]["api"]
            if not adapter_name:
                raise SourceUnavailable("api_not_available", PLATFORMS[account["platform"]]["api_note"])
            return self.adapters[adapter_name].fetch(account)
        if source == "upload":
            return supplied.from_upload(account, body.get("upload"))
        return supplied.from_manual(account, body.get("profile"))

    def report(self, data):
        features = feature_extraction.extract(data)
        posts = len(data.posts)
        result = self.scorer.score(features, posts)
        signals = result.pop("signals")
        suspicious = [s for s in signals if s["state"] == "suspicious"]
        human = [s for s in signals if s["state"] == "human_like" and s.get("text")]
        unavailable = [s for s in signals if s["state"] == "unavailable"]
        limitations = list(data.limitations)
        if unavailable:
            limitations.append(f"{len(unavailable)} of {len(signals)} signals could not be assessed with the available data.")
        if posts == 0:
            limitations.append("No posts were available, so activity and content patterns were not assessed.")
        return {
            "account": {"platform": data.platform, "platform_name": PLATFORMS[data.platform]["name"],
                        "username": data.username, "display_name": data.display_name, "source": data.source,
                        "account_age_days": features.get("account_age_days"), "followers": data.followers,
                        "following": data.following, "total_posts": data.total_posts, "verified": data.verified,
                        "posts_analysed": posts},
            **result,
            "suspicious_indicators": [{"id": s["id"], "category": s["category"], "text": s["text"],
                                       "contribution": s["contribution"]} for s in suspicious],
            "human_indicators": [{"id": s["id"], "category": s["category"], "text": s["text"]} for s in human],
            "signals": signals,
            "activity": {k: features.get(k) for k in ("posts_per_day", "span_days", "interval_cv", "regular_interval_share",
                                                     "active_hours", "night_gap_share", "burst_share", "repost_ratio",
                                                     "activity_change_ratio", "hour_histogram", "daily_counts")},
            "content": {k: features.get(k) for k in ("exact_duplicate_share", "near_duplicate_share", "hashtags_per_post",
                                                    "mentions_per_post", "urls_per_post", "top_domain_share",
                                                    "vocabulary_diversity", "spam_language_share")},
            "ml_model": self._ml(self.ml_model, data, features),
            "ml_activity_model": self._ml(self.ml_activity_model, data, features),
            "explanation": self._explain(result, suspicious, human),
            "limitations": limitations + [DISCLAIMER],
            "analysed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data_retention": "Nothing from this analysis was stored.",
        }

    def _ml(self, model, data, features):
        if model is None:
            return None
        account = {"followers": data.followers, "following": data.following, "posts": data.total_posts,
                   "age_days": features.get("account_age_days"), "bio": data.bio, "username": data.username,
                   "display_name": data.display_name, "has_url": bool(data.website)}
        try:
            return model.assess(data.platform, account, data.posts)
        except Exception:
            log.warning("bot ml model failed platform=%s", data.platform)
            return {"state": "unavailable", "reason": "inference_failed"}

    @staticmethod
    def _explain(result, suspicious, human):
        label = result["classification"]["label"]
        if result["classification"]["id"] == "insufficient_data":
            return ("There was not enough data to classify this account. Upload its recent posts or add profile "
                    "details for a meaningful assessment.")
        top = ", ".join(s["text"].rstrip(".").lower() for s in suspicious[:3])
        parts = [f"Classified as \"{label}\" with a bot-likeness score of {result['score']}/100 "
                 f"({result['confidence']['level'].lower()} confidence)."]
        parts.append(f"The strongest signals: {top}." if top else "No strong automation signals were found.")
        if result.get("coordination_flag"):
            parts.append("Coordination signals (repeated content, uniform engagement or follower jumps) are strong; "
                         "compare with related accounts before concluding it is part of a network.")
        if human:
            parts.append(f"{len(human)} human-like indicator{'s' if len(human) != 1 else ''} lowered the score.")
        return " ".join(parts)
